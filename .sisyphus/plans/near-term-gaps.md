# Near-Term Gap Remediation (PRD ↔ 系统流程说明 一致性补缺)

## TL;DR

> **Quick Summary**: 补齐 PRD 与系统流程说明之间的 4 个关键缺口——更新文档状态表、修复品牌画像回写闭环、打通跨项目知识库复用、补齐 Web UI 缺失页面。
>
> **Deliverables**:
>
> - PRD §3.3 实施状态表更新（L4 能力标记为 ✅）
> - BrandProfile `guidelines` 字段 + feedback_loop 回写修复
> - knowledge_base 生产集成（promote → brief_generator / slot_planner 查询）
> - Web UI: 人工复核页 + QA Dashboard + `aip web` 命令 + 导航栏补全
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 (独立) | Task 2 → Task 3 (知识库依赖品牌回写完整) | Task 4 (独立)

---

## Context

### Original Request

对照 `系统流程说明.md` 和 `PRD.md` 发现 10 个缺口，老板选择补齐近期 4 个，最终目标是基于完整系统撰写订单 SOP 操作手册。

### Interview Summary

**Key Discussions**:

- L4/L5 六个 Task 全部完成（db_migrate, confidence_routing, knowledge_anonymizer, ab_attribution, trend_engine, flywheel），Wave FINAL 通过
- PRD vs 系统流程说明一致性审查发现 10 个缺口，老板选近期 4 个
- 3 个 explore agent 深度调研了 feedback_loop / knowledge_base / web 的现状

**Research Findings**:

- feedback_loop 写入 `brand.guidelines` 但该字段在 BrandProfile 模型中不存在（假连通）
- knowledge_base CRUD 层完整、anonymizer 完整，但生产代码零调用（全链路断裂）
- Web UI 80% 完成，缺人工复核页、QA Dashboard、`aip web` 命令、导航栏入口

### Metis Review

**Identified Gaps** (addressed):

- SQLite `create_all()` 不加列 → 必须用 `db_migrate.py` ALTER TABLE（已纳入 Task 2）
- Task 2 字段映射需明确 → 计划中指定 A/B 结果 → guidelines 文本拼接策略
- Task 3 查询机制 → 采用 tag-match + category 过滤
- Task 4 F-DA-03 / QA Dashboard 内容规格 → 计划中详细定义
- 不得新建数据库表，不得在 Task 2/3 中加 Flask 路由

---

## Work Objectives

### Core Objective

补齐 PRD 与系统流程说明的 4 个关键缺口，使系统功能完整度达到可撰写 SOP 手册的程度。

### Concrete Deliverables

- `docs/PRD.md` §3.3 实施状态表更新
- `pipeline/models/brand_profile.py` 新增 `guidelines` Column
- `pipeline/db_migrate.py` 新增迁移函数
- `pipeline/layers/feedback_loop.py` 回写逻辑修复
- `pipeline/layers/knowledge_base.py` 新增 `promote_to_knowledge()` 桥接函数
- `pipeline/layers/brief_generator.py` 集成 knowledge_base 查询
- `pipeline/layers/slot_planner.py` 集成 knowledge_base 查询
- `pipeline/layers/ab_attribution.py` 触发知识库写入
- `pipeline/web/app.py` 新增 `/review`, `/qa-dashboard` 路由
- `pipeline/web/templates/review.html`, `pipeline/web/templates/qa_dashboard.html`
- `pipeline/web/templates/base.html` 导航栏补全
- `pipeline/__main__.py` 新增 `web` 子命令

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q` → ≥ 456 passed（不回退）
- [ ] 新增测试全部 pass
- [ ] PRD §3.3 L4 能力全部标记 ✅
- [ ] `aip web` 能启动 Flask 服务
- [ ] `/review` 和 `/qa-dashboard` 页面可访问

### Must Have

- BrandProfile.guidelines 字段落库可验证
- knowledge_base 在 brief_generator 和 slot_planner 中被调用
- 人工复核页面展示待复核交付物列表
- 所有现有测试不回退

### Must NOT Have (Guardrails)

- 不得新建数据库表（只加字段）
- 不得在 Task 2/3 中加 Flask 路由
- 不得用 Alembic，只用 `db_migrate.py` + ALTER TABLE
- 不得修改 `.sisyphus/plans/l4-l5-implementation.md`（SACRED）
- 不得跑 `tests/test_e2e_tws.py` 或 `tests/test_e2e_pipeline.py`
- CSS 外部引用 style.css，禁止 `<style>` 内联
- 不得在模板中使用内联样式

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision

- **Infrastructure exists**: YES
- **Automated tests**: TDD (RED → GREEN → REFACTOR)
- **Framework**: pytest
- **Baseline**: 456 passed

### QA Policy

Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend**: Bash (pytest / python REPL) - Import, call functions, assert output
- **Web UI**: Playwright - Navigate, interact, assert DOM, screenshot
- **CLI**: Bash - Run `aip web`, verify process starts

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - independent tasks):
├── Task 1: PRD §3.3 状态表更新 [quick]
├── Task 2: BrandProfile guidelines 字段 + feedback_loop 回写修复 [deep]
└── Task 4a: Web UI - aip web 命令 + 导航栏补全 [quick]

Wave 2 (After Task 2 - 知识库集成依赖品牌回写完整):
├── Task 3: 跨项目知识库复用打通 [deep]
└── Task 4b: Web UI - 人工复核页 + QA Dashboard [unspecified-high]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

| Task  | Depends On | Blocks |
| ----- | ---------- | ------ |
| 1     | -          | -      |
| 2     | -          | 3      |
| 3     | 2          | FINAL  |
| 4a    | -          | 4b     |
| 4b    | 4a         | FINAL  |
| FINAL | 1,2,3,4b   | -      |

### Agent Dispatch Summary

- **Wave 1**: 3 tasks — T1 → `quick`, T2 → `deep`, T4a → `quick`
- **Wave 2**: 2 tasks — T3 → `deep`, T4b → `unspecified-high` + `playwright` skill
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high` + `playwright`, F4 → `deep`

---

## TODOs

- [x] 1. 更新 PRD §3.3 实施状态表

  **What to do**:
  - 打开 `docs/PRD.md`，找到 §3.3 实施状态表
  - 将 L4 已实现能力（db_migrate, confidence_routing, knowledge_anonymizer, ab_attribution, trend_engine, flywheel）从「⏳ 待建」改为「✅ 已实现」
  - 确保描述与实际实现一致

  **Must NOT do**:
  - 不得修改 §3.3 以外的内容
  - 不得改变表格格式

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 4a)
  - **Blocks**: -
  - **Blocked By**: None

  **References**:
  - `docs/PRD.md` — §3.3 实施状态表，找到 L4 相关行
  - `.sisyphus/plans/l4-l5-implementation.md` — 确认已完成的 6 个 Task 名称（只读参考）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: PRD L4 状态全部标记已实现
    Tool: Bash
    Steps:
      1. grep -c "✅" docs/PRD.md → 记录数量 N1
      2. 确认 confidence_routing, knowledge_anonymizer, ab_attribution, trend_engine, flywheel 对应行均为 ✅
      3. grep "⏳" docs/PRD.md → L4 相关条目不应出现 ⏳
    Expected Result: L4 六项能力全部标记 ✅，无 ⏳ 残留
    Evidence: .sisyphus/evidence/task-1-prd-status.txt

  Scenario: 未误改其他内容
    Tool: Bash
    Steps:
      1. git diff docs/PRD.md → 仅 §3.3 相关行有变更
    Expected Result: diff 仅包含状态标记变更
    Evidence: .sisyphus/evidence/task-1-prd-diff.txt
  ```

  **Commit**: YES (C1)
  - Message: `docs(prd): update §3.3 L4 implementation status`
  - Files: `docs/PRD.md`

- [x] 2. 修复品牌画像自动回写闭环

  **What to do**:
  - **Step 1 (RED)**: 编写测试 `tests/test_brand_writeback.py`
    - 测试 BrandProfile 模型有 `guidelines` 属性
    - 测试 `feedback_loop.update_brand_profile_from_results()` 能将数据写入 `guidelines` 字段并持久化
    - 测试 `db_migrate.py` 的迁移函数能为已有表添加 `guidelines` 列
  - **Step 2 (GREEN)**:
    - 在 `pipeline/models/brand_profile.py` 添加 `guidelines = Column(Text, nullable=True)`
    - 在 `pipeline/db_migrate.py` 添加迁移函数 `_migrate_brand_profile_guidelines()`，用 ALTER TABLE 幂等添加列
    - 修复 `pipeline/layers/feedback_loop.py` 的 `update_brand_profile_from_results()`，确保写入 `brand.guidelines` 能落库
  - **Step 3 (REFACTOR)**: 清理代码，确保无冗余

  **Must NOT do**:
  - 不得新建数据库表
  - 不得使用 Alembic
  - 不得添加 Flask 路由
  - 不得修改 BrandProfile 的 10 个现有风格字段

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Parallel Group**: Wave 1 (with Tasks 1, 4a)
  - **Blocks**: Task 3
  - **Blocked By**: None

  **References**:
  - `pipeline/models/brand_profile.py` — BrandProfile 模型，有 10 个风格字段，缺 `guidelines`
  - `pipeline/layers/feedback_loop.py` — `update_brand_profile_from_results()` 函数，当前写入不存在的字段
  - `pipeline/db_migrate.py` — 幂等迁移模式，参考已有的 `_migrate_prompt_asset_*` 函数格式
  - `tests/test_db_migrate.py` — 迁移测试模式参考

  **Acceptance Criteria**:
  - [ ] `tests/test_brand_writeback.py` 全部 pass
  - [ ] 现有 456 测试不回退

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: guidelines 字段存在且可写入
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.models.brand_profile import BrandProfile
         assert hasattr(BrandProfile, 'guidelines'), 'guidelines missing'
         print('FIELD_EXISTS')
         "
    Expected Result: stdout 输出 FIELD_EXISTS
    Evidence: .sisyphus/evidence/task-2-field-exists.txt

  Scenario: feedback_loop 回写持久化验证
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.models import get_session
         from pipeline.models.brand_profile import BrandProfile
         session = get_session()
         bp = session.query(BrandProfile).first()
         if not bp:
             bp = BrandProfile(project_id='test-writeback')
             session.add(bp)
             session.commit()
         bp.guidelines = 'test guideline data'
         session.commit()
         session.refresh(bp)
         assert bp.guidelines == 'test guideline data'
         print('WRITEBACK_OK')
         "
    Expected Result: stdout 输出 WRITEBACK_OK
    Evidence: .sisyphus/evidence/task-2-writeback.txt

  Scenario: 迁移幂等性
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.db_migrate import run_migrations
         run_migrations()
         run_migrations()
         print('MIGRATE_IDEMPOTENT')
         "
    Expected Result: 两次迁移均无报错，输出 MIGRATE_IDEMPOTENT
    Evidence: .sisyphus/evidence/task-2-migrate-idempotent.txt

  Scenario: 全量测试不回退
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
    Expected Result: ≥ 456 passed, 0 failed
    Evidence: .sisyphus/evidence/task-2-regression.txt
  ```

  **Commit**: YES (C2)
  - Message: `fix(feedback): add BrandProfile.guidelines + fix writeback`
  - Files: `pipeline/models/brand_profile.py`, `pipeline/db_migrate.py`, `pipeline/layers/feedback_loop.py`, `tests/test_brand_writeback.py`
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`

- [x] 3. 打通跨项目知识库复用

  **What to do**:
  - **Step 1 (RED)**: 编写测试 `tests/test_knowledge_integration.py`
    - 测试 `promote_to_knowledge()` 能将 winning template 匿名化后写入 knowledge_entries
    - 测试 `brief_generator.generate_brief()` 查询 knowledge_base 并将推荐模板纳入 brief
    - 测试 `slot_planner.generate_slot_plan()` 查询 knowledge_base 推荐模板
    - 测试 `ab_attribution` 标记 `is_recommended=True` 时触发知识库写入
  - **Step 2 (GREEN)**:
    - 在 `pipeline/layers/knowledge_base.py` 添加 `promote_to_knowledge(prompt_asset, session)` 函数：调用 `knowledge_anonymizer.anonymize_knowledge()` → `add_entry()`
    - 在 `pipeline/layers/ab_attribution.py` 的标记 `is_recommended=True` 之后调用 `promote_to_knowledge()`
    - 在 `pipeline/layers/brief_generator.py` 的 `generate_brief()` 中添加 `knowledge_base.search_entries(tags, category)` 查询，将结果附加到 brief context
    - 在 `pipeline/layers/slot_planner.py` 的 `generate_slot_plan()` 中添加 `knowledge_base.get_popular_entries(category)` 查询，推荐模板
  - **Step 3 (REFACTOR)**: 确保 increment_usage 在每次推荐使用时被调用

  **Must NOT do**:
  - 不得新建数据库表
  - 不得添加 Flask 路由
  - 不得修改 knowledge_anonymizer 核心逻辑（已完成且通过测试）
  - 不得修改 KnowledgeEntry 模型结构

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2
  - **Blocks**: FINAL
  - **Blocked By**: Task 2（品牌回写完整后，知识库写入时需要完整的品牌数据）

  **References**:
  - `pipeline/layers/knowledge_base.py` — CRUD 函数：`add_entry()`, `search_entries()`, `get_popular_entries()`, `increment_usage()`
  - `pipeline/layers/knowledge_anonymizer.py` — `anonymize_knowledge(content, project_id)` 函数
  - `pipeline/layers/ab_attribution.py` — 找到 `is_recommended = True` 赋值位置，在其后添加调用
  - `pipeline/layers/brief_generator.py` — `generate_brief()` 函数，找到 context 构建位置
  - `pipeline/layers/slot_planner.py` — `generate_slot_plan()` 函数，找到模板推荐位置
  - `pipeline/models/knowledge_entry.py` — KnowledgeEntry 模型：source_project_id, category, title, content, tags, usage_count
  - `tests/test_knowledge_anonymizer.py` — 匿名化测试参考

  **Acceptance Criteria**:
  - [ ] `tests/test_knowledge_integration.py` 全部 pass
  - [ ] 现有测试不回退

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: promote_to_knowledge 端到端
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.layers.knowledge_base import promote_to_knowledge, search_entries
         from pipeline.models import get_session
         from unittest.mock import MagicMock
         session = get_session()
         asset = MagicMock()
         asset.id = 'test-asset-1'
         asset.content = 'Template for BrandX project PRJ-001'
         asset.project_id = 'PRJ-001'
         asset.category = 'product_photo'
         asset.tags = 'lifestyle,modern'
         promote_to_knowledge(asset, session)
         results = search_entries(session, tags=['lifestyle'], category='product_photo')
         assert len(results) > 0, 'No entries found'
         assert 'BrandX' not in results[0].content, 'Brand name not anonymized'
         print('PROMOTE_OK')
         "
    Expected Result: stdout 输出 PROMOTE_OK（内容已匿名化且可检索）
    Evidence: .sisyphus/evidence/task-3-promote.txt

  Scenario: brief_generator 集成验证
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.layers import brief_generator
         import inspect
         src = inspect.getsource(brief_generator.generate_brief)
         assert 'knowledge_base' in src or 'search_entries' in src, 'knowledge_base not integrated'
         print('BRIEF_INTEGRATED')
         "
    Expected Result: brief_generator 源码中包含 knowledge_base 调用
    Evidence: .sisyphus/evidence/task-3-brief-integration.txt

  Scenario: slot_planner 集成验证
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.layers import slot_planner
         import inspect
         src = inspect.getsource(slot_planner.generate_slot_plan)
         assert 'knowledge_base' in src or 'get_popular_entries' in src, 'knowledge_base not integrated'
         print('SLOT_INTEGRATED')
         "
    Expected Result: slot_planner 源码中包含 knowledge_base 调用
    Evidence: .sisyphus/evidence/task-3-slot-integration.txt

  Scenario: 全量测试不回退
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
    Expected Result: ≥ 456 passed, 0 failed
    Evidence: .sisyphus/evidence/task-3-regression.txt
  ```

  **Commit**: YES (C3)
  - Message: `feat(knowledge): integrate knowledge_base into production pipeline`
  - Files: `pipeline/layers/knowledge_base.py`, `pipeline/layers/ab_attribution.py`, `pipeline/layers/brief_generator.py`, `pipeline/layers/slot_planner.py`, `tests/test_knowledge_integration.py`
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`

- [x] 4a. Web UI — `aip web` 命令 + 导航栏补全

  **What to do**:
  - 在 `pipeline/__main__.py` 添加 `web` 子命令，调用 `pipeline.web.app` 启动 Flask
    - 支持 `--port` 参数（默认 5000）
    - 支持 `--debug` 标志
  - 在 `pipeline/web/templates/base.html` 导航栏添加缺失入口：
    - Knowledge Base (`/knowledge`)
    - Brand Profile (`/brand-profile` 或已有路由)
    - Review (`/review` — Task 4b 创建）
    - QA Dashboard (`/qa-dashboard` — Task 4b 创建）
  - 编写测试 `tests/test_web_cli.py`：验证 `aip web --help` 输出正确

  **Must NOT do**:
  - 不得使用 `<style>` 内联样式
  - 不得修改已有路由逻辑
  - 不得添加新的 Python 依赖

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Task 4b
  - **Blocked By**: None

  **References**:
  - `pipeline/__main__.py` — CLI 入口，查看已有子命令格式（如 `run`, `init` 等）
  - `pipeline/web/app.py` — Flask 应用，找到 `app = Flask(__name__)` 和 `app.run()` 调用
  - `pipeline/web/templates/base.html` — 导航栏，当前仅 4 个链接
  - `pipeline/web/static/style.css` — 已有样式，导航栏新入口需匹配

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. python -m pipeline.__main__ web --help` 显示帮助
  - [ ] 导航栏包含 6+ 入口

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: aip web --help 输出
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -m pipeline.__main__ web --help
    Expected Result: 输出包含 --port 和 --debug 选项说明
    Evidence: .sisyphus/evidence/task-4a-web-help.txt

  Scenario: 导航栏入口完整
    Tool: Bash
    Steps:
      1. grep -c 'href=' pipeline/web/templates/base.html
    Expected Result: ≥ 6 个导航链接
    Evidence: .sisyphus/evidence/task-4a-nav-links.txt
  ```

  **Commit**: YES (grouped with C4)

- [x] 4b. Web UI — 人工复核页 + QA Dashboard

  **What to do**:
  - **人工复核页 `/review`** (F-DA-03, PRD Phase 1 P0):
    - 在 `pipeline/web/app.py` 添加 `/review` 路由
    - 创建 `pipeline/web/templates/review.html`
    - 展示待复核交付物列表（从 DeliveryVersion 查询 status='pending_review'）
    - 每条显示：项目名、版本号、创建时间、缩略图（如有）
    - 提供 Approve / Reject 操作按钮（POST 到 `/review/<id>/approve` 和 `/review/<id>/reject`）
    - Approve 更新 status='approved'，Reject 更新 status='rejected' 并可填写原因
  - **QA Dashboard `/qa-dashboard`**:
    - 在 `pipeline/web/app.py` 添加 `/qa-dashboard` 路由
    - 创建 `pipeline/web/templates/qa_dashboard.html`
    - 展示 QARecord 列表：项目名、检查时间、通过/失败状态、各 gate 得分
    - 按项目分组，最新记录在前
    - 展示通过率统计（总通过 / 总记录）
  - 编写测试 `tests/test_web_review.py`：
    - 测试 `/review` 路由返回 200
    - 测试 `/qa-dashboard` 路由返回 200
    - 测试 approve/reject POST 操作

  **Must NOT do**:
  - 不得使用 `<style>` 内联样式，CSS 写入 `style.css`
  - 不得修改已有路由
  - 不得修改 DeliveryVersion / QARecord 模型

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`playwright`]

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Task 3)
  - **Parallel Group**: Wave 2
  - **Blocks**: FINAL
  - **Blocked By**: Task 4a（导航栏需先补全）

  **References**:
  - `pipeline/web/app.py` — 已有路由模式，参考 `/projects` 或 `/prompts` 路由格式
  - `pipeline/web/templates/projects.html` — 列表页模板参考
  - `pipeline/web/templates/base.html` — 模板继承格式
  - `pipeline/web/static/style.css` — 样式文件，新页面样式加在此处
  - `pipeline/models/delivery_version.py` — DeliveryVersion 模型，有 status 字段
  - `pipeline/models/qa_record.py` 或类似 — QARecord 模型，有 gate 得分字段
  - `tests/test_prompt_editor.py` — Web 路由测试模式参考（Flask test_client 用法）

  **Acceptance Criteria**:
  - [ ] `tests/test_web_review.py` 全部 pass
  - [ ] 现有测试不回退

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: /review 页面可访问
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.web.app import app
         client = app.test_client()
         resp = client.get('/review')
         assert resp.status_code == 200, f'Got {resp.status_code}'
         assert b'review' in resp.data.lower() or b'复核' in resp.data.lower()
         print('REVIEW_OK')
         "
    Expected Result: /review 返回 200 且包含相关内容
    Evidence: .sisyphus/evidence/task-4b-review-page.txt

  Scenario: /qa-dashboard 页面可访问
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.web.app import app
         client = app.test_client()
         resp = client.get('/qa-dashboard')
         assert resp.status_code == 200, f'Got {resp.status_code}'
         assert b'qa' in resp.data.lower() or b'dashboard' in resp.data.lower()
         print('QA_DASH_OK')
         "
    Expected Result: /qa-dashboard 返回 200
    Evidence: .sisyphus/evidence/task-4b-qa-dashboard.txt

  Scenario: approve 操作
    Tool: Bash
    Steps:
      1. PYTHONPATH=. python -c "
         from pipeline.web.app import app
         from pipeline.models import get_session
         from pipeline.models.delivery_version import DeliveryVersion
         # Setup test data
         session = get_session()
         dv = DeliveryVersion(project_id='test-review', version=1, status='pending_review')
         session.add(dv)
         session.commit()
         dv_id = dv.id
         # Test approve
         client = app.test_client()
         resp = client.post(f'/review/{dv_id}/approve')
         assert resp.status_code in (200, 302), f'Got {resp.status_code}'
         session.refresh(dv)
         assert dv.status == 'approved', f'Got {dv.status}'
         print('APPROVE_OK')
         "
    Expected Result: status 更新为 approved
    Evidence: .sisyphus/evidence/task-4b-approve.txt

  Scenario: Playwright UI 验证（人工复核页）
    Tool: Playwright
    Preconditions: Flask 服务运行在 localhost:5000
    Steps:
      1. 启动 Flask: PYTHONPATH=. python -m pipeline.__main__ web --port 5000 &
      2. playwright_browser_navigate url=http://localhost:5000/review
      3. playwright_browser_snapshot → 确认页面包含交付物列表结构
      4. playwright_browser_take_screenshot filename=task-4b-review-ui.png
    Expected Result: 页面渲染正常，包含 Approve/Reject 按钮
    Evidence: .sisyphus/evidence/task-4b-review-ui.png

  Scenario: 全量测试不回退
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
    Expected Result: ≥ 456 passed, 0 failed
    Evidence: .sisyphus/evidence/task-4b-regression.txt
  ```

  **Commit**: YES (C4)
  - Message: `feat(web): add review page, QA dashboard, aip web command`
  - Files: `pipeline/web/app.py`, `pipeline/web/templates/review.html`, `pipeline/web/templates/qa_dashboard.html`, `pipeline/web/templates/base.html`, `pipeline/web/static/style.css`, `pipeline/__main__.py`, `tests/test_web_review.py`, `tests/test_web_cli.py`
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
      Run `PYTHONPATH=. .venv/bin/pytest tests/ -q` (must be ≥ 456 passed). Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill)
      Start Flask with `aip web`. Navigate to `/review`, `/qa-dashboard`, verify pages render. Test knowledge_base integration by running `promote_to_knowledge()` in REPL. Verify BrandProfile.guidelines persists after feedback_loop update. Save evidence to `.sisyphus/evidence/final-qa/`.
      Output: `Scenarios [N/N pass] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | VERDICT`

---

## Commit Strategy

| Commit | Tasks      | Message                                                              | Pre-commit                                |
| ------ | ---------- | -------------------------------------------------------------------- | ----------------------------------------- |
| C1     | Task 1     | `docs(prd): update §3.3 L4 implementation status`                    | -                                         |
| C2     | Task 2     | `fix(feedback): add BrandProfile.guidelines + fix writeback`         | `PYTHONPATH=. .venv/bin/pytest tests/ -q` |
| C3     | Task 3     | `feat(knowledge): integrate knowledge_base into production pipeline` | `PYTHONPATH=. .venv/bin/pytest tests/ -q` |
| C4     | Task 4a+4b | `feat(web): add review page, QA dashboard, aip web command`          | `PYTHONPATH=. .venv/bin/pytest tests/ -q` |

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q                    # Expected: ≥ 456 passed
PYTHONPATH=. python -m pipeline.__main__ web --help        # Expected: shows help for web command
grep "✅" docs/PRD.md | wc -l                              # Expected: increased count
PYTHONPATH=. python -c "from pipeline.models.brand_profile import BrandProfile; print(hasattr(BrandProfile, 'guidelines'))"  # Expected: True
PYTHONPATH=. python -c "from pipeline.layers.knowledge_base import promote_to_knowledge; print('OK')"  # Expected: OK
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass (≥ 456)
- [ ] PRD §3.3 updated
- [ ] `aip web` works
- [ ] `/review` and `/qa-dashboard` accessible
