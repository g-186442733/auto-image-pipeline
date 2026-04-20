# L1-L4 全量功能测试（重点：出图质量）

## TL;DR

> **Quick Summary**: 补全 L1-L4 测试覆盖缺口，重点验证出图质量链路（QA 5道门→评分过滤→交付打包），然后跑全量测试确保系统符合 PRD。
>
> **Deliverables**:
>
> - 补写 ~8 个测试文件/场景，覆盖质量链路边界条件
> - 全量测试 PASS（594+ passed，27 pre-existing failures 不变）
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Wave 1 (补写测试) → Wave 2 (全量跑测 + 修复)

---

## Context

### Original Request

对 auto-image-pipeline 系统 L1-L4 已实现功能做全量测试验证，确保系统符合 `系统流程说明.md` (PRD)。老板特别强调：**把出图质量考虑进去，用户最关心的是这个。**

### Research Findings

- qa_gate.py (708行)：5道Gate串行，两套QA入口（LLM + legacy），Gate5公式 = 0.4×tag + 0.4×brand + 0.2×resolution
- delivery.py：QA总分 <70 的 asset 被跳过不打包
- prompt_engine.py (246行)：Jinja2模板 + 品牌约束 + negative_prompt
- slot_planner.py：8槽位 × 4维标签，需 AmazonBenchmark 数据
- 现有8个核心测试文件覆盖基本 happy/fail path，但缺边界条件和跨组件集成

---

## Work Objectives

### Core Objective

验证 L1-L4 全链路功能正确，重点确保出图质量链路（QA Gate → Delivery filtering）无遗漏。

### Must Have

- 出图质量链路全覆盖：Gate1-5 各自边界 + 串行逻辑 + 评分过滤
- Prompt 组装质量：品牌约束注入、negative_prompt、变量缺失处理
- Delivery 质量过滤：<70分跳过、manifest 正确性
- 全量测试通过（不引入新 failure）

### Must NOT Have (Guardrails)

- 不修改业务源码（只写测试）
- 不触碰 L5 (ab_tests, performance_score, feedback loop)
- 不新增 pip 依赖
- 不修改 pre-existing 27 failures 的测试
- 不写集成测试/E2E（scope 限定为 unit + 组件级测试）

---

## Verification Strategy

### Test Decision

- **Infrastructure exists**: YES (pytest + conftest.py)
- **Automated tests**: YES (Tests-after — 补写缺口测试)
- **Framework**: pytest
- **Test command**: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`
- **Baseline**: 594 passed + 27 pre-existing failures

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (补写测试 - MAX PARALLEL):
├── Task 1: QA Gate 串行边界测试 [quick]
├── Task 2: Gate5 评分公式边界测试 [quick]
├── Task 3: Delivery 质量过滤测试 [quick]
├── Task 4: Prompt Engine 品牌约束 + 边界测试 [quick]
├── Task 5: Slot Planner 标签完整性测试 [quick]
├── Task 6: LLM QA 入口边界测试 [quick]

Wave 2 (验证 - 串行):
├── Task 7: 全量测试运行 + 修复 [deep]

Wave FINAL:
└── Task F1: 测试结果审计 [quick]
```

### Dependency Matrix

- **1-6**: None → 7
- **7**: 1-6 → F1
- **F1**: 7 → done

---

## TODOs

- [x] 1. QA Gate 串行边界测试

  **What to do**:
  - 在 `tests/test_qa_gate_5doors.py` 中补充边界场景：
    - Gate1: 文件恰好 10MB（边界 pass）、1000x999 像素（边界 fail）、非 jpg/png 格式（如 .webp）
    - Gate2: 损坏图片文件（PIL 无法打开）、宽=0 的退化图片
    - Gate3: project 存在但 ReferencePack 为空列表 vs None
    - Gate4: ConsistencyProfile 存在但 `validate_consistency` 返回 False
    - run_qa_gate: 第一个 Gate fail 时后续仍然执行（验证串行不短路）
  - 所有测试用 mock，不依赖真实文件/数据库

  **Must NOT do**: 修改 qa_gate.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-6)
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/qa_gate.py:check_compliance` — Gate1: format in (jpg,jpeg,png), size ≥1000x1000, filesize ≤10MB
  - `pipeline/layers/qa_gate.py:check_visual_anchor` — Gate2: PIL.Image.open + 宽高≠0
  - `pipeline/layers/qa_gate.py:run_qa_gate` — 串行执行5门，收集所有结果
  - `tests/test_qa_gate_5doors.py` — 已有测试结构，在此文件追加

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate_5doors.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: 边界测试全部通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate_5doors.py -v 2>&1
      2. 检查输出包含所有新增 test function 名称且状态为 PASSED
    Expected Result: 0 failures, 新增 ≥5 个测试
    Evidence: .sisyphus/evidence/task-1-qa-gate-boundary.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 2. Gate5 评分公式边界测试

  **What to do**:
  - 在 `tests/test_qa_gate5.py` 中补充：
    - 精确边界：score = 0.6（恰好 pass）、score = 0.599（fail）
    - tag_coverage=0, brand_consistency=0, resolution=0 → score=0 fail
    - tag_coverage=1, brand_consistency=1, resolution<1024 → 验证 0.2 权重影响
    - 非标分辨率：1023x1024（一边不达标）

  **Must NOT do**: 修改 qa_gate.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/qa_gate.py:compute_gate5_score` — 公式：0.4×tag + 0.4×brand + 0.2×resolution(≥1024→1.0)，阈值 ≥0.6
  - `tests/test_qa_gate5.py` — 已有4个场景，追加边界场景

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate5.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: 边界评分测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate5.py -v 2>&1
      2. 确认新增 ≥3 个 test function 且全部 PASSED
    Expected Result: 0 failures
    Evidence: .sisyphus/evidence/task-2-gate5-boundary.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 3. Delivery 质量过滤测试

  **What to do**:
  - 在 `tests/test_delivery.py` 中补充：
    - QA 总分 = 69（<70，应被跳过不打包）
    - QA 总分 = 70（恰好 pass，应包含在 package）
    - 混合场景：3个 asset（85分、69分、72分）→ 只有2个被打包
    - manifest.json 中只包含 passed assets 的条目
    - 无任何 asset 通过 QA → 空 package 处理

  **Must NOT do**: 修改 delivery.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/delivery.py:build_delivery_package` — QA score <70 跳过逻辑
  - `tests/test_delivery.py` — 已有6个场景，追加过滤边界

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_delivery.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: 质量过滤边界测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_delivery.py -v 2>&1
      2. 确认新增 ≥4 个 test function 且全部 PASSED
    Expected Result: 0 failures
    Evidence: .sisyphus/evidence/task-3-delivery-filter.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 4. Prompt Engine 品牌约束 + 边界测试

  **What to do**:
  - 在 `tests/test_prompt_engine_v2.py` 中补充：
    - assemble_prompt: brand_profile 为 None → prompt 不含品牌约束段
    - assemble_prompt: reference_pack 存在 → prompt 包含参考图描述
    - assemble_prompt: negative_prompt 注入验证
    - assemble_prompt: 缺少必需变量（如缺 composition）→ 验证 Jinja2 错误处理
    - build_prompt: project 无 ImageBrief → 验证 fallback 行为
    - generate_slot_prompts: SlotPlan 为空 → 返回空列表

  **Must NOT do**: 修改 prompt_engine.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/prompt_engine.py:assemble_prompt` — Jinja2 渲染 + brand_profile + reference_pack + negative_prompt
  - `pipeline/layers/prompt_engine.py:build_prompt` — 从 ImageBrief+BrandProfile 组装
  - `pipeline/layers/prompt_engine.py:generate_slot_prompts` — 遍历 SlotPlan
  - `tests/test_prompt_engine_v2.py` — 已有测试结构

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_prompt_engine_v2.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: Prompt 品牌约束测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_prompt_engine_v2.py -v 2>&1
      2. 确认新增 ≥5 个 test function 且全部 PASSED
    Expected Result: 0 failures
    Evidence: .sisyphus/evidence/task-4-prompt-engine.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 5. Slot Planner 标签完整性测试

  **What to do**:
  - 在 `tests/test_slot_planner_v2.py` 中补充：
    - 8个槽位全部生成（验证数量 = 8）
    - 每个槽位有完整4维标签（intent, layout, style, color）
    - ImageBrief.target_tags 部分缺失 → 缺失维度用默认值填充
    - AmazonBenchmark 为空 → 返回空计划 + error code E_PLANNER_001
    - tag_system.assign_tags 被调用且参数正确

  **Must NOT do**: 修改 slot_planner.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/slot_planner.py` — 8槽位 × 4维标签，AmazonBenchmark 依赖
  - `tests/test_slot_planner_v2.py` — 已有4个场景

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_slot_planner_v2.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: 标签完整性测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_slot_planner_v2.py -v 2>&1
      2. 确认新增 ≥4 个 test function 且全部 PASSED
    Expected Result: 0 failures
    Evidence: .sisyphus/evidence/task-5-slot-planner.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 6. LLM QA 入口边界测试

  **What to do**:
  - 在 `tests/test_qa_gate_llm.py` 中补充：
    - run_qa_checks: Gemini 返回 score=70（边界 pass）和 score=69（边界 fail）
    - run_qa_checks: goal_brief 为空 → 验证 fallback 行为
    - run_qa_checks_legacy: 6项检查中某项返回0分 → 总分计算正确
    - step_qa: max_retries=2 时第3次仍 fail → 最终 FAIL 状态
    - step_qa: 第1次 fail、第2次 pass → 最终 PASS

  **Must NOT do**: 修改 qa_gate.py 源码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/qa_gate.py:run_qa_checks` — LLM QA 入口，score ≥70 pass
  - `pipeline/layers/qa_gate.py:run_qa_checks_legacy` — 6项检查均分
  - `pipeline/layers/qa_gate.py:step_qa` — 重试逻辑 max_retries=2
  - `tests/test_qa_gate_llm.py` — 已有测试（200行）

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate_llm.py -q` → 全部 PASS

  **QA Scenarios**:

  ```
  Scenario: LLM QA 边界测试通过
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate_llm.py -v 2>&1
      2. 确认新增 ≥4 个 test function 且全部 PASSED
    Expected Result: 0 failures
    Evidence: .sisyphus/evidence/task-6-llm-qa.txt
  ```

  **Commit**: YES (groups with Wave 1)

- [x] 7. 全量测试运行 + 修复

  **What to do**:
  - 运行完整测试套件：`PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`
  - 对比基线：passed ≥ 594，failed = 27 (pre-existing)
  - 如有新增 failure：分析原因，修复测试代码（不改源码）
  - 如新增测试导致 import 冲突或 fixture 问题，修复 conftest.py
  - 保存完整测试输出

  **Must NOT do**: 修改业务源码，只修复测试代码

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (串行)
  - **Blocks**: F1
  - **Blocked By**: Tasks 1-6

  **References**:
  - 所有 `tests/` 下测试文件
  - `tests/conftest.py` — 共享 fixtures
  - Pre-existing failures: test_drl_scheduler(6), test_event_trigger(3), test_hypothesis_crud(4), test_integration_pipeline(4+), test_tag_review_routes(4)

  **Acceptance Criteria**:
  - [ ] passed ≥ 594, failed = 27, 0 errors

  **QA Scenarios**:

  ```
  Scenario: 全量测试通过基线
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py 2>&1
      2. 末行检查 "N passed, 27 failed"
      3. 确认 N ≥ 594
    Expected Result: passed ≥ 594, failed = 27, 0 errors
    Evidence: .sisyphus/evidence/task-7-full-test-run.txt
  ```

  **Commit**: YES
  - Message: `test(l1-l4): add quality chain coverage and verify full suite`

---

## Final Verification Wave

- [x] F1. **测试结果审计**
      运行全量测试，确认 passed ≥ 594，failed = 27 (pre-existing only)，无新增 failure。将输出保存为 `.sisyphus/evidence/l1-l4-test-results.txt`。

---

## Commit Strategy

- **Wave 1 完成后**: `test(l1-l4): add quality chain coverage tests` — 所有新测试文件
- **Wave 2 修复后**: `fix(tests): resolve test failures from coverage gaps` — 如有修复

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: 594+ passed, 27 failed (pre-existing), 0 errors
```

### Final Checklist

- [ ] 出图质量链路全覆盖（QA Gate 5门 + 评分 + 过滤 + Prompt + SlotPlan）
- [ ] 全量测试 passed ≥ 594
- [ ] 无新增 failure
- [ ] 不触碰 L5 代码
