# 文档-代码一致性修复计划

## TL;DR

> **Quick Summary**: 项目7份文档（PRD, SYSTEM_SPEC, data-flow, architecture, interfaces, TEST_CASES, L5_REQUIREMENTS）与实际代码存在大量不一致。本计划以"文档对齐代码现状"为主，同时标记需要老板决策的功能缺口。
>
> **Deliverables**:
>
> - 7份文档全部更新至与代码一致
> - `performance_score`/`is_recommended` 决策落地（改文档或补代码）
> - 测试基线保持 456 passed
>
> **Estimated Effort**: Medium（主要是文档重写，少量代码变更）
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: 决策点确认 → architecture.md 重写 → 其余文档并行更新

---

## Context

### Original Request

老板要求全面审查项目文档与代码的差距，列出完整不一致清单，制定修复计划，实现完全一致性。

### Interview Summary

**Key Discussions**:

- 已完整读取7份文档（共3953行）和6个核心代码模块
- grep验证 `performance_score` 和 `is_recommended` 在代码中零匹配
- 测试运行确认 456 passed
- 发现4类不一致共 20+ 项

**Research Findings**:

- QA Gate 5道门、自动重出、品牌画像更新等 L4 能力已实现，但文档标注"⏳ 待建"
- `data-flow.md` 的 `ab_tests` 表结构与实际 `ABTest` 模型字段完全不同
- `architecture.md` 仍标注 L2 MVP，严重过时
- `interfaces.md` 函数签名大量与代码不符
- Web路由20+但 interfaces.md 仅列7个

### 决策点（需老板确认）

**DECISION-1: `performance_score` / `is_recommended` / 0.75阈值逻辑**

- **选项A（改文档）**: 从 `data-flow.md` 和 `interfaces.md` 中移除这些字段描述，标注为"未来 L5 规划"
- **选项B（补代码）**: 在 `PromptAsset` 模型中新增 `performance_score` 和 `is_recommended` 字段，实现 `0.6×CTR + 0.4×CVR` 公式和 ≥0.75 阈值逻辑
- **推荐**: 选项A（改文档）—— 这些字段属于 L5 高级功能，当前无数据源支撑计算，强行加代码会产生空字段

> 本计划按**选项A（改文档）**编写。若老板选B，需额外添加代码实现任务。

---

## Work Objectives

### Core Objective

使7份项目文档与代码实际状态完全对齐，消除所有已发现的不一致。

### Concrete Deliverables

- `architecture.md` — 从 L2 MVP 重写至当前 L4 状态
- `data-flow.md` — 修正 ab_tests 表结构、移除不存在的字段
- `interfaces.md` — 对齐所有函数签名、补充缺失的 Web 路由
- `SYSTEM_SPEC.md` — 更新 L4 实施状态表
- `PRD.md` — 更新 L4 能力状态标注
- `TEST_CASES.md` — 更新验收矩阵状态
- `L5_REQUIREMENTS.md` — 无重大不一致，仅微调

### Definition of Done

- [ ] 7份文档中所有函数签名、表结构、字段名与代码完全一致
- [ ] 所有"⏳ 待建"标注已根据实际代码状态更新
- [ ] `grep -rn "performance_score\|is_recommended" docs/` 返回的内容均标注为"L5 规划"或已移除
- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → 456 passed（不退步）

### Must Have

- 每份文档修改后必须保持内部自洽（章节间不矛盾）
- 修改必须基于代码实际状态，不能凭文档推测
- 所有函数签名必须从代码中提取，不能手写

### Must NOT Have (Guardrails)

- ❌ 不得修改任何 Python 代码文件（除非选项B）
- ❌ 不得删除文档中的路线图/未来规划内容，仅更新实施状态
- ❌ 不得修改测试文件
- ❌ 不得在文档中编造不存在的功能
- ❌ 不得使用 Alembic 相关描述（项目用 `create_all()`）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES (pytest, 456 passed)
- **Automated tests**: None (this is documentation work, no new code)
- **Framework**: pytest (existing, for regression check only)

### QA Policy

每个任务完成后，agent 必须：

1. `grep` 验证修改后的文档不包含已知错误内容
2. 对比代码文件确认签名/字段名一致
3. 运行 `PYTHONPATH=. .venv/bin/pytest tests/ -q` 确认不影响测试（仅代码变更任务）

Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - 独立文档，无依赖):
├── Task 1: architecture.md 重写 [unspecified-high]
├── Task 2: data-flow.md 修正 [unspecified-high]
├── Task 3: interfaces.md 对齐函数签名 [unspecified-high]
├── Task 4: interfaces.md 补充 Web 路由 [unspecified-high]
└── Task 5: SYSTEM_SPEC.md 更新 L4 状态表 [quick]

Wave 2 (After Wave 1 - 依赖 SYSTEM_SPEC 更新):
├── Task 6: PRD.md 更新能力状态 [quick]
├── Task 7: TEST_CASES.md 更新验收矩阵 [quick]
└── Task 8: L5_REQUIREMENTS.md 微调 [quick]

Wave 3 (After ALL - 交叉验证):
└── Task 9: 全量交叉验证 [deep]

Wave FINAL (After ALL tasks):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

- **1-5**: None → 6-8, Wave 1
- **6**: 5 → 9, Wave 2
- **7**: 5 → 9, Wave 2
- **8**: None → 9, Wave 2
- **9**: 1-8 → FINAL, Wave 3

### Agent Dispatch Summary

- **Wave 1**: 5 tasks — T1-T4 → `unspecified-high`, T5 → `quick`
- **Wave 2**: 3 tasks — T6-T8 → `quick`
- **Wave 3**: 1 task — T9 → `deep`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. architecture.md 重写（L2→L4）

  **What to do**:
  - 读取 `docs/architecture.md`（264行）和以下代码文件获取真实状态：
    - `pipeline/__main__.py` — CLI 入口与命令列表
    - `pipeline/web/app.py` — Web 路由架构
    - `pipeline/orchestrator.py` — 流程编排
    - `pipeline/layers/qa_gate.py` — QA 5道门
    - `pipeline/layers/feedback_loop.py` — 数据回流
    - `pipeline/adapters/gpt_image_adapter.py` — GPT Image 适配器
    - `pipeline/adapters/gemini_image_adapter.py` — Gemini 适配器
    - `pipeline/adapters/mock_adapter.py` — Mock 适配器
  - 重写以下章节使其反映 L4 当前状态：
    - **技术栈**: 移除 Flux/MJ/ComfyUI 引用，替换为 GPT Image / Gemini / Mock
    - **目录结构**: 更新为实际目录树（用 `ls -R` 获取）
    - **核心模块**: 更新模块描述与职责
    - **数据流**: 简化引用 data-flow.md
    - **部署**: 移除 Alembic 引用，改为 `create_all()`
  - 保留路线图/未来规划章节，仅更新实施状态标注

  **Must NOT do**:
  - 不修改任何 Python 文件
  - 不删除未来规划内容
  - 不引用 Alembic
  - 不编造不存在的模块

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `docs/architecture.md` — 当前文档（264行），需重写
  - `pipeline/__main__.py` — CLI 命令列表（真实）
  - `pipeline/web/app.py` — Web 路由（真实）
  - `pipeline/orchestrator.py` — 编排逻辑（真实）
  - `pipeline/adapters/` — 3个适配器（真实名称）

  **QA Scenarios**:

  ```
  Scenario: 验证旧适配器名已移除
    Tool: Bash (grep)
    Steps:
      1. grep -in "Flux\|Midjourney\|ComfyUI" docs/architecture.md
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-1-no-old-adapters.txt

  Scenario: 验证无 Alembic 引用
    Tool: Bash (grep)
    Steps:
      1. grep -in "alembic" docs/architecture.md
    Expected Result: 0 matches
    Evidence: .sisyphus/evidence/task-1-no-alembic.txt

  Scenario: 验证新适配器名存在
    Tool: Bash (grep)
    Steps:
      1. grep -in "gpt_image\|gemini\|mock" docs/architecture.md
    Expected Result: ≥3 matches
    Evidence: .sisyphus/evidence/task-1-new-adapters.txt
  ```

  **Commit**: YES
  - Message: `docs: rewrite architecture.md to L4 current state`
  - Files: `docs/architecture.md`

- [ ] 2. data-flow.md 修正（ab_tests 表结构 + phantom 字段）

  **What to do**:
  - 读取 `docs/data-flow.md`（550行）和 `pipeline/models/` 下的 ORM 模型
  - 修正 `ab_tests` 表结构：替换错误的 `ctr, cvr, rank_change` 为实际字段 `variant_a_id, variant_b_id, winner, metric, score_a, score_b`
  - 将 `performance_score`、`is_recommended`、`0.6×CTR + 0.4×CVR` 公式、`≥0.75 标记推荐` 移至 L5 规划章节或标注为「L5 待实现」
  - 核对所有其他表结构（`projects`, `prompt_assets`, `generation_history` 等）与 ORM 模型一致

  **Must NOT do**:
  - 不删除 L5 规划内容，仅标注状态
  - 不修改 Python 文件

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `docs/data-flow.md:~310` — performance_score 公式位置
  - `docs/data-flow.md:~203` — is_recommended 位置
  - `pipeline/models/` — 所有 ORM 模型（真实表结构）
  - `pipeline/layers/feedback_loop.py` — ABTest 模型使用

  **QA Scenarios**:

  ```
  Scenario: 验证 ab_tests 表结构已更新
    Tool: Bash (grep)
    Steps:
      1. grep -A8 "ab_tests" docs/data-flow.md
    Expected Result: 包含 variant_a_id, variant_b_id, winner, metric, score_a, score_b
    Evidence: .sisyphus/evidence/task-2-ab-tests-schema.txt

  Scenario: 验证 phantom 字段已标注为 L5
    Tool: Bash (grep)
    Steps:
      1. grep -n "performance_score\|is_recommended" docs/data-flow.md
    Expected Result: 若存在，上下文包含"L5"或"待实现"；或已移除
    Evidence: .sisyphus/evidence/task-2-phantom-fields.txt
  ```

  **Commit**: YES
  - Message: `docs: fix data-flow.md ab_tests schema and remove phantom fields`
  - Files: `docs/data-flow.md`

- [ ] 3. interfaces.md 对齐函数签名

  **What to do**:
  - 读取 `docs/interfaces.md`（968行）
  - 对照以下代码文件，更新所有函数签名：
    - `pipeline/orchestrator.py` — `create_project()`, `run_pipeline()` 等
    - `pipeline/layers/input_layer.py` — `validate_input()`, 14个必填字段
    - `pipeline/layers/qa_gate.py` — 5道门函数签名
    - `pipeline/layers/feedback_loop.py` — `update_brand_profile_from_results()` 等
    - `pipeline/layers/amazon_data.py` — Keepa API 函数
    - `pipeline/layers/consistency_system.py` — 一致性检查函数
    - `pipeline/layers/knowledge_base.py` — 知识库函数
  - 每个函数签名必须从代码 `def` 行直接复制，不得手写
  - 更新参数类型、返回值、默认值

  **Must NOT do**:
  - 不修改 Python 文件
  - 不编造函数签名

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `docs/interfaces.md` — 当前文档（968行）
  - `pipeline/orchestrator.py` — 核心函数签名
  - `pipeline/layers/input_layer.py` — 输入验证函数
  - `pipeline/layers/qa_gate.py` — QA 门函数签名
  - `pipeline/layers/feedback_loop.py` — 反馈循环函数

  **QA Scenarios**:

  ```
  Scenario: 验证 create_project 签名一致
    Tool: Bash (grep)
    Steps:
      1. grep "create_project" docs/interfaces.md
      2. grep "def create_project" pipeline/orchestrator.py
    Expected Result: 参数列表一致（session, name, asin 等）
    Evidence: .sisyphus/evidence/task-3-create-project-sig.txt

  Scenario: 验证无旧签名残留
    Tool: Bash (grep)
    Steps:
      1. grep "create_project(brief:" docs/interfaces.md
    Expected Result: 0 matches（旧签名已移除）
    Evidence: .sisyphus/evidence/task-3-no-old-sigs.txt
  ```

  **Commit**: YES (groups with Task 4)
  - Message: `docs: align interfaces.md function signatures with code`
  - Files: `docs/interfaces.md`

- [ ] 4. interfaces.md 补充 Web 路由（7→20+）

  **What to do**:
  - 读取 `pipeline/web/app.py`（754行），提取所有 `@app.route` / `@app.get` / `@app.post` 装饰器
  - 在 `docs/interfaces.md` 的 Web API 章节中补充缺失的路由
  - 每个路由包含：方法、路径、参数、返回值、简要描述
  - 保持与已有7个路由的格式一致

  **Must NOT do**:
  - 不修改 Python 文件
  - 不改变已有7个路由的描述（仅补充缺失的）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `pipeline/web/app.py` — 所有路由定义（754行）
  - `docs/interfaces.md` — Web API 章节（当前仅7个路由）

  **QA Scenarios**:

  ```
  Scenario: 验证路由数量 ≥20
    Tool: Bash (grep)
    Steps:
      1. grep -c "^###\|^####\|GET \|POST \|PUT \|DELETE " docs/interfaces.md | 统计 Web API 章节路由数
    Expected Result: ≥20 个路由条目
    Evidence: .sisyphus/evidence/task-4-route-count.txt

  Scenario: 验证代码中的路由都有文档
    Tool: Bash (grep)
    Steps:
      1. grep -oP '@app\.(get|post|put|delete)\("([^"]+)"' pipeline/web/app.py | sort
      2. 对比 docs/interfaces.md 中列出的路由
    Expected Result: 代码中每个路由在文档中都有对应条目
    Evidence: .sisyphus/evidence/task-4-route-coverage.txt
  ```

  **Commit**: YES (groups with Task 3)
  - Files: `docs/interfaces.md`

- [ ] 5. SYSTEM_SPEC.md 更新 L4 实施状态表

  **What to do**:
  - 读取 `docs/SYSTEM_SPEC.md`（1073行）
  - 找到所有标注"⏳ 待建"的 L4 能力
  - 对照代码确认已实现的能力，将状态从"⏳ 待建"更新为"✅ 已实现"：
    - QA Gate 5道门 → `qa_gate.py`
    - 自动重出最多3次 → `orchestrator.py:488`
    - 品牌画像自动更新 → `feedback_loop.py`
  - 保持未实现功能的"⏳ 待建"不变

  **Must NOT do**:
  - 不将未实现功能标为已实现
  - 不修改 Python 文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6, 7, 9
  - **Blocked By**: None

  **References**:
  - `docs/SYSTEM_SPEC.md` — 实施状态表
  - `pipeline/layers/qa_gate.py` — QA 5道门实现
  - `pipeline/orchestrator.py:488` — 自动重出逻辑
  - `pipeline/layers/feedback_loop.py` — 品牌画像更新

  **QA Scenarios**:

  ```
  Scenario: 验证 QA Gate 状态已更新
    Tool: Bash (grep)
    Steps:
      1. grep -A2 "QA.*Gate\|质量门" docs/SYSTEM_SPEC.md
    Expected Result: 包含"✅"而非"⏳"
    Evidence: .sisyphus/evidence/task-5-qa-gate-status.txt

  Scenario: 验证仍有⏳标注（确认未过度更新）
    Tool: Bash (grep)
    Steps:
      1. grep -c "⏳" docs/SYSTEM_SPEC.md
    Expected Result: >0（仍有未实现的 L5 功能）
    Evidence: .sisyphus/evidence/task-5-remaining-pending.txt
  ```

  **Commit**: YES
  - Message: `docs: update SYSTEM_SPEC L4 implementation status`
  - Files: `docs/SYSTEM_SPEC.md`

- [ ] 6. PRD.md 更新 L4 能力状态

  **What to do**:
  - 读取 `docs/PRD.md`（546行）
  - 与已更新的 SYSTEM_SPEC.md 对齐（Task 5 完成后）
  - 将已实现的 L4 能力从"⏳ 待建 L4"更新为"✅ 已实现"
  - 保持格式与其他状态标注一致

  **Must NOT do**:
  - 不修改 Python 文件
  - 不改变 PRD 的需求描述内容

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 7, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Task 5

  **References**:
  - `docs/PRD.md` — 当前文档
  - `docs/SYSTEM_SPEC.md` — 已更新的状态表（对齐源）

  **QA Scenarios**:

  ```
  Scenario: 验证 L4 能力状态已更新
    Tool: Bash (grep)
    Steps:
      1. grep -n "⏳.*L4" docs/PRD.md
    Expected Result: 0 matches（所有已实现的 L4 能力已标为✅）
    Evidence: .sisyphus/evidence/task-6-no-pending-l4.txt
  ```

  **Commit**: YES (groups with Tasks 7, 8)
  - Message: `docs: update PRD, TEST_CASES, L5_REQUIREMENTS status markers`
  - Files: `docs/PRD.md`

- [ ] 7. TEST_CASES.md 更新验收矩阵

  **What to do**:
  - 读取 `docs/TEST_CASES.md`（216行）
  - 更新验收矩阵中已实现功能的状态
  - 确认测试用例描述与代码实际行为一致

  **Must NOT do**:
  - 不修改测试文件
  - 不添加未验证的测试用例

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Task 5

  **References**:
  - `docs/TEST_CASES.md` — 当前文档
  - `docs/SYSTEM_SPEC.md` — 已更新的状态表

  **QA Scenarios**:

  ```
  Scenario: 验证验收矩阵与 SYSTEM_SPEC 一致
    Tool: Bash (grep)
    Steps:
      1. 比较 TEST_CASES.md 和 SYSTEM_SPEC.md 中相同能力的状态标注
    Expected Result: 状态一致
    Evidence: .sisyphus/evidence/task-7-matrix-consistent.txt
  ```

  **Commit**: YES (groups with Tasks 6, 8)
  - Files: `docs/TEST_CASES.md`

- [ ] 8. L5_REQUIREMENTS.md 微调

  **What to do**:
  - 读取 `docs/L5_REQUIREMENTS.md`（336行）
  - 确认 `performance_score`/`is_recommended` 相关内容在此文档中有正确的 L5 规划描述
  - 如果 Task 2 将这些字段从 data-flow.md 移出，确保 L5 文档中有承接
  - 微调任何与代码不一致的细节

  **Must NOT do**:
  - 不修改 Python 文件
  - 不改变 L5 需求的范围定义

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 6, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `docs/L5_REQUIREMENTS.md` — 当前文档
  - `docs/data-flow.md` — Task 2 修改后的 phantom 字段处理

  **QA Scenarios**:

  ```
  Scenario: 验证 L5 文档包含 performance_score 规划
    Tool: Bash (grep)
    Steps:
      1. grep -n "performance_score" docs/L5_REQUIREMENTS.md
    Expected Result: ≥1 match（作为 L5 规划内容存在）
    Evidence: .sisyphus/evidence/task-8-l5-perf-score.txt
  ```

  **Commit**: YES (groups with Tasks 6, 7)
  - Files: `docs/L5_REQUIREMENTS.md`

- [ ] 9. 全量交叉验证

  **What to do**:
  - 对7份已修改文档执行交叉验证：
    - 每份文档抽取5个关键声明（函数签名、表结构、字段名、状态标注、模块描述）
    - 共35个 spot check，每个用 grep 或代码比对验证
  - 运行 `PYTHONPATH=. .venv/bin/pytest tests/ -q` 确认 456 passed
  - 运行所有 Success Criteria 中的验证命令
  - 生成验证报告

  **Must NOT do**:
  - 不修改任何文件
  - 不跳过任何 spot check

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential after Wave 2)
  - **Blocks**: FINAL wave
  - **Blocked By**: Tasks 1-8

  **References**:
  - 所有7份 `docs/*.md` 文档
  - 所有相关 `pipeline/` 代码文件

  **QA Scenarios**:

  ```
  Scenario: 35个 spot check 全部通过
    Tool: Bash (grep + diff)
    Steps:
      1. 每份文档抽取5个声明
      2. 逐个与代码比对
    Expected Result: 35/35 pass
    Evidence: .sisyphus/evidence/task-9-spot-checks.txt

  Scenario: 测试回归
    Tool: Bash
    Steps:
      1. cd /Users/axureboutique/Projects/auto-image-pipeline && PYTHONPATH=. .venv/bin/pytest tests/ -q
    Expected Result: 456 passed
    Evidence: .sisyphus/evidence/task-9-test-regression.txt
  ```

  **Commit**: NO（验证任务，不产生文件变更） (MANDATORY)

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search for forbidden patterns. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `PYTHONPATH=. .venv/bin/pytest tests/ -q` to confirm 456 passed. Verify no Python files were modified (git diff). Check all docs are valid markdown (no broken links/headers).
      Output: `Tests [456/456] | Code Changes [NONE] | Markdown [N valid] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
      For each of the 7 docs: pick 3 function signatures/field names/table structures, grep the codebase to confirm they match. Total: 21 spot checks.
      Output: `Spot Checks [21/21 pass] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      Verify only docs/ files were changed. No code changes. No test changes. No new files outside docs/. No content fabrication (every claim traceable to code).
      Output: `Files Changed [docs/ only] | Fabrication [CLEAN] | VERDICT`

---

## Commit Strategy

- **Wave 1 commit**: `docs: rewrite architecture.md to L4 current state` — architecture.md
- **Wave 1 commit**: `docs: fix data-flow.md ab_tests schema and remove phantom fields` — data-flow.md
- **Wave 1 commit**: `docs: align interfaces.md function signatures with code` — interfaces.md
- **Wave 1 commit**: `docs: update SYSTEM_SPEC L4 implementation status` — SYSTEM_SPEC.md
- **Wave 2 commit**: `docs: update PRD, TEST_CASES, L5_REQUIREMENTS status markers` — PRD.md, TEST_CASES.md, L5_REQUIREMENTS.md
- **Final commit**: `docs: cross-verified all 7 docs against codebase` — (no file changes, verification only)

---

## Success Criteria

### Verification Commands

```bash
# 确认测试不退步
PYTHONPATH=. .venv/bin/pytest tests/ -q  # Expected: 456 passed

# 确认 phantom 字段已处理
grep -rn "performance_score" docs/  # Expected: 仅出现在 L5 规划上下文中，或不出现
grep -rn "is_recommended" docs/     # Expected: 同上

# 确认无 Alembic 引用
grep -rn "alembic\|Alembic" docs/   # Expected: 0 matches

# 确认 ab_tests 表结构已更新
grep -A5 "ab_tests" docs/data-flow.md  # Expected: variant_a_id, variant_b_id, winner, metric, score_a, score_b
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] 456 tests pass
- [ ] 7 docs internally consistent
- [ ] All function signatures match code
