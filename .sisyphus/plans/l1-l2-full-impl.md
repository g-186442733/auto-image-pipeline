# L1+L2 全量功能实施计划

## TL;DR

> **Quick Summary**: 完成 auto-image-pipeline 项目 PRD 中 L1+L2 阶段所有缺失/部分实现功能，共约31项。P0先修复数据模型冲突和数据断链，然后并行推进核心生成引擎、视觉分析、QA门禁等模块。
>
> **Deliverables**:
>
> - 统一的 BrandProfile 数据模型（消除双模型冲突）
> - customer_brief 数据打通到 brief 生成流程
> - 三引擎 Fan-out 并行生成（GPT-image-1 / Gemini Imagen / Mock）
> - 5层视觉标签完整接入 + tag_assignment 持久化
> - QA Gate 5 真实逻辑（替换硬编码 PASS）
> - 品类假设管理 CRUD
> - 事件驱动 ASIN 触发
> - 14天自动追踪
> - 交付包 ZIP + delivered 状态
> - 1页 PDF 推荐报告（信号灯）
> - 内容获客输出
> - 反馈回路 LLM 兜底 + 持久化
> - Top50 ASIN + listing 丰富化
> - 人工标注复核 UI
> - 测试覆盖（tests-after 策略，基线 489 passed 不回归）
>
> **Estimated Effort**: XL（~30 tasks across 5 waves）
> **Parallel Execution**: YES - 5 waves, max 8 concurrent
> **Critical Path**: 0a → 1a → 2a → 2b/2c → 3c → 3d → 4a → FINAL

---

## Context

### Original Request

老板要求全面核查并实现 PRD 中 L1（阶段一）和 L2（阶段二）的所有功能。经过 9 个 explore agent 会话的全量审计，确认 6 项完全未实现、14 项部分实现、11 项已完成。

### Interview Summary

**Key Discussions**:

- 实施范围：L1+L2 全部做，无排除
- 测试策略：tests-after（先实现后补测试），基线 489 passed 不回归
- Fan-out 引擎选型：A=GPT-image-1, B=Gemini Imagen, C=Mock
- DB 迁移策略：不用 Alembic，用 `create_all()` + 手写 ALTER TABLE（幂等）
- CSS 规范：外部引用 style.css，禁止内联 `<style>`

**Research Findings**:

- brand.py(brand_profiles, 6字段) vs brand_profile.py(brand_profile_cards, 11字段) 命名空间冲突
- customer_brief 表有完整10步数据但 brief_generator.py 从不读取
- vision_analyzer.py 只用 INTENT+ROLE 2层，COLOR/LAYOUT/STYLE 定义了但未接入
- tag_assignment 模型存在但从未写入
- qa_gate.py Gate 5 硬编码返回 PASS
- delivery.py 路径 output/ vs data/exports/ 不匹配，无 ZIP，无 delivered 状态

### Metis Review

**Identified Gaps** (addressed):

- Fan-out 部分失败策略：采用「部分成功」模式，A失败不影响B/C
- customer_brief NULL 字段处理：brief_generator 跳过空字段
- QA Gate 5 标准：复合评分 ≥0.6 PASS（已确认）
- 品牌模型合并需先检查现有数据量 → 加入 Wave 0 预检
- 反馈回路循环检测：max-revision=3 硬上限
- 内容获客输出格式模糊 → 默认 JSON 格式（copy + social_posts + seo_keywords）

---

## Work Objectives

### Core Objective

将 auto-image-pipeline 的 L1+L2 全部功能补齐到 PRD 定义的完整状态，消除数据冲突和断链。

### Concrete Deliverables

- 统一 `BrandProfile` 模型（合并 brand.py + brand_profile.py）
- `brief_generator.py` 读取 customer_brief 表数据
- `fan_out_engine.py` 三引擎并行调度
- `vision_analyzer.py` 5层标签 + `tag_assignment` 写入
- `qa_gate.py` Gate 5 真实评估逻辑
- `hypothesis.py` 模型 + CRUD API
- `pipeline_trigger.py` 事件驱动触发
- `tracking_scheduler.py` 14天追踪
- `delivery.py` ZIP打包 + delivered 状态
- `report_generator.py` PDF信号灯报告
- `content_marketing.py` 获客内容输出
- `revision_lookup.py` LLM兜底 + 持久化
- `amazon_data.py` Top50 + listing 丰富化
- 标注复核 UI template
- 对应测试文件

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py` → ≥489 passed, 0 failed
- [ ] 所有新功能有对应测试
- [ ] 无 `from pipeline.models.brand import BrandProfile` 残留引用
- [ ] `aip generate --engines mock` 正常执行

### Must Have

- 三引擎 Fan-out 并行（GPT-image-1 + Gemini + Mock）
- 统一品牌画像模型
- customer_brief 数据注入 brief
- 5层视觉标签完整
- QA Gate 5 真实逻辑
- 交付包 ZIP + delivered 状态
- 测试基线不回归

### Must NOT Have (Guardrails)

- **不引入消息队列**（无 Celery/Redis/RabbitMQ）——事件触发用简单 webhook
- **不新增 pip 依赖**（除 weasyprint/reportlab 用于 PDF）——无需理由不加包
- **不做 PDF 复杂排版**——基础表格+图片，无自定义样式
- **不扩展标签层级**——严格 5 层（INTENT/ROLE/COLOR/LAYOUT/STYLE），不加新层
- **不做 LLM 微调**——反馈回路 LLM 兜底用单次 API 调用 + 固定 prompt
- **品牌合并不加新字段**——取 11 字段超集，不额外增加
- **不用 Alembic**——create_all() + 手写 ALTER TABLE
- **CSS 不内联**——外部引用 style.css
- **测试不调真实 LLM**——全部 mock/fixture

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision

- **Infrastructure exists**: YES
- **Automated tests**: Tests-after
- **Framework**: pytest (already configured)
- **Test command**: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`
- **Baseline**: 489 passed

### QA Policy

Every task MUST run the test command after completion and assert ≥489 passed.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (Prerequisite — baseline + data check):
├── Task 0a: Validate test baseline (489 passed) [quick]
├── Task 0b: Check brand table data counts [quick]
└── Task 0c: QA Gate 5 criteria confirmed (≥0.6 PASS)

Wave 1 (Foundation — P0 fixes, parallel):
├── Task 1a: Merge brand models (depends: 0a, 0b) [deep]
├── Task 1b: Wire customer_brief → brief_generator (depends: 0a) [unspecified-high]
├── Task 1c: Top50 ASIN + listing enrichment (depends: 0a) [unspecified-high]
└── Task 1d: Gemini Vision wire into main flow (depends: 0a) [quick]

Wave 2 (Core engines + analysis, max parallel):
├── Task 2a: Fan-out engine interface + Mock (depends: 1a) [deep]
├── Task 2b: GPT-image-1 engine adapter (depends: 2a) [unspecified-high]
├── Task 2c: Gemini Imagen engine adapter (depends: 2a) [unspecified-high]
├── Task 2d: Vision 5-layer tags + tag_assignment (depends: 0a) [deep]
├── Task 2e: QA Gate 5 real logic (depends: 0c, 2d) [unspecified-high]
├── Task 2f: Hypothesis management CRUD (depends: 1a) [deep]
├── Task 2g: Human annotation review UI (depends: 2d) [visual-engineering]
└── Task 2h: A+ Storyboard product context (depends: 1b) [unspecified-high]

Wave 3 (L2 features, parallel):
├── Task 3a: Event-driven pipeline trigger (depends: 2a) [unspecified-high]
├── Task 3b: 14-day tracking scheduler (depends: 2f) [unspecified-high]
├── Task 3c: Delivery ZIP + path fix + delivered status (depends: 0a) [unspecified-high]
├── Task 3d: PDF report generation (depends: 3b, 3c) [unspecified-high]
├── Task 3e: Content marketing output (depends: 1b) [unspecified-high]
├── Task 3f: Feedback LLM fallback + persistence (depends: 2e) [deep]
├── Task 3g: Decision log + query (depends: 0a) [quick]
└── Task 3h: Price band + promo rhythm enhancements (depends: 0a) [unspecified-high]

Wave 4 (Tests + integration):
├── Task 4a: Integration test suite (depends: ALL Wave 3) [deep]
└── Task 4b: Helium10/JungleScout adapter stubs (depends: 0a) [quick]

Wave FINAL (4 parallel reviews, then user okay):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real QA execution (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay
```

### Dependency Matrix

| Task | Blocked By | Blocks                     |
| ---- | ---------- | -------------------------- |
| 0a   | -          | 1a,1b,1c,1d,2d,3c,3g,3h,4b |
| 0b   | -          | 1a                         |
| 0c   | -          | 2e                         |
| 1a   | 0a,0b      | 2a,2f                      |
| 1b   | 0a         | 2h,3e                      |
| 1c   | 0a         | -                          |
| 1d   | 0a         | -                          |
| 2a   | 1a         | 2b,2c,3a                   |
| 2b   | 2a         | -                          |
| 2c   | 2a         | -                          |
| 2d   | 0a         | 2e,2g                      |
| 2e   | 0c,2d      | 3f                         |
| 2f   | 1a         | 3b                         |
| 2g   | 2d         | -                          |
| 2h   | 1b         | -                          |
| 3a   | 2a         | -                          |
| 3b   | 2f         | 3d                         |
| 3c   | 0a         | 3d                         |
| 3d   | 3b,3c      | -                          |
| 3e   | 1b         | -                          |
| 3f   | 2e         | -                          |
| 3g   | 0a         | -                          |
| 3h   | 0a         | -                          |
| 4a   | ALL W3     | FINAL                      |
| 4b   | 0a         | -                          |

### Agent Dispatch Summary

- **Wave 0**: 2 tasks → `quick` × 2
- **Wave 1**: 4 tasks → `deep` × 1, `unspecified-high` × 2, `quick` × 1
- **Wave 2**: 8 tasks → `deep` × 3, `unspecified-high` × 3, `visual-engineering` × 1, `unspecified-high` × 1
- **Wave 3**: 8 tasks → `deep` × 1, `unspecified-high` × 6, `quick` × 1
- **Wave 4**: 2 tasks → `deep` × 1, `quick` × 1
- **FINAL**: 4 tasks → `oracle` × 1, `unspecified-high` × 2, `deep` × 1

---

## TODOs

### Wave 0 — Prerequisite Checks

- [x] 0a. Validate test baseline (489 passed)

  **What to do**:
  - Run `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`
  - Assert exactly 489 passed, 0 failed
  - If baseline differs, STOP and report — do not proceed with any other task

  **Must NOT do**:
  - Change any test file
  - Change any source file

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 0b, 0c)
  - **Parallel Group**: Wave 0
  - **Blocks**: 1a, 1b, 1c, 1d, 2d, 3c, 3g, 3h, 4b
  - **Blocked By**: None

  **References**:
  - `tests/` — existing test suite
  - Baseline recorded in this plan's TL;DR and Verification Strategy

  **QA Scenarios**:

  ```
  Scenario: Baseline passes
    Tool: Bash
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
      2. Parse output for "N passed"
      3. Assert N >= 489 and "0 failed" or no "failed" line
    Expected Result: 489 passed, 0 failed
    Evidence: .sisyphus/evidence/task-0a-baseline.txt
  ```

  **Commit**: NO (no code changes)

- [x] 0b. Check brand table data counts (both empty → no data migration needed)

  **What to do**:
  - Write a one-off script or Python snippet to query:
    - `SELECT COUNT(*) FROM brand_profiles`
    - `SELECT COUNT(*) FROM brand_profile_cards`
  - Record counts in evidence file
  - If brand_profiles has >0 rows, Task 1a must include data migration
  - If brand_profile_cards has >0 rows, Task 1a must preserve those columns

  **Must NOT do**:
  - Modify any table or data
  - Add migration scripts yet

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 0a, 0c)
  - **Parallel Group**: Wave 0
  - **Blocks**: 1a
  - **Blocked By**: None

  **References**:
  - `pipeline/models/brand.py` — `brand_profiles` table (6 columns)
  - `pipeline/models/brand_profile.py` — `brand_profile_cards` table (11 columns)
  - `pipeline/db_migrate.py` — current migration logic

  **QA Scenarios**:

  ```
  Scenario: Brand data count
    Tool: Bash
    Steps:
      1. Run: PYTHONPATH=. python -c "from pipeline.database import get_engine; from sqlalchemy import text; e=get_engine(); r=e.execute(text('SELECT COUNT(*) FROM brand_profiles')); print('brand_profiles:', r.scalar()); r2=e.execute(text('SELECT COUNT(*) FROM brand_profile_cards')); print('brand_profile_cards:', r2.scalar())"
      2. Record both counts
    Expected Result: Both queries return integers (0 or more)
    Evidence: .sisyphus/evidence/task-0b-brand-counts.txt
  ```

  **Commit**: NO (no code changes)

- [x] 0c. QA Gate 5 criteria (confirmed: ≥0.6 PASS)

  **What to do**:
  - This is a user decision point, not a code task
  - Need user to specify: What criteria should Gate 5 evaluate?
  - Suggested default: composite score from 5-layer tag coverage (≥3 layers tagged) + brand consistency score (≥0.7) + resolution check (≥1024px)
  - Record decision in evidence file

  **Must NOT do**:
  - Implement anything — just record the decision

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 0a, 0b)
  - **Parallel Group**: Wave 0
  - **Blocks**: 2e
  - **Blocked By**: None

  **Commit**: NO

### Wave 1 — P0 Foundation Fixes

- [x] 1a. Merge dual BrandProfile into unified model

  **What to do**:
  - Keep `brand_profile.py` as the survivor (11-column superset in `brand_profile_cards` table)
  - Add any columns from `brand.py`'s `brand_profiles` that are missing (likely: none, 11 is superset of 6)
  - If 0b found data in `brand_profiles`: write ALTER TABLE migration in `db_migrate.py` to copy data → `brand_profile_cards`, then DROP old table
  - If 0b found 0 rows in `brand_profiles`: just DROP table in migration
  - Update ALL imports: `grep -rn "from pipeline.models.brand import" pipeline/` → change to `from pipeline.models.brand_profile import`
  - Update `__init__.py` barrel exports if any
  - Delete `pipeline/models/brand.py` after all references migrated
  - Run full test suite to verify no breakage

  **Must NOT do**:
  - Add new columns beyond the 11-column superset
  - Use Alembic
  - Change any business logic — only model consolidation

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Reason: multi-file refactor with data migration risk, needs careful reference tracking

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 1b, 1c, 1d — all in Wave 1)
  - **Parallel Group**: Wave 1
  - **Blocks**: 2a, 2f
  - **Blocked By**: 0a, 0b

  **References**:
  - `pipeline/models/brand.py` — source model to eliminate (brand_profiles, 6 cols)
  - `pipeline/models/brand_profile.py` — survivor model (brand_profile_cards, 11 cols)
  - `pipeline/db_migrate.py` — add ALTER TABLE / DROP TABLE here
  - `pipeline/models/__init__.py` — update exports
  - Evidence from 0b — data counts determining migration strategy

  **QA Scenarios**:

  ```
  Scenario: No dual brand imports remain
    Tool: Bash
    Steps:
      1. Run: grep -rn "from pipeline.models.brand import" pipeline/
      2. Assert 0 results
    Expected Result: No matches
    Evidence: .sisyphus/evidence/task-1a-no-dual-imports.txt

  Scenario: Tests still pass
    Tool: Bash
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
      2. Assert ≥489 passed, 0 failed
    Expected Result: ≥489 passed
    Evidence: .sisyphus/evidence/task-1a-tests.txt

  Scenario: brand.py file deleted
    Tool: Bash
    Steps:
      1. Run: ls pipeline/models/brand.py
      2. Assert file does not exist (exit code 1)
    Expected Result: "No such file or directory"
    Evidence: .sisyphus/evidence/task-1a-brand-deleted.txt
  ```

  **Commit**: YES
  - Message: `refactor(models): merge dual BrandProfile into unified model`
  - Files: `pipeline/models/brand.py` (deleted), `pipeline/models/brand_profile.py`, `pipeline/db_migrate.py`, all files with updated imports
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`

- [x] 1b. Wire customer_brief data into brief generation

  **What to do**:
  - In `brief_generator.py`, add a DB query to fetch `customer_brief` row for the current project
  - Inject non-NULL fields from customer_brief into the LLM prompt context
  - Fields to inject: `brand_voice`, `target_audience`, `product_usp`, `visual_preferences`, `competitor_refs`, `campaign_goal`, `budget_range`, `timeline`, `special_instructions`, `reference_images`
  - Skip any field that is NULL (don't inject placeholder text)
  - Add test: mock customer_brief with 3 filled fields + 7 NULL → verify only 3 appear in prompt

  **Must NOT do**:
  - Change customer_brief model or table schema
  - Make customer_brief required — brief generation must still work if no customer_brief exists
  - Add default values for NULL fields

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 1a, 1c, 1d)
  - **Parallel Group**: Wave 1
  - **Blocks**: 2h, 3e
  - **Blocked By**: 0a

  **References**:
  - `pipeline/layers/brief_generator.py` — current brief generation (no customer_brief usage)
  - `pipeline/models/customer_brief.py` — CustomerBrief model with 10 fields
  - `pipeline/database.py` — DB session management

  **QA Scenarios**:

  ```
  Scenario: Brief includes customer_brief data
    Tool: Bash
    Steps:
      1. Create test: mock DB with customer_brief having brand_voice="Bold and modern", target_audience="Gen Z", product_usp="Eco-friendly"
      2. Call brief_generator with that project
      3. Assert generated brief contains "Bold and modern", "Gen Z", "Eco-friendly"
    Expected Result: All 3 non-NULL fields appear in brief output
    Evidence: .sisyphus/evidence/task-1b-brief-injection.txt

  Scenario: Brief works without customer_brief
    Tool: Bash
    Steps:
      1. Create test: mock DB with no customer_brief row for project
      2. Call brief_generator
      3. Assert no error, brief still generated
    Expected Result: Brief generated successfully without customer_brief data
    Evidence: .sisyphus/evidence/task-1b-no-brief.txt
  ```

  **Commit**: YES
  - Message: `feat(brief): wire customer_brief data into brief generation`
  - Files: `pipeline/layers/brief_generator.py`, `tests/test_brief_generator.py`
  - Pre-commit: test command

- [x] 1c. Top 50 ASIN + listing enrichment

  **What to do**:
  - In `amazon_data.py` (or equivalent data fetch layer), change default `top_n=20` → `top_n=50`
  - Enrich competitor_listing model/storage to include: `title`, `price`, `rating`, `review_count`, `bullet_points` (as JSON array), `description`, `main_image_url`, `category_rank`
  - Add ALTER TABLE migration in `db_migrate.py` for new columns (idempotent)
  - Update the ASIN fetch logic to populate these fields from the Keepa/API response
  - Parse `bullet_points` as structured JSON array instead of raw text
  - Parse `description` (currently always None) from listing data

  **Must NOT do**:
  - Change Keepa API integration pattern
  - Add new pip dependencies
  - Break existing ASIN fetch for projects with <50 ASINs (handle gracefully)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 1a, 1b, 1d)
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: 0a

  **References**:
  - `pipeline/layers/amazon_data.py` or equivalent — current top_n=20 logic
  - `pipeline/models/competitor_listing.py` — current model (asin + slot_index only)
  - `pipeline/db_migrate.py` — add ALTER TABLE
  - `docs/PRD.md` lines referencing F-DA-01

  **QA Scenarios**:

  ```
  Scenario: Top 50 default
    Tool: Bash
    Steps:
      1. Grep for top_n or equivalent in amazon_data.py
      2. Assert default is 50
    Expected Result: Default top_n=50
    Evidence: .sisyphus/evidence/task-1c-top50.txt

  Scenario: Listing has enriched fields
    Tool: Bash
    Steps:
      1. Run test that creates a competitor_listing with all enriched fields
      2. Assert title, price, rating, review_count, bullet_points, description, main_image_url, category_rank are stored and retrievable
    Expected Result: All 8 enriched fields round-trip through DB
    Evidence: .sisyphus/evidence/task-1c-enriched.txt
  ```

  **Commit**: YES
  - Message: `feat(amazon): expand top ASIN to 50 + enrich listing data`
  - Files: `pipeline/layers/amazon_data.py`, `pipeline/models/competitor_listing.py`, `pipeline/db_migrate.py`, `tests/test_amazon_data.py`

- [x] 1d. Wire Gemini Vision adapter into main analysis flow

  **What to do**:
  - `gemini_vision_adapter.py` already implements the adapter interface — verify it's registered in `registry.py`
  - In `vision_analyzer.py` (or orchestrator), add config option `VISION_PROVIDER=openai|gemini` (default: openai for backward compat)
  - When `VISION_PROVIDER=gemini`, route vision analysis calls through `gemini_vision_adapter`
  - Add test with mock: verify gemini path is called when config is set

  **Must NOT do**:
  - Change default behavior (must remain openai by default)
  - Modify gemini_vision_adapter.py internals (already implemented)
  - Make Gemini Vision a hard dependency

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 1a, 1b, 1c)
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: 0a

  **References**:
  - `pipeline/adapters/gemini_vision_adapter.py` — already implemented adapter
  - `pipeline/adapters/registry.py` — adapter registration
  - `pipeline/layers/vision_analyzer.py` — current vision analysis (OpenAI only)
  - `pipeline/config.py` — add VISION_PROVIDER config

  **QA Scenarios**:

  ```
  Scenario: Gemini Vision routed when configured
    Tool: Bash
    Steps:
      1. Set VISION_PROVIDER=gemini in test env
      2. Mock gemini_vision_adapter call
      3. Run vision analysis
      4. Assert gemini adapter was called, not openai
    Expected Result: Gemini adapter invoked
    Evidence: .sisyphus/evidence/task-1d-gemini-route.txt

  Scenario: Default still uses OpenAI
    Tool: Bash
    Steps:
      1. Don't set VISION_PROVIDER (or set to openai)
      2. Run vision analysis
      3. Assert openai path used
    Expected Result: OpenAI adapter invoked by default
    Evidence: .sisyphus/evidence/task-1d-default-openai.txt
  ```

  **Commit**: YES
  - Message: `feat(vision): wire Gemini Vision adapter into main analysis flow`
  - Files: `pipeline/layers/vision_analyzer.py`, `pipeline/config.py`, `pipeline/adapters/registry.py`, `tests/test_vision_gemini.py`

### Wave 2 — Core Engines + Analysis

- [ ] 2a. Fan-out engine interface + Mock engine

  **What to do**:
  - Create `pipeline/engines/base.py` with abstract `ImageEngine` interface: `generate(prompt, params) -> EngineResult`
  - `EngineResult` dataclass: `image_bytes`, `engine_name`, `latency_ms`, `error` (optional), `status` (success/failed)
  - Create `pipeline/engines/mock_engine.py` implementing `ImageEngine` — returns a 1x1 PNG placeholder
  - Create `pipeline/engines/fan_out.py`: accepts list of engines, runs all via `asyncio.gather`, returns `FanOutResult` with per-engine results
  - `FanOutResult`: `results: list[EngineResult]`, `any_success: bool`, `all_success: bool`
  - Partial failure policy: if ≥1 engine succeeds, `FanOutResult.any_success=True` — proceed with successful results
  - Register mock engine in a simple `ENGINES` dict by name
  - Add test: 3 mock engines, one forced to fail → assert `any_success=True`, 2 successful results

  **Must NOT do**:
  - Add Celery/Redis/message queue
  - Import GPT or Gemini SDKs in this task (those are 2b/2c)
  - Add new pip dependencies

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Reason: core architectural interface design with async coordination

  **Parallelization**:
  - **Can Run In Parallel**: NO (first in Wave 2, but depends on 1a)
  - **Parallel Group**: Wave 2
  - **Blocks**: 2b, 2c, 3a
  - **Blocked By**: 1a

  **References**:
  - `pipeline/adapters/registry.py` — existing adapter registry pattern to follow
  - `pipeline/adapters/mock_adapter.py` — existing mock adapter for reference
  - `docs/SYSTEM_SPEC.md` §6.3 — Fan-out three-engine definition
  - `docs/PRD.md` F-GEN-06 — Fan-out requirements

  **QA Scenarios**:

  ```
  Scenario: Fan-out with partial failure
    Tool: Bash
    Steps:
      1. Run test: 3 mock engines, engine_b raises Exception
      2. Assert FanOutResult.any_success == True
      3. Assert len([r for r in results if r.status == 'success']) == 2
      4. Assert len([r for r in results if r.status == 'failed']) == 1
    Expected Result: 2 success, 1 failed, any_success=True
    Evidence: .sisyphus/evidence/task-2a-partial-failure.txt

  Scenario: Fan-out all succeed
    Tool: Bash
    Steps:
      1. Run test: 3 mock engines, all return valid image
      2. Assert FanOutResult.all_success == True
    Expected Result: all_success=True
    Evidence: .sisyphus/evidence/task-2a-all-success.txt

  Scenario: Tests still pass
    Tool: Bash
    Steps:
      1. Run full test suite
      2. Assert ≥489 passed
    Expected Result: ≥489 passed, 0 failed
    Evidence: .sisyphus/evidence/task-2a-tests.txt
  ```

  **Commit**: YES
  - Message: `feat(fanout): add fan-out engine interface + mock engine`
  - Files: `pipeline/engines/base.py`, `pipeline/engines/mock_engine.py`, `pipeline/engines/fan_out.py`, `pipeline/engines/__init__.py`, `tests/test_fan_out.py`

- [ ] 2b. GPT-image-1 engine adapter

  **What to do**:
  - Create `pipeline/engines/gpt_image_engine.py` implementing `ImageEngine`
  - Wrap existing `gpt_image_adapter.py` logic into the new `ImageEngine.generate()` interface
  - Read API key from config (`OPENAI_API_KEY`)
  - Capture latency_ms, handle API errors → return `EngineResult(status='failed', error=str(e))`
  - Register as `"gpt-image-1"` in engines dict
  - Add test: mock OpenAI API response → verify EngineResult fields

  **Must NOT do**:
  - Change `gpt_image_adapter.py` — wrap, don't modify
  - Make real API calls in tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 2c, 2d, 2e, 2f, 2g, 2h)
  - **Parallel Group**: Wave 2 (after 2a)
  - **Blocks**: None
  - **Blocked By**: 2a

  **References**:
  - `pipeline/adapters/gpt_image_adapter.py` — existing GPT image generation logic
  - `pipeline/engines/base.py` — ImageEngine interface (from 2a)
  - `pipeline/config.py` — API key config

  **QA Scenarios**:

  ```
  Scenario: GPT engine returns EngineResult on success
    Tool: Bash
    Steps:
      1. Mock OpenAI images API to return base64 PNG
      2. Call gpt_image_engine.generate(prompt="test", params={})
      3. Assert result.status == 'success', result.image_bytes is not None, result.engine_name == 'gpt-image-1'
    Expected Result: Valid EngineResult with image bytes
    Evidence: .sisyphus/evidence/task-2b-gpt-success.txt

  Scenario: GPT engine handles API error
    Tool: Bash
    Steps:
      1. Mock OpenAI API to raise RateLimitError
      2. Call gpt_image_engine.generate(...)
      3. Assert result.status == 'failed', result.error contains 'rate'
    Expected Result: Graceful failure with error message
    Evidence: .sisyphus/evidence/task-2b-gpt-error.txt
  ```

  **Commit**: YES
  - Message: `feat(fanout): add GPT-image-1 engine adapter`
  - Files: `pipeline/engines/gpt_image_engine.py`, `tests/test_gpt_engine.py`

- [ ] 2c. Gemini Imagen engine adapter

  **What to do**:
  - Create `pipeline/engines/gemini_image_engine.py` implementing `ImageEngine`
  - Wrap existing `gemini_image_adapter.py` logic into `ImageEngine.generate()`
  - Read API key from config (`GEMINI_API_KEY`)
  - Capture latency_ms, handle API errors → `EngineResult(status='failed')`
  - Register as `"gemini-imagen"` in engines dict
  - Add test: mock Gemini API response → verify EngineResult

  **Must NOT do**:
  - Change `gemini_image_adapter.py`
  - Make real API calls in tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 2b, 2d, 2e, 2f, 2g, 2h)
  - **Parallel Group**: Wave 2 (after 2a)
  - **Blocks**: None
  - **Blocked By**: 2a

  **References**:
  - `pipeline/adapters/gemini_image_adapter.py` — existing Gemini image generation logic
  - `pipeline/engines/base.py` — ImageEngine interface (from 2a)
  - `pipeline/config.py` — API key config

  **QA Scenarios**:

  ```
  Scenario: Gemini engine returns EngineResult
    Tool: Bash
    Steps:
      1. Mock Gemini API to return image bytes
      2. Call gemini_image_engine.generate(prompt="test", params={})
      3. Assert result.status == 'success', result.engine_name == 'gemini-imagen'
    Expected Result: Valid EngineResult
    Evidence: .sisyphus/evidence/task-2c-gemini-success.txt
  ```

  **Commit**: YES
  - Message: `feat(fanout): add Gemini Imagen engine adapter`
  - Files: `pipeline/engines/gemini_image_engine.py`, `tests/test_gemini_engine.py`

- [ ] 2d. Vision 5-layer tags + tag_assignment persistence

  **What to do**:
  - In `vision_analyzer.py`, extend analysis to produce all 5 layers: INTENT, ROLE, COLOR, LAYOUT, STYLE
  - Currently only INTENT+ROLE are extracted — add prompts/logic for COLOR, LAYOUT, STYLE
  - After analysis, write results to `tag_assignment` table via the existing `TagAssignment` model
  - Each tag_assignment row: `image_id`, `tag_layer` (enum), `tag_value`, `confidence`, `source` (auto/manual)
  - Add migration in `db_migrate.py` if `tag_assignment` table needs new columns
  - Add test: mock vision API → verify 5 tag layers written to tag_assignment

  **Must NOT do**:
  - Add tag layers beyond the 5 defined (INTENT/ROLE/COLOR/LAYOUT/STYLE)
  - Change tag definitions in `constants/tags.py`
  - Make real LLM calls in tests

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Reason: multi-component change (vision prompts + DB persistence + model wiring)

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 2b, 2c, 2f, 2g, 2h — but 2g depends on 2d)
  - **Parallel Group**: Wave 2
  - **Blocks**: 2e, 2g
  - **Blocked By**: 0a

  **References**:
  - `pipeline/layers/vision_analyzer.py` — current 2-layer analysis
  - `pipeline/constants/tags.py` — 5-layer tag definitions (INTENT, ROLE, COLOR, LAYOUT, STYLE)
  - `pipeline/models/tag_assignment.py` — existing model (never written to)
  - `pipeline/db_migrate.py` — for any schema changes

  **QA Scenarios**:

  ```
  Scenario: All 5 tag layers produced
    Tool: Bash
    Steps:
      1. Mock vision API to return structured tags for all 5 layers
      2. Run vision_analyzer on a test image
      3. Query tag_assignment table for that image
      4. Assert 5 distinct tag_layer values exist
    Expected Result: INTENT, ROLE, COLOR, LAYOUT, STYLE all present in tag_assignment
    Evidence: .sisyphus/evidence/task-2d-5layers.txt

  Scenario: tag_assignment persisted to DB
    Tool: Bash
    Steps:
      1. Run vision analysis with mock
      2. Query: SELECT COUNT(*) FROM tag_assignment WHERE image_id = ?
      3. Assert count >= 5
    Expected Result: ≥5 rows written
    Evidence: .sisyphus/evidence/task-2d-persistence.txt
  ```

  **Commit**: YES
  - Message: `feat(vision): implement 5-layer tag analysis + tag_assignment persistence`
  - Files: `pipeline/layers/vision_analyzer.py`, `pipeline/db_migrate.py`, `tests/test_vision_5layer.py`

- [ ] 2e. QA Gate 5 — Real Composite Evaluation

  **What to do**:
  - Replace hardcoded PASS in `qa_gate.py` Gate 5 with composite scoring:
    - 5-layer tag coverage ≥ 3 layers present → score component
    - Brand consistency ≥ 0.7 (cosine similarity between generated image embedding and brand reference) → score component
    - Resolution ≥ 1024px on both dimensions → binary pass
  - Composite formula: `0.4 * tag_coverage_norm + 0.4 * brand_consistency + 0.2 * resolution_pass`
  - Threshold: **≥ 0.6 PASS, < 0.6 FAIL** (confirmed)
  - Log per-component scores to `gate_results` table
  - Write tests covering: all-pass, one-fail, edge-at-threshold

  **Must NOT do**:
  - Call external LLM for scoring (use deterministic formula)
  - Change Gate 1-4 behavior

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with 2a-2d, 2f-2h)
  - **Blocks**: 4a (integration tests)
  - **Blocked By**: 0c (tag constants)

  **References**:
  - `pipeline/layers/qa_gate.py` — current Gate 5 hardcoded PASS logic
  - `pipeline/constants/tags.py` — 5-layer tag definitions for coverage check
  - `pipeline/models/gate_result.py` — GateResult model for persisting scores
  - `docs/PRD.md` — F-QA-05 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate5.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Gate 5 passes with good scores
    Tool: Bash
    Steps:
      1. Create mock image result with 4/5 layers tagged, brand_consistency=0.85, resolution=2048x2048
      2. Run Gate 5 evaluation
      3. Assert result.passed == True, result.score >= 0.6
    Expected Result: PASS with score ~0.82
    Evidence: .sisyphus/evidence/task-2e-gate5-pass.txt

  Scenario: Gate 5 fails on low brand consistency
    Tool: Bash
    Steps:
      1. Create mock with 5/5 layers, brand_consistency=0.3, resolution=2048x2048
      2. Run Gate 5 evaluation
      3. Assert result.passed == False
    Expected Result: FAIL with score < 0.6
    Evidence: .sisyphus/evidence/task-2e-gate5-fail.txt
  ```

  **Commit**: YES (groups with 2d)
  - Message: `feat(qa): implement Gate 5 composite evaluation scoring`
  - Files: `pipeline/layers/qa_gate.py`, `tests/test_qa_gate5.py`

- [ ] 2f. Hypothesis Management CRUD (F-DRL-02)

  **What to do**:
  - Create `pipeline/models/hypothesis.py`: Hypothesis model with fields: id, project_id, category (e.g. "color_preference", "style_trend"), statement, status (pending/validated/rejected), evidence_json, created_at, validated_at
  - Add `db_migrate.py` migration for `hypotheses` table
  - Create `pipeline/web/routes/hypothesis_routes.py` with CRUD:
    - `POST /api/projects/{id}/hypotheses` — create
    - `GET /api/projects/{id}/hypotheses` — list (filter by status)
    - `PATCH /api/hypotheses/{id}` — update status + evidence
    - `DELETE /api/hypotheses/{id}` — soft delete
  - Register blueprint in `app.py`
  - Write tests for all 4 endpoints

  **Must NOT do**:
  - Implement auto-validation logic (that's F-DRL-03 tracking)
  - Add new pip dependencies

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 3b (14-day tracking)
  - **Blocked By**: None

  **References**:
  - `pipeline/models/project.py` — Project model for FK relationship
  - `pipeline/web/routes/project_routes.py` — existing route pattern to follow
  - `pipeline/db_migrate.py` — migration pattern
  - `docs/PRD.md` — F-DRL-02 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_hypothesis_crud.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Full CRUD lifecycle
    Tool: Bash (curl)
    Steps:
      1. POST /api/projects/1/hypotheses body={"category":"color","statement":"Blue sells 2x"}
      2. Assert 201, response has id
      3. GET /api/projects/1/hypotheses → list contains new hypothesis
      4. PATCH /api/hypotheses/{id} body={"status":"validated","evidence_json":{"sales_lift":1.8}}
      5. Assert 200, status=validated
      6. DELETE /api/hypotheses/{id} → 200
    Expected Result: All CRUD ops succeed
    Evidence: .sisyphus/evidence/task-2f-hypothesis-crud.txt

  Scenario: Create hypothesis for non-existent project
    Tool: Bash (curl)
    Steps:
      1. POST /api/projects/99999/hypotheses body={"category":"x","statement":"y"}
      2. Assert 404
    Expected Result: 404 with error message
    Evidence: .sisyphus/evidence/task-2f-hypothesis-404.txt
  ```

  **Commit**: YES
  - Message: `feat(drl): add Hypothesis model and CRUD endpoints (F-DRL-02)`
  - Files: `pipeline/models/hypothesis.py`, `pipeline/web/routes/hypothesis_routes.py`, `pipeline/db_migrate.py`, `tests/test_hypothesis_crud.py`

- [ ] 2g. Human Annotation Review UI (F-DA-03)

  **What to do**:
  - Create `pipeline/web/templates/annotation_review.html` — tag review page (NOT delivery approval)
  - Shows images with their AI-assigned 5-layer tags
  - Reviewer can: approve tags, edit tags, reject image
  - Backend: `GET /api/projects/{id}/annotations` returns images + tags; `PATCH /api/annotations/{id}` saves reviewer edits
  - Add `reviewed_by`, `reviewed_at`, `review_status` fields to `tag_assignment` table via migration
  - CSS in external `style.css` only (no inline `<style>`)

  **Must NOT do**:
  - Modify existing `/review` delivery approval flow
  - Add JavaScript frameworks (vanilla JS only, consistent with existing templates)

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 4a (integration tests)
  - **Blocked By**: 0c (tag constants), 2d (5-layer vision)

  **References**:
  - `pipeline/web/templates/review.html` — existing review page pattern (but this is delivery review, NOT annotation)
  - `pipeline/models/tag_assignment.py` — TagAssignment model
  - `pipeline/web/static/style.css` — project CSS file
  - `pipeline/web/routes/review_routes.py` — existing route pattern

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_annotation_review.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Load annotation review page
    Tool: Playwright
    Steps:
      1. Navigate to /projects/1/annotation-review
      2. Assert page contains images with tag badges for each layer (COLOR, LAYOUT, STYLE, COMPOSITION, OBJECT)
      3. Click "Approve" on first image
      4. Assert tag status changes to "approved"
    Expected Result: Page renders with tags, approve action persists
    Evidence: .sisyphus/evidence/task-2g-annotation-ui.png

  Scenario: Edit a tag assignment
    Tool: Playwright
    Steps:
      1. Navigate to /projects/1/annotation-review
      2. Click "Edit" on first image's COLOR tag
      3. Change value from "warm" to "cool"
      4. Click Save
      5. Refresh page, assert COLOR tag shows "cool"
    Expected Result: Edited tag persists after refresh
    Evidence: .sisyphus/evidence/task-2g-annotation-edit.png
  ```

  **Commit**: YES
  - Message: `feat(ui): add human annotation review page (F-DA-03)`
  - Files: `pipeline/web/templates/annotation_review.html`, `pipeline/web/routes/annotation_routes.py`, `pipeline/web/static/style.css`, `pipeline/models/tag_assignment.py`, `pipeline/db_migrate.py`, `tests/test_annotation_review.py`

- [ ] 2h. A+ Storyboard Product Context Injection (F-GEN-04)

  **What to do**:
  - In storyboard generation, inject product context into each panel prompt:
    - ASIN data (title, category, bullet_points) from `top_asins` table
    - Brand profile (tone, color palette, visual style) from unified `brand_profiles` table (after 0a merge)
    - Customer brief key selling points from `customer_briefs` table
  - Modify `pipeline/layers/storyboard_generator.py` (or equivalent) to fetch and format context
  - Each panel prompt should include: `[PRODUCT: {title}] [BRAND: {tone}, {palette}] [USP: {selling_points}]`
  - Write tests verifying context appears in generated prompts

  **Must NOT do**:
  - Change the storyboard structure/panel count
  - Add new LLM calls (context is injected into existing prompts)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: 4a (integration tests)
  - **Blocked By**: 0a (brand merge), 1b (brief injection)

  **References**:
  - `pipeline/layers/storyboard_generator.py` — current storyboard generation (prompts lack product context)
  - `pipeline/models/brand.py` — unified brand model (after 0a)
  - `pipeline/models/customer_brief.py` — customer brief data
  - `pipeline/models/top_asin.py` — ASIN data source
  - `docs/PRD.md` — F-GEN-04 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_storyboard_context.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Storyboard prompts contain product context
    Tool: Bash
    Steps:
      1. Create project with brand_profile (tone="premium", palette="navy,gold"), customer_brief (usp="waterproof"), top_asin (title="Premium Watch")
      2. Run storyboard generation
      3. Inspect generated panel prompts
      4. Assert each prompt contains "premium", "navy", "waterproof", "Premium Watch"
    Expected Result: All panel prompts include injected context
    Evidence: .sisyphus/evidence/task-2h-storyboard-context.txt

  Scenario: Storyboard handles missing brief gracefully
    Tool: Bash
    Steps:
      1. Create project with brand_profile but NO customer_brief
      2. Run storyboard generation
      3. Assert prompts contain brand context, USP section is omitted (not "None")
    Expected Result: Graceful degradation, no crash
    Evidence: .sisyphus/evidence/task-2h-storyboard-no-brief.txt
  ```

  **Commit**: YES (groups with 2e)
  - Message: `feat(gen): inject product context into A+ storyboard prompts (F-GEN-04)`
  - Files: `pipeline/layers/storyboard_generator.py`, `tests/test_storyboard_context.py`

---

### Wave 3 — Integration Features & Delivery (After Wave 2)

- [x] 3a. Event-Driven ASIN Trigger on Project Create

  **What to do**:
  - After `project_create` (in `project_routes.py`), automatically trigger ASIN data fetch pipeline
  - Add `post_create_hook` in orchestrator: calls `fetch_top_asins(project_id)` asynchronously
  - Use existing `threading.Thread` pattern (no new deps like Celery)
  - Add `auto_triggered` boolean + `trigger_source` field to pipeline_runs table
  - Write tests: project creation → verify ASIN fetch was triggered

  **Must NOT do**:
  - Add message queue (Celery/RabbitMQ/Redis queue)
  - Block the POST response waiting for ASIN fetch

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with 3b-3h)
  - **Blocks**: 4a
  - **Blocked By**: 1a (top_asin enrichment)

  **References**:
  - `pipeline/web/routes/project_routes.py` — POST /api/projects endpoint
  - `pipeline/orchestrator.py` — pipeline execution entry point
  - `pipeline/layers/asin_fetcher.py` — ASIN fetch logic
  - `docs/PRD.md` — event-driven trigger spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_event_trigger.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Project creation triggers ASIN fetch
    Tool: Bash (curl)
    Steps:
      1. POST /api/projects body={"name":"Test","marketplace":"US","category":"Electronics"}
      2. Assert 201
      3. Wait 2s, GET /api/projects/{id}/pipeline-runs
      4. Assert at least 1 run with auto_triggered=true, trigger_source="project_create"
    Expected Result: Auto-triggered pipeline run exists
    Evidence: .sisyphus/evidence/task-3a-event-trigger.txt

  Scenario: Manual run not marked as auto-triggered
    Tool: Bash (curl)
    Steps:
      1. POST /api/projects/{id}/run
      2. Assert new run has auto_triggered=false
    Expected Result: Manual runs distinguishable from auto
    Evidence: .sisyphus/evidence/task-3a-manual-run.txt
  ```

  **Commit**: YES
  - Message: `feat(orchestrator): event-driven ASIN trigger on project create`
  - Files: `pipeline/web/routes/project_routes.py`, `pipeline/orchestrator.py`, `pipeline/db_migrate.py`, `tests/test_event_trigger.py`

- [ ] 3b. 14-Day Auto Tracking (F-DRL-03)

  **What to do**:
  - Add tracking fields to `hypotheses` table: `tracking_start_date`, `tracking_end_date`, `last_checked_at`, `check_count`
  - Create `pipeline/layers/hypothesis_tracker.py`:
    - `check_hypotheses()` — finds hypotheses with status=pending, tracking active, and checks evidence sources
    - Evidence check: query sales data / ASIN performance from existing data (not external API yet)
    - Auto-validate if evidence threshold met, auto-reject after 14 days with insufficient evidence
  - Add CLI command: `aip track-hypotheses` that runs the check
  - Scheduler: document cron setup (no in-process scheduler to keep it simple)
  - Notify via log + optional webhook (reuse existing notification pattern)

  **Must NOT do**:
  - Add APScheduler or similar in-process scheduler
  - Call external data sources (use existing DB data for validation)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: 2f (hypothesis CRUD)

  **References**:
  - `pipeline/models/hypothesis.py` — Hypothesis model (created in 2f)
  - `pipeline/__main__.py` — CLI entry point for adding commands
  - `docs/PRD.md` — F-DRL-03 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_hypothesis_tracker.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Auto-reject after 14 days
    Tool: Bash
    Steps:
      1. Create hypothesis with tracking_start_date = 15 days ago, status=pending, no evidence
      2. Run `PYTHONPATH=. python -m pipeline.__main__ track-hypotheses`
      3. Query hypothesis status
    Expected Result: status=rejected, validated_at set
    Evidence: .sisyphus/evidence/task-3b-auto-reject.txt

  Scenario: Auto-validate with sufficient evidence
    Tool: Bash
    Steps:
      1. Create hypothesis with tracking_start_date = 5 days ago, evidence_json with 3+ data points
      2. Run track-hypotheses
      3. Query status
    Expected Result: status=validated
    Evidence: .sisyphus/evidence/task-3b-auto-validate.txt
  ```

  **Commit**: YES
  - Message: `feat(drl): implement 14-day hypothesis auto-tracking (F-DRL-03)`
  - Files: `pipeline/layers/hypothesis_tracker.py`, `pipeline/models/hypothesis.py`, `pipeline/__main__.py`, `pipeline/db_migrate.py`, `tests/test_hypothesis_tracker.py`

- [ ] 3c. Delivery ZIP + Path Fix + Delivered Status

  **What to do**:
  - Fix delivery path mismatch: ensure output paths in `delivery.py` match actual generated file locations
  - Add ZIP packaging: `create_delivery_zip(project_id)` bundles all approved images + metadata JSON into `deliveries/{project_id}/delivery_{timestamp}.zip`
  - Add `delivered` status to project lifecycle (after `approved`): `project.status = "delivered"` after ZIP creation
  - Add migration for `delivered_at` timestamp field on projects
  - Endpoint: `POST /api/projects/{id}/deliver` → creates ZIP, sets status
  - Write tests for path resolution, ZIP contents, status transition

  **Must NOT do**:
  - Add new pip dependencies for ZIP (use stdlib `zipfile`)
  - Change image storage structure

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 3d (PDF report needs delivery data)
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/delivery.py` — current delivery logic with path issues
  - `pipeline/models/project.py` — Project model, status field
  - `pipeline/web/routes/delivery_routes.py` — existing delivery endpoints

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_delivery_zip.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Create delivery ZIP
    Tool: Bash (curl + unzip)
    Steps:
      1. Setup project with 3 approved images
      2. POST /api/projects/{id}/deliver
      3. Assert 200, response contains zip_path
      4. Unzip file, verify contains 3 images + metadata.json
      5. GET /api/projects/{id} → status == "delivered"
    Expected Result: Valid ZIP with all approved images, project status updated
    Evidence: .sisyphus/evidence/task-3c-delivery-zip.txt

  Scenario: Deliver with no approved images
    Tool: Bash (curl)
    Steps:
      1. Project with 0 approved images
      2. POST /api/projects/{id}/deliver
      3. Assert 400 with message "No approved images to deliver"
    Expected Result: Graceful rejection
    Evidence: .sisyphus/evidence/task-3c-no-images.txt
  ```

  **Commit**: YES
  - Message: `feat(delivery): add ZIP packaging, path fix, delivered status`
  - Files: `pipeline/layers/delivery.py`, `pipeline/models/project.py`, `pipeline/db_migrate.py`, `pipeline/web/routes/delivery_routes.py`, `tests/test_delivery_zip.py`

- [ ] 3d. 1-Page PDF Recommendation Report (Signal Light)

  **What to do**:
  - Create `pipeline/layers/pdf_report.py` using `reportlab` (add to requirements.txt — exception to no-new-deps for PDF)
  - Report contains:
    - Project header (name, marketplace, category)
    - Signal light: GREEN (≥80% gates passed) / YELLOW (60-79%) / RED (<60%)
    - Per-image thumbnail grid with pass/fail badges
    - Top 3 recommendations based on gate failures
    - Brand consistency score summary
  - Endpoint: `GET /api/projects/{id}/report.pdf` → streams PDF
  - Write tests for signal light logic and PDF generation

  **Must NOT do**:
  - Use wkhtmltopdf or browser-based PDF (use reportlab for server-side)
  - Make PDF generation blocking for delivery flow

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: 3c (needs delivery data)

  **References**:
  - `docs/PRD.md` — PDF report spec, signal light criteria
  - `pipeline/models/gate_result.py` — gate pass/fail data
  - `pipeline/models/project.py` — project metadata

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_pdf_report.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Generate GREEN signal PDF
    Tool: Bash (curl)
    Steps:
      1. Project with 5 images, 4 passed all gates (80%)
      2. GET /api/projects/{id}/report.pdf
      3. Assert 200, Content-Type=application/pdf
      4. Save to file, verify file size > 1KB
    Expected Result: Valid PDF with GREEN signal
    Evidence: .sisyphus/evidence/task-3d-pdf-green.pdf

  Scenario: RED signal with recommendations
    Tool: Bash (curl)
    Steps:
      1. Project with 5 images, 2 passed (40%)
      2. GET /api/projects/{id}/report.pdf
      3. Assert 200, valid PDF
    Expected Result: PDF with RED signal and failure-based recommendations
    Evidence: .sisyphus/evidence/task-3d-pdf-red.pdf
  ```

  **Commit**: YES
  - Message: `feat(report): add 1-page PDF recommendation report with signal light`
  - Files: `pipeline/layers/pdf_report.py`, `pipeline/web/routes/report_routes.py`, `requirements.txt`, `tests/test_pdf_report.py`

- [ ] 3e. Content Marketing System

  **What to do**:
  - Create `pipeline/layers/content_generator.py`:
    - Input: project data (brand profile, top ASINs, generated images)
    - Output JSON: `{ "copy": [...], "social_posts": [...], "seo_keywords": [...] }`
    - Uses existing LLM adapter (GPT) to generate marketing copy
  - Create `pipeline/models/content_asset.py`: ContentAsset model (project_id, asset_type, content_json, created_at)
  - Migration for `content_assets` table
  - Endpoints:
    - `POST /api/projects/{id}/content/generate` — trigger generation
    - `GET /api/projects/{id}/content` — list generated assets
  - Write tests with mocked LLM responses

  **Must NOT do**:
  - Auto-publish to any platform
  - Add social media API integrations

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: 0a (brand profile)

  **References**:
  - `pipeline/adapters/openai_adapter.py` — LLM call pattern
  - `pipeline/models/brand.py` — brand data for copy generation
  - `docs/PRD.md` — content marketing spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_content_generator.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Generate content assets
    Tool: Bash (curl)
    Steps:
      1. POST /api/projects/{id}/content/generate
      2. Assert 200
      3. GET /api/projects/{id}/content
      4. Assert response contains copy array, social_posts array, seo_keywords array
    Expected Result: All 3 content types generated
    Evidence: .sisyphus/evidence/task-3e-content-gen.txt

  Scenario: Generate with no brand profile
    Tool: Bash (curl)
    Steps:
      1. Project with no brand profile
      2. POST /api/projects/{id}/content/generate
      3. Assert 400 "Brand profile required"
    Expected Result: Clear error message
    Evidence: .sisyphus/evidence/task-3e-no-brand.txt
  ```

  **Commit**: YES
  - Message: `feat(content): add content marketing generation system`
  - Files: `pipeline/layers/content_generator.py`, `pipeline/models/content_asset.py`, `pipeline/web/routes/content_routes.py`, `pipeline/db_migrate.py`, `tests/test_content_generator.py`

- [ ] 3f. Feedback LLM Fallback + Action Persistence (F-DEL-03)

  **What to do**:
  - Enhance `revision_lookup.py`: after 8-keyword match fails, call LLM to classify feedback into action categories (regenerate/adjust_color/resize/reject/other)
  - Add max-revision=3 hard limit with clear error when exceeded
  - Persist actions: create `feedback_actions` table (id, image_id, feedback_text, matched_action, source=keyword|llm, created_at)
  - Migration for new table
  - Write tests for: keyword match, LLM fallback, max-revision enforcement

  **Must NOT do**:
  - Remove existing keyword matching (keep as fast path)
  - Allow infinite revision loops

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/revision_lookup.py` — current 8-keyword matching
  - `pipeline/adapters/openai_adapter.py` — LLM call pattern for fallback
  - `docs/PRD.md` — F-DEL-03 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_feedback_llm.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Keyword match (fast path)
    Tool: Bash
    Steps:
      1. Submit feedback "please regenerate this image"
      2. Assert action=regenerate, source=keyword
      3. Verify feedback_actions row created
    Expected Result: Keyword match succeeds, action persisted
    Evidence: .sisyphus/evidence/task-3f-keyword-match.txt

  Scenario: LLM fallback for complex feedback
    Tool: Bash
    Steps:
      1. Submit feedback "the color scheme doesn't match our spring collection vibe"
      2. Assert keyword match fails, LLM called
      3. Assert action=adjust_color, source=llm
    Expected Result: LLM classifies correctly, action persisted
    Evidence: .sisyphus/evidence/task-3f-llm-fallback.txt

  Scenario: Max revision exceeded
    Tool: Bash
    Steps:
      1. Submit 4th feedback for same image (3 already exist)
      2. Assert rejection with "Maximum revisions (3) exceeded"
    Expected Result: Hard limit enforced
    Evidence: .sisyphus/evidence/task-3f-max-revision.txt
  ```

  **Commit**: YES
  - Message: `feat(feedback): add LLM fallback + action persistence + max-revision limit (F-DEL-03)`
  - Files: `pipeline/layers/revision_lookup.py`, `pipeline/models/feedback_action.py`, `pipeline/db_migrate.py`, `tests/test_feedback_llm.py`

- [ ] 3g. Decision Log (F-DEL-04)

  **What to do**:
  - Create `pipeline/models/decision_log.py`: DecisionLog model (id, project_id, decision_type, input_summary, output_action, rationale, created_at, actor=system|human)
  - Log decisions at key pipeline points:
    - Gate pass/fail → log with rationale
    - Feedback action → log classification result
    - Hypothesis validation → log evidence summary
    - Delivery approval → log reviewer + decision
  - Endpoint: `GET /api/projects/{id}/decisions` — chronological decision history
  - Write a `log_decision()` utility function used by all layers

  **Must NOT do**:
  - Retroactively log past decisions (only new ones going forward)
  - Add complex querying/filtering (simple chronological list)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/qa_gate.py` — integration point for gate decisions
  - `pipeline/layers/revision_lookup.py` — integration point for feedback decisions
  - `docs/PRD.md` — F-DEL-04 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_decision_log.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Gate decision logged
    Tool: Bash
    Steps:
      1. Run pipeline with Gate 5 evaluation
      2. GET /api/projects/{id}/decisions
      3. Assert decision_log contains entry with decision_type="gate_evaluation"
    Expected Result: Gate decision logged with rationale
    Evidence: .sisyphus/evidence/task-3g-gate-log.txt

  Scenario: Decision log chronological order
    Tool: Bash (curl)
    Steps:
      1. Trigger multiple pipeline actions
      2. GET /api/projects/{id}/decisions
      3. Assert entries sorted by created_at ascending
    Expected Result: Chronological ordering maintained
    Evidence: .sisyphus/evidence/task-3g-chronological.txt
  ```

  **Commit**: YES
  - Message: `feat(decision): add decision log model and utility (F-DEL-04)`
  - Files: `pipeline/models/decision_log.py`, `pipeline/web/routes/decision_routes.py`, `pipeline/db_migrate.py`, `tests/test_decision_log.py`

- [ ] 3h. Listing Analysis Enhancement (F-DA-04) + Brand Profile Auto-Update

  **What to do**:
  - **Listing analysis**: Parse `bullet_points` into structured fields (feature, benefit, keyword) using LLM; populate `description` field from listing page data (currently always None)
  - **Brand profile auto-update**: After image review/approval, update brand_profile structured preferences (preferred_colors, preferred_styles) based on approved image tags — write back to `brand_profiles` table
  - Add `structured_bullets` JSON field to `top_asins` table
  - Write tests for bullet parsing and brand preference learning

  **Must NOT do**:
  - Fetch new listing data from Amazon (use existing stored data)
  - Override manually-set brand preferences (only auto-fill if field is NULL)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: 4a
  - **Blocked By**: 0a (brand merge), 1a (top_asin enrichment)

  **References**:
  - `pipeline/models/top_asin.py` — TopAsin model, bullet_points field
  - `pipeline/models/brand.py` — unified brand model (after 0a)
  - `pipeline/adapters/openai_adapter.py` — LLM call for parsing
  - `docs/PRD.md` — F-DA-04 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_listing_analysis.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Parse bullet points into structured format
    Tool: Bash
    Steps:
      1. Create top_asin with raw bullet_points="Waterproof design for outdoor use\nLightweight at only 200g"
      2. Run listing analysis
      3. Assert structured_bullets contains [{feature:"Waterproof",benefit:"outdoor use",keyword:"waterproof"}...]
    Expected Result: Structured parsing succeeds
    Evidence: .sisyphus/evidence/task-3h-bullet-parse.txt

  Scenario: Brand auto-update from approved tags
    Tool: Bash
    Steps:
      1. Approve 3 images all tagged COLOR=warm, STYLE=minimalist
      2. Check brand_profile.preferred_colors
      3. Assert "warm" added to preferences (only if field was NULL)
    Expected Result: Brand preferences auto-populated
    Evidence: .sisyphus/evidence/task-3h-brand-autoupdate.txt
  ```

  **Commit**: YES
  - Message: `feat(analysis): structured listing parsing + brand profile auto-update (F-DA-04)`
  - Files: `pipeline/layers/listing_analyzer.py`, `pipeline/models/top_asin.py`, `pipeline/models/brand.py`, `pipeline/db_migrate.py`, `tests/test_listing_analysis.py`

---

### Wave 4 — Integration & Stubs (After Wave 3)

- [ ] 4a. Integration Tests (Full Pipeline Smoke)

  **What to do**:
  - Create `tests/test_integration_l1l2.py` — end-to-end smoke test:
    1. Create project → verify event trigger fires
    2. Fetch ASINs → verify top_n=50, enriched data
    3. Run vision analysis → verify 5-layer tags + tag_assignment rows
    4. Generate brief → verify customer_brief data injected
    5. Fan-out generate → verify 3 engines attempted, partial success handled
    6. QA Gate 5 → verify composite scoring
    7. Delivery → verify ZIP created, status=delivered
    8. PDF report → verify signal light
  - Use test fixtures with mocked external APIs (OpenAI, Gemini)
  - Verify baseline 489 tests still pass: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`

  **Must NOT do**:
  - Call real external APIs
  - Modify existing 489 tests

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (sequential after Wave 3)
  - **Blocks**: Final Verification
  - **Blocked By**: ALL Wave 1-3 tasks

  **References**:
  - `tests/test_e2e_pipeline.py` — existing e2e pattern (but currently ignored)
  - All newly created test files from Waves 0-3

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_integration_l1l2.py -q` → PASS
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py` → ≥ 489 passed, 0 failed

  **QA Scenarios**:

  ```
  Scenario: Full pipeline integration
    Tool: Bash
    Steps:
      1. Run `PYTHONPATH=. .venv/bin/pytest tests/test_integration_l1l2.py -v`
      2. Assert all steps pass
      3. Run full test suite: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`
      4. Assert ≥ 489 passed, 0 failed
    Expected Result: Integration passes, no regression
    Evidence: .sisyphus/evidence/task-4a-integration.txt

  Scenario: Regression check
    Tool: Bash
    Steps:
      1. Run baseline test suite
      2. Compare pass count to baseline 489
      3. Assert no previously passing test now fails
    Expected Result: Zero regressions
    Evidence: .sisyphus/evidence/task-4a-regression.txt
  ```

  **Commit**: YES
  - Message: `test: add L1+L2 integration smoke tests`
  - Files: `tests/test_integration_l1l2.py`

- [ ] 4b. Helium10 / JungleScout Adapter Stubs (F-DRL-04)

  **What to do**:
  - Create `pipeline/adapters/helium10_adapter.py` — stub with interface:
    - `fetch_keyword_data(asin, marketplace)` → raises `NotImplementedError("Helium10 integration pending API key")`
    - `fetch_sales_estimate(asin)` → raises same
  - Create `pipeline/adapters/junglescout_adapter.py` — same pattern
  - Register both in `registry.py` with `available=False` flag
  - Document in code: required env vars, API endpoints, expected response shapes
  - Write tests verifying stubs raise correctly and are registered

  **Must NOT do**:
  - Implement actual API calls
  - Add API keys or credentials
  - Make any pipeline flow depend on these adapters

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with 4a, but 4a is more critical)
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: None (independent stubs)

  **References**:
  - `pipeline/adapters/registry.py` — adapter registration pattern
  - `pipeline/adapters/mock_adapter.py` — stub adapter pattern
  - `docs/PRD.md` — F-DRL-04 spec

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_adapter_stubs.py -q` → PASS

  **QA Scenarios**:

  ```
  Scenario: Helium10 stub raises NotImplementedError
    Tool: Bash
    Steps:
      1. Import helium10_adapter
      2. Call fetch_keyword_data("B08N5WRWNW", "US")
      3. Assert NotImplementedError raised with message containing "API key"
    Expected Result: Clear not-implemented error
    Evidence: .sisyphus/evidence/task-4b-helium10-stub.txt

  Scenario: Stubs registered in registry
    Tool: Bash
    Steps:
      1. Import registry
      2. Assert "helium10" in registry with available=False
      3. Assert "junglescout" in registry with available=False
    Expected Result: Both registered as unavailable
    Evidence: .sisyphus/evidence/task-4b-registry.txt
  ```

  **Commit**: YES
  - Message: `feat(adapters): add Helium10 + JungleScout stubs (F-DRL-04)`
  - Files: `pipeline/adapters/helium10_adapter.py`, `pipeline/adapters/junglescout_adapter.py`, `pipeline/adapters/registry.py`, `tests/test_adapter_stubs.py`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py`. Review all changed files for: `as any`/`@ts-ignore` (N/A for Python), empty excepts, print() in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
      Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Test edge cases: empty brand data, NULL customer_brief fields, fan-out partial failure. Save to `.sisyphus/evidence/final-qa/`.
      Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff (git log/diff). Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
      Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **0a**: `chore: validate test baseline 489 passed` - (no code changes)
- **0b**: `chore: check brand table data counts` - (no code changes)
- **1a**: `refactor(models): merge dual BrandProfile into unified model` - brand.py, brand_profile.py, all importers
- **1b**: `feat(brief): wire customer_brief data into brief generation` - brief_generator.py
- **1c**: `feat(amazon): expand top ASIN to 50 + enrich listing data` - amazon_data.py, competitor_listing model
- **1d**: `feat(vision): wire Gemini Vision adapter into main analysis flow` - orchestrator.py, vision_analyzer.py
- **2a**: `feat(fanout): add fan-out engine interface + mock engine` - fan_out_engine.py, mock_engine.py
- **2b**: `feat(fanout): add GPT-image-1 engine adapter` - gpt_image_engine.py
- **2c**: `feat(fanout): add Gemini Imagen engine adapter` - gemini_image_engine.py
- **2d**: `feat(vision): implement 5-layer tag analysis + tag_assignment persistence` - vision_analyzer.py, tags.py
- **2e**: `feat(qa): implement Gate 5 real evaluation logic` - qa_gate.py
- **2f**: `feat(hypothesis): add hypothesis model + CRUD` - hypothesis.py, web routes
- **2g**: `feat(ui): add annotation review interface` - review_tags.html
- **2h**: `feat(aplus): inject product context into storyboard generation` - aplus_generator.py
- **3a**: `feat(trigger): add event-driven pipeline trigger endpoint` - pipeline_trigger.py
- **3b**: `feat(tracking): add 14-day tracking scheduler + metrics table` - tracking_scheduler.py
- **3c**: `feat(delivery): fix paths + ZIP packaging + delivered status` - delivery.py
- **3d**: `feat(report): add PDF summary report with traffic-light scoring` - report_generator.py
- **3e**: `feat(marketing): add content marketing output generator` - content_marketing.py
- **3f**: `feat(feedback): add LLM fallback + persistence to feedback loop` - revision_lookup.py, feedback_handler.py
- **3g**: `feat(decision): add decision log + query endpoint` - decision_log.py
- **3h**: `feat(analysis): enhance price band + promo rhythm analysis` - price_analyzer.py, promo_analyzer.py
- **4a**: `test: add integration test suite for full pipeline` - test_integration.py
- **4b**: `feat(adapter): add Helium10/JungleScout adapter stubs` - helium10_adapter.py

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
# Expected: ≥489 passed, 0 failed

PYTHONPATH=. python -m pipeline.__main__ generate --engines mock
# Expected: exit 0, output files in data/exports/

grep -rn "from pipeline.models.brand import" --include="*.py" pipeline/
# Expected: 0 results (all migrated to brand_profile)
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass (≥489 + new tests)
- [ ] No dual BrandProfile references remain
- [ ] Fan-out mock engine produces output
- [ ] 5 tag layers in tag_assignment
- [ ] ZIP delivery at data/exports/
- [ ] PDF report generates
