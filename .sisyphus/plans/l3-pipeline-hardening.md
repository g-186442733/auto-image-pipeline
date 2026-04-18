# L3 Pipeline Hardening — 流水线闭环与健壮性补齐

## TL;DR

> **Quick Summary**: 将 5 层架构审计发现的 P0-P2 缺失功能补齐，实现 orchestrator 完整闭环（deliver + feedback wiring）、Brief 多槽保存、Phase 1 容错、A+ Content 数据模型。
>
> **Deliverables**:
>
> - `step_deliver` 接入 `run_full_pipeline` 主流程
> - Brief 生成从单条硬编码改为按 slot 循环保存
> - `update_brand_profile_from_results` 接入 orchestrator（含 BrandProfile guard）
> - Phase 1 Amazon 抓取加 try/except 容错
> - A+ Content ORM model + 文件上传 endpoint
>
> **Estimated Effort**: Medium（5 tasks, 2 waves）
> **Parallel Execution**: YES — 2 waves
> **Critical Path**: T2/T5 (Wave 1, parallel) → T1 → T3 → T4 (Wave 2, sequential on orchestrator.py)

---

## Context

### Original Request

5 层架构审计完成后，老板确认 P0-P2 级缺失功能可以做，要求列计划执行。

### Interview Summary

**Key Discussions**:

- 老板确认 5 个任务（T1-T5）均为可执行范围
- 波次规划需避免 orchestrator.py 并发冲突
- 所有改动需保持 192 测试全绿

**Research Findings**:

- `step_deliver` 已有完整实现（`delivery.py`），只需在 orchestrator 加一行调用
- Brief 生成的 Gemini 返回已是多槽 JSON，保存逻辑硬编码 `slot_index=0` 是唯一瓶颈
- `update_brand_profile_from_results` 完整实现但零调用点
- Phase 1 的 `fetch_asin_detail` + `fetch_category_top` 无任何 try/except

### Metis Review

**Identified Gaps** (addressed):

- orchestrator.py 并发冲突风险 → Wave 2 串行处理
- step_deliver 空包处理 → guard + early return
- BrandProfile 不存在时 feedback wiring 会崩 → guard-and-log-warning
- Brief 0 slots 边界 → guard + 返回空列表

---

## Work Objectives

### Core Objective

补齐 orchestrator 主流程缺失环节，实现 init→analyze→plan→generate→qa→report→**deliver→feedback** 完整闭环，并提升 Phase 1 容错能力。

### Concrete Deliverables

- `orchestrator.py`: 新增 `step_deliver()` 调用 + feedback wiring + Phase 1 try/except
- `brief_generator.py`: 循环保存多条 ImageBrief（按 Gemini 返回的 slots 数量）
- `models/aplus_content.py`: 新 ORM model
- `web/app.py`: 文件上传 endpoint

### Definition of Done

- [x] `aip run <project_id>` 执行到 deliver + feedback 步骤，无报错
- [x] Brief 生成后 DB 中有 ≥1 条 ImageBrief（slot_index 从 0 开始递增）
- [x] Phase 1 单个 fetch 失败不中断整个 step_analyze
- [x] `pytest tests/` 全绿（≥192 tests）

### Must Have

- step_deliver 接入主流程
- Brief 多槽保存
- Phase 1 容错
- Feedback wiring with BrandProfile guard

### Must NOT Have (Guardrails)

- ❌ step_deliver 不加 retry/通知/webhook（scope creep）
- ❌ 不改 Gemini prompt 或 JSON 解析逻辑（T2 只改保存循环）
- ❌ 不自动创建 BrandProfile（guard-and-log-warning only）
- ❌ Phase 1 不加 retry 机制，只 catch + log + 软失败
- ❌ 不改 happy path 逻辑（只包 try/except）
- ❌ 不用 `as any`（TypeScript 禁止）
- ❌ 不用 `<style>` 内联 CSS

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES（pytest, 192 tests）
- **Automated tests**: Tests-after（每个 task 写对应测试）
- **Framework**: pytest + unittest.mock

### QA Policy

每个 task 包含 agent-executed QA scenarios。
Evidence 保存到 `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`。

- **Backend/Pipeline**: Bash（pytest, aip CLI commands）
- **API Endpoint**: Bash（curl）

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — 不同文件，完全并行):
├── T2: Brief per-slot expansion (brief_generator.py) [quick]
└── T5: A+ Content model + file upload endpoint (新文件 + web/app.py) [unspecified-high]

Wave 2 (After Wave 1 — 全在 orchestrator.py，串行避免冲突):
├── T1: Wire step_deliver into run_full_pipeline (orchestrator.py) [quick]
├── T3: Wire feedback loop with BrandProfile guard (orchestrator.py) [quick]
└── T4: Phase 1 resilience — try/except around Amazon fetches (orchestrator.py) [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real QA — run aip pipeline end-to-end (unspecified-high)
└── F4: Scope fidelity check (deep)
→ Present results → Get explicit user okay
```

### Dependency Matrix

| Task  | Depends On | Blocks    |
| ----- | ---------- | --------- |
| T2    | —          | Wave 2    |
| T5    | —          | Wave 2    |
| T1    | T2, T5     | T3        |
| T3    | T1         | T4        |
| T4    | T3         | FINAL     |
| F1-F4 | T1-T5      | user okay |

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T2 → `quick`, T5 → `unspecified-high`
- **Wave 2**: 3 tasks — T1 → `quick`, T3 → `quick`, T4 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 2. Brief Per-Slot Expansion — 循环保存多条 ImageBrief

  **What to do**:
  - 修改 `pipeline/layers/brief_generator.py` 的 `generate_brief()` 函数（约 L56-95）
  - 当前逻辑：Gemini 返回 `{"slots": [...]}` 后，硬编码 `slot_index=0` 只保存第一条
  - 改为：`for i, slot_data in enumerate(slots)` 循环，每个 slot 创建一条 `ImageBrief(slot_index=i, ...)`
  - Guard：如果 Gemini 返回 0 个 slots，log warning 并返回空列表
  - 填写 `source_analysis_ids` 字段（当前从未写入）：将传入的 analysis ID 列表 JSON 序列化后存入
  - 函数返回类型从 `ImageBrief` 改为 `list[ImageBrief]`
  - 更新所有调用点（`orchestrator.py` 的 `step_plan()`）以处理列表返回值
  - 写测试：mock Gemini 返回 3 slots → 验证 DB 中有 3 条 ImageBrief；mock 返回 0 slots → 验证空列表 + warning log

  **Must NOT do**:
  - 不改 Gemini prompt 内容
  - 不改 JSON 解析逻辑（`json.loads` 部分不动）
  - 不改 SlotPlan 相关代码

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件核心改动（brief_generator.py），逻辑简单（for 循环替代单条保存）
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T5)
  - **Blocks**: Wave 2 (T1, T3, T4)
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `pipeline/layers/brief_generator.py:56-95` — 当前 `generate_brief()` 实现，硬编码 `slot_index=0` 在约 L85 附近
  - `pipeline/models/image_brief.py` — ImageBrief ORM model，含 `slot_index` 和 `source_analysis_ids` 字段

  **API/Type References**:
  - `pipeline/layers/slot_planner.py` — SlotPlan model 有 `intent_tag`, `layout_tag` 等字段可参考

  **Test References**:
  - `tests/` 目录下现有 brief 相关测试 — 复用 mock 和 fixture 模式

  **Acceptance Criteria**:
  - [x] `generate_brief()` 返回 `list[ImageBrief]`
  - [x] Gemini 返回 N slots → DB 中 N 条 ImageBrief，slot_index = 0..N-1
  - [x] Gemini 返回 0 slots → 空列表 + warning log
  - [x] `source_analysis_ids` 字段被正确填写
  - [x] `pytest tests/` 全绿

  **QA Scenarios:**

  ```
  Scenario: Multi-slot brief generation
    Tool: Bash (pytest)
    Preconditions: Mock Gemini adapter 返回 {"slots": [slot0, slot1, slot2]}
    Steps:
      1. pytest tests/test_brief_multi_slot.py -v
      2. 断言 session.query(ImageBrief).filter_by(project_id=X).count() == 3
      3. 断言 slot_index 分别为 0, 1, 2
    Expected Result: 3 条 ImageBrief，slot_index 递增
    Evidence: .sisyphus/evidence/task-2-multi-slot-brief.txt

  Scenario: Zero slots edge case
    Tool: Bash (pytest)
    Preconditions: Mock Gemini adapter 返回 {"slots": []}
    Steps:
      1. pytest tests/test_brief_zero_slots.py -v
      2. 断言返回空列表 + warning log
    Expected Result: 空列表，无异常
    Evidence: .sisyphus/evidence/task-2-zero-slots.txt
  ```

  **Commit**: YES
  - Message: `fix(brief): save all slots from Gemini response instead of hardcoded slot_index=0`
  - Files: `pipeline/layers/brief_generator.py`, `tests/test_brief_*.py`
  - Pre-commit: `pytest tests/`

- [x] 5. A+ Content Model + File Upload Endpoint

  **What to do**:
  - 创建 `pipeline/models/aplus_content.py`：`APlusContent` ORM model
    - 字段：`id`, `project_id` (FK), `module_type` (enum: STANDARD/PREMIUM/BRAND_STORY), `headline`, `body_text`, `image_refs` (JSON list), `position_index`, `created_at`, `updated_at`
    - 关系：`project = relationship("Project", back_populates="aplus_contents")`
  - 在 `pipeline/models/__init__.py` 注册新 model
  - 在 `pipeline/web/app.py` 添加 `POST /api/projects/<project_id>/upload`
    - 接收 multipart file，保存到 `uploads/<project_id>/`，返回文件路径 JSON
    - 图片类型验证（png/jpg/jpeg/webp），文件大小限制 10MB
  - 写测试：model CRUD + upload endpoint

  **Must NOT do**:
  - 不改现有 models 的字段
  - 不加 A+ Content 业务逻辑（只定义 model + 存储）
  - 不加认证/鉴权

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 跨多个文件（新 model + **init**.py + app.py + tests）
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T2)
  - **Blocks**: Wave 2
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `pipeline/models/image_brief.py` — 现有 ORM model 模式
  - `pipeline/models/__init__.py` — model 注册方式
  - `pipeline/web/app.py` — 现有 Flask route 模式

  **API/Type References**:
  - `pipeline/models/project.py` — Project model（APlusContent FK 目标）

  **Acceptance Criteria**:
  - [x] `APlusContent` model 可 `create_all()` 建表
  - [x] `POST /api/projects/<id>/upload` 返回 200 + 文件路径
  - [x] 非图片文件返回 400；超 10MB 返回 413
  - [x] `pytest tests/` 全绿

  **QA Scenarios:**

  ```
  Scenario: APlusContent model CRUD
    Tool: Bash (pytest)
    Steps:
      1. 创建 APlusContent + commit + 查询
      2. 断言字段值匹配
    Expected Result: CRUD 成功
    Evidence: .sisyphus/evidence/task-5-aplus-model.txt

  Scenario: File upload happy path
    Tool: Bash (pytest with Flask test client)
    Steps:
      1. POST multipart 图片到 /api/projects/<id>/upload
      2. 断言 HTTP 200 + response JSON 含 "path"
    Expected Result: 200 + 路径
    Evidence: .sisyphus/evidence/task-5-upload-happy.txt

  Scenario: Invalid file type rejection
    Tool: Bash (pytest)
    Steps:
      1. POST .txt 文件到同一 endpoint
      2. 断言 HTTP 400
    Expected Result: 400 + error
    Evidence: .sisyphus/evidence/task-5-upload-invalid.txt
  ```

  **Commit**: YES
  - Message: `feat(models): add APlusContent model and file upload endpoint`
  - Files: `pipeline/models/aplus_content.py`, `pipeline/models/__init__.py`, `pipeline/web/app.py`, `tests/test_aplus_*.py`
  - Pre-commit: `pytest tests/`

- [x] 1. Wire step_deliver into run_full_pipeline

  **What to do**:
  - 在 `pipeline/orchestrator.py` 的 `run_full_pipeline()` 中，`step_report()` 之后添加 `step_deliver()` 调用
  - 新增 `step_deliver(project_id, session)` 函数：
    - 调用 `build_delivery_package(project_id, session)` from `pipeline.layers.delivery`
    - Guard：如果返回的包路径为空或目录为空（无 generated images），log warning + 跳过（不 raise）
    - log.info 输出包路径
  - 写测试：mock `build_delivery_package` 返回路径 → 验证被调用；mock 返回空 → 验证 warning log

  **Must NOT do**:
  - 不加 retry/通知/webhook
  - 不改 `build_delivery_package` 本身
  - 不改其他 step 函数

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件改动，加一个 wrapper 函数 + 一行调用
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential: T1 → T3 → T4)
  - **Blocks**: T3
  - **Blocked By**: T2, T5 (Wave 1)

  **References**:

  **Pattern References**:
  - `pipeline/orchestrator.py` — `run_full_pipeline()` 函数，当前末尾是 `step_report()`；其他 step\_\* 函数的签名和 log 模式
  - `pipeline/layers/delivery.py` — `build_delivery_package(project_id, session=None) -> str`，已完整实现

  **Acceptance Criteria**:
  - [x] `run_full_pipeline()` 流程包含 step_deliver
  - [x] 有 generated images → delivery package 被创建
  - [x] 无 generated images → warning log，不 raise
  - [x] `pytest tests/` 全绿

  **QA Scenarios:**

  ```
  Scenario: step_deliver called in pipeline
    Tool: Bash (pytest)
    Steps:
      1. Mock all steps + build_delivery_package
      2. 调用 run_full_pipeline
      3. 断言 build_delivery_package 被调用 1 次
    Expected Result: deliver 步骤在 report 之后执行
    Evidence: .sisyphus/evidence/task-1-deliver-wired.txt

  Scenario: Empty delivery package
    Tool: Bash (pytest)
    Steps:
      1. Mock build_delivery_package 返回空目录路径
      2. 断言 step_deliver 不 raise
      3. 断言 log 包含 warning
    Expected Result: 软失败 + warning
    Evidence: .sisyphus/evidence/task-1-deliver-empty.txt
  ```

  **Commit**: YES
  - Message: `feat(orchestrator): wire step_deliver into run_full_pipeline`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_*.py`
  - Pre-commit: `pytest tests/`

- [x] 3. Wire Feedback Loop with BrandProfile Guard

  **What to do**:
  - 在 `pipeline/orchestrator.py` 的 `run_full_pipeline()` 中，`step_deliver()` 之后添加 feedback wiring
  - 新增 `step_feedback(project_id, session)` 函数：
    - 查询 BrandProfile 是否存在：`session.query(BrandProfile).filter_by(project_id=project_id).first()`
    - 如果不存在：log.warning("No BrandProfile found for project {project_id}, skipping feedback loop") + return
    - 如果存在：调用 `update_brand_profile_from_results(project_id)` from `pipeline.layers.feedback_loop`
  - 写测试：有 BrandProfile → 验证 update 被调用；无 BrandProfile → 验证 warning + 不调用 update

  **Must NOT do**:
  - 不自动创建 BrandProfile（guard-and-log-warning only）
  - 不改 `update_brand_profile_from_results` 本身
  - 不加 retry

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件，简单 guard 逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential: T1 → T3 → T4)
  - **Blocks**: T4
  - **Blocked By**: T1

  **References**:

  **Pattern References**:
  - `pipeline/orchestrator.py` — step\_\* 函数模式
  - `pipeline/layers/feedback_loop.py` — `update_brand_profile_from_results(project_id)` 签名和实现
  - `pipeline/models/brand_profile.py` — BrandProfile model

  **Acceptance Criteria**:
  - [x] `run_full_pipeline()` 流程包含 step_feedback
  - [x] 有 BrandProfile → update_brand_profile_from_results 被调用
  - [x] 无 BrandProfile → warning log，不 raise，不创建 BrandProfile
  - [x] `pytest tests/` 全绿

  **QA Scenarios:**

  ```
  Scenario: Feedback with existing BrandProfile
    Tool: Bash (pytest)
    Steps:
      1. 创建 Project + BrandProfile in test DB
      2. Mock update_brand_profile_from_results
      3. 调用 step_feedback
      4. 断言 update 被调用 1 次
    Expected Result: feedback 执行
    Evidence: .sisyphus/evidence/task-3-feedback-exists.txt

  Scenario: Feedback without BrandProfile
    Tool: Bash (pytest)
    Steps:
      1. 创建 Project（无 BrandProfile）
      2. 调用 step_feedback
      3. 断言 update 未被调用
      4. 断言 log 包含 "No BrandProfile"
    Expected Result: 跳过 + warning
    Evidence: .sisyphus/evidence/task-3-feedback-no-profile.txt
  ```

  **Commit**: YES
  - Message: `feat(orchestrator): wire feedback loop with BrandProfile guard`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_*.py`
  - Pre-commit: `pytest tests/`

- [x] 4. Phase 1 Resilience — try/except around Amazon Fetches

  **What to do**:
  - 在 `pipeline/orchestrator.py` 的 `step_analyze()` 中，给 Phase 1 的两个调用加 try/except：
    - `fetch_asin_detail(asin)` — catch `Exception`，log.error + 设 `asin_detail = None`
    - `fetch_category_top(category)` — catch `Exception`，log.error + 设 `category_top = None`
  - 下游逻辑需处理 None（检查 Phase 2 的各函数是否已 handle None 输入 — 根据调研它们已有独立 try/except）
  - 如果两个都失败（asin_detail 和 category_top 都是 None），log.warning 但**仍继续** Phase 2（Phase 2 各函数自己有容错）
  - 写测试：mock fetch 抛异常 → 验证不 abort + warning log

  **Must NOT do**:
  - 不加 retry 机制
  - 不改 happy path 逻辑
  - 不改 Phase 2 的 try/except
  - 只 catch 特定异常类（`requests.RequestException`, `Exception`），不用 bare `except`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件，两处加 try/except
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential: T1 → T3 → T4)
  - **Blocks**: FINAL
  - **Blocked By**: T3

  **References**:

  **Pattern References**:
  - `pipeline/orchestrator.py` — `step_analyze()` 函数，Phase 1 部分（fetch_asin_detail, fetch_category_top 调用处）
  - `pipeline/orchestrator.py` — Phase 2 的 try/except 模式（复用相同风格）

  **Acceptance Criteria**:
  - [x] `fetch_asin_detail` 失败 → `asin_detail = None`，log.error，不 abort
  - [x] `fetch_category_top` 失败 → `category_top = None`，log.error，不 abort
  - [x] 两个都失败 → Phase 2 仍执行
  - [x] `pytest tests/` 全绿

  **QA Scenarios:**

  ```
  Scenario: Phase 1 fetch failure resilience
    Tool: Bash (pytest)
    Steps:
      1. Mock fetch_asin_detail 抛 requests.RequestException
      2. Mock fetch_category_top 正常返回
      3. 调用 step_analyze
      4. 断言 step 完成（不 raise）
      5. 断言 log 包含 error message
    Expected Result: step_analyze 完成，Phase 2 继续
    Evidence: .sisyphus/evidence/task-4-phase1-resilience.txt

  Scenario: Both Phase 1 fetches fail
    Tool: Bash (pytest)
    Steps:
      1. Mock 两个 fetch 都抛异常
      2. 调用 step_analyze
      3. 断言不 abort + warning log
    Expected Result: Phase 2 仍执行
    Evidence: .sisyphus/evidence/task-4-both-fail.txt
  ```

  **Commit**: YES
  - Message: `fix(orchestrator): add try/except around Phase 1 Amazon fetches`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_*.py`
  - Pre-commit: `pytest tests/`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE.
> Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
      Run `pytest tests/`. Review all changed files for: empty catches, print in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real QA — Pipeline End-to-End** — `unspecified-high`
      Start from clean state. Run `PYTHONPATH=. python -m pipeline.__main__ run <test_project_id>` and verify all steps complete including deliver and feedback. Test edge cases: empty generated images (deliver), missing BrandProfile (feedback), Phase 1 fetch failure (mock network error).
      Output: `Scenarios [N/N pass] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| After | Message                                                                             | Files                                                            | Pre-commit      |
| ----- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------- | --------------- |
| T2    | `fix(brief): save all slots from Gemini response instead of hardcoded slot_index=0` | `brief_generator.py`, `tests/test_brief_*.py`                    | `pytest tests/` |
| T5    | `feat(models): add APlusContent model and file upload endpoint`                     | `models/aplus_content.py`, `web/app.py`, `tests/test_aplus_*.py` | `pytest tests/` |
| T1    | `feat(orchestrator): wire step_deliver into run_full_pipeline`                      | `orchestrator.py`, `tests/test_orchestrator_*.py`                | `pytest tests/` |
| T3    | `feat(orchestrator): wire feedback loop with BrandProfile guard`                    | `orchestrator.py`, `tests/test_orchestrator_*.py`                | `pytest tests/` |
| T4    | `fix(orchestrator): add try/except around Phase 1 Amazon fetches`                   | `orchestrator.py`, `tests/test_orchestrator_*.py`                | `pytest tests/` |

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. pytest tests/ -q  # Expected: ≥197 passed, 0 failed
PYTHONPATH=. python -m pipeline.__main__ run <project_id>  # Expected: completes through deliver + feedback
```

### Final Checklist

- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All tests pass (≥197)
- [x] step_deliver in run_full_pipeline flow
- [x] Brief saves multiple slots
- [x] Feedback wiring with BrandProfile guard
- [x] Phase 1 resilient to individual fetch failures
- [x] A+ Content model exists
