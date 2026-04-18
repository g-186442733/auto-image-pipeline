# L2 分析决策层集成 + Superpower 改造

## TL;DR

> **Quick Summary**: 将4个已完成但未接入的分析模块接入 orchestrator.step_analyze，新建2个缺失模块，补充数据获取函数，**同时融入 Superpower 三件改造**：安装 obra/superpowers 框架、QA gate 改为 Goal-Driven LLM loop（自评+retry）、orchestrator 分析器并行化（ThreadPoolExecutor）。最后用 project_id=7 端到端真实验证。
>
> **Deliverables**:
>
> - orchestrator.py step_analyze 完整调用全部6个分析器 + brief_generator
> - 2个新模块: price_analyzer.py, promo_analyzer.py
> - 2个新 DB 模型: PriceAnalysis, PromoAnalysis
> - 2个新数据获取函数: fetch_reviews(), fetch_qa() in amazon_data.py
> - **obra/superpowers 框架安装到 opencode.json**
> - **qa_gate.py 重构为 Goal-Driven LLM loop + step_qa retry loop**
> - **orchestrator.py step_analyze 分析器并行执行（ThreadPoolExecutor）**
> - 集成测试覆盖全部新增调用链
> - project_id=7 端到端真实运行通过 + ImageBrief 写入 DB
>
> **Estimated Effort**: Medium-Large (3-4 天)
> **Parallel Execution**: YES - 3 waves (13 tasks + 4 final reviews)
> **Critical Path**: T1 → T2 → T4/T5 → T8 (brief wiring) → T13 (parallelization) → T9 (e2e)

---

## Context

### Original Request

老板要求完成 L2 阶段：将已编写但未集成的分析模块接入主流水线 orchestrator，补建缺失模块（价格带/推广节奏分析），写集成测试，用 project_id=7（Sony WH-1000XM5）端到端真实验证。**同时融入 Superpower 三件改造**（灵感来源：Karpathy CLAUDE.md 四原则 + obra/superpowers 框架）。

### Interview Summary

**Key Discussions**:

- 6个竞品分析模块全做（包括⑤价格带和⑥推广节奏）
- 要写测试
- 要用 project_id=7 端到端真实跑（会消耗 API 额度）
- 所有分析模块用 Gemini API (GOOGLE_API_KEY)
- **Superpower 决策（老板拍板：三件都做）**：
  - ① QA gate 从硬编码规则改成 Goal-Driven LLM loop（给 LLM 成功标准让它自评 + retry）
  - ② 安装 obra/superpowers 框架（TDD 强制、结构化调试、并行子 Agent）
  - ③ Orchestrator analyzer 并行化（vision/listing/review/qa 并行跑，不串行等待）

**Research Findings**:

- orchestrator step_analyze 当前只做 fetch_asin_detail → fetch_category_top → CompetitorListing(title only) → Vision 分析
- 4个孤岛模块（listing/review/qa/brief）代码完整、单元测试通过，但未接入 orchestrator
- amazon_data.py 缺少 fetch_reviews() 和 fetch_qa()
- brief_generator 输出 ImageBrief，slot_planner 已能从 DB 消费 ImageBrief
- 134 个现有测试全部通过

### Metis Review

**Identified Gaps** (addressed):

- fetch_reviews/fetch_qa 数据源未确定 → 默认走 Keepa Product API（reviews endpoint），如不可用则 mock stub
- 新模块 PriceAnalysis/PromoAnalysis DB 模型需新建 → 列入 T1
- 幂等性策略 → 采用 upsert（先删旧记录再插入）
- 部分分析器失败处理 → try/except per analyzer，log warning，继续后续分析
- brief_generator 是否自行持久化 → 需验证，orchestrator 确保结果写入 DB

---

## Work Objectives

### Core Objective

让 orchestrator.step_analyze 完整执行全部6种竞品分析 + brief 生成，**并行化分析器执行**，**将 QA gate 改为 Goal-Driven LLM loop + retry**，实现真正的一键自动化分析决策层。

### Concrete Deliverables

- `orchestrator.py` step_analyze 调用 listing/review/qa/price/promo analyzer + brief_generator
- `orchestrator.py` step_analyze 使用 ThreadPoolExecutor 并行执行分析器
- `orchestrator.py` step_qa 加入 retry loop（QA 不通过 → 带反馈重新生成 → 再 QA）
- `pipeline/layers/price_analyzer.py` — 新模块
- `pipeline/layers/promo_analyzer.py` — 新模块
- `pipeline/layers/qa_gate.py` — 重构为 Goal-Driven LLM loop（单次 LLM 调用替代6个硬编码检查）
- `pipeline/models/price_analysis.py` — 新 ORM 模型
- `pipeline/models/promo_analysis.py` — 新 ORM 模型
- `pipeline/layers/amazon_data.py` — 新增 fetch_reviews(), fetch_qa()
- `~/.config/opencode/opencode.json` — 添加 superpowers 插件
- 集成测试文件
- project_id=7 端到端运行通过

### Definition of Done

- [ ] `pytest tests/ -v` 全部通过（含新增测试），零回归
- [ ] `PYTHONPATH=. python -m pipeline.__main__ run --project-id 7` 完整执行无报错
- [ ] DB 中 project_id=7 的 ImageBrief、ReviewCluster、QAEntry、PriceAnalysis、PromoAnalysis 均有数据
- [ ] QA gate 使用 LLM 评分（非硬编码规则），QARecord.details 包含 LLM reasoning
- [ ] step_analyze 中多个分析器并行执行（通过日志时间戳可验证）

### Must Have

- 所有6个分析器结果写入 DB
- brief_generator 在 step_plan 之前执行，结果写入 ImageBrief
- 部分分析器失败不阻塞整体流水线（graceful degradation）
- 幂等性：重复运行同 project_id 采用 upsert 策略
- QA gate Goal-Driven：单次 LLM 调用传入 image + goal + brand_profile，返回 pass/fail + reasoning
- step_qa retry loop：QA fail → 带 LLM feedback 重新 step_generate → 再 QA（max 2 retries）
- 并行化：step_analyze 中 listing/review/qa analyzer 通过 ThreadPoolExecutor 并行执行
- DB 写操作在主线程执行（SQLite 线程安全约束）

### Must NOT Have (Guardrails)

- ❌ 不修改 slot_planner.py（已工作正常）
- ❌ 不改变现有4个孤岛模块的函数签名
- ❌ 不新增 orchestrator 步骤（所有分析器在 step_analyze 内，QA retry 在 step_qa 内）
- ❌ 不引入 asyncio（全项目同步代码，用 ThreadPoolExecutor）
- ❌ 不添加复杂熔断/背压逻辑（简单 max retry + log）
- ❌ 不写文档（只改代码 + 测试）
- ❌ 不用 `as any`（TypeScript 项目约束）
- ❌ 不用 `<style>` 内联 CSS

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES (pytest, 134 existing tests, 26 test files)
- **Automated tests**: YES (Tests-after — each task includes implementation + test)
- **Framework**: pytest
- **Baseline**: `pytest tests/ -v` must pass BEFORE any changes

### QA Policy

Every task includes agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend/Pipeline**: Use Bash — run pytest, run pipeline commands, check DB with sqlite3
- **API/Module**: Use Bash — import module in Python REPL, call function, verify output

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation, no dependencies):
├── T1:  New DB models (PriceAnalysis, PromoAnalysis) + register [quick]
├── T2:  Add fetch_reviews() + fetch_qa() to amazon_data.py [unspecified-high]
├── T3:  Wire listing_analyzer into step_analyze [quick]
├── T6:  Build price_analyzer module [quick]
├── T7:  Build promo_analyzer module [quick]
└── T11: Install obra/superpowers framework in opencode.json [quick]

Wave 2 (After Wave 1 — wiring + QA gate rewrite):
├── T4:  Wire review_analyzer into step_analyze (depends: T2) [quick]
├── T5:  Wire qa_analyzer into step_analyze (depends: T2) [quick]
├── T8:  Wire brief_generator into orchestrator (depends: T3, T4, T5) [unspecified-high]
└── T12: Rewrite qa_gate.py → Goal-Driven LLM loop + step_qa retry (independent) [deep]

Wave 3 (After ALL wiring — parallelization + E2E + regression):
├── T13: Orchestrator step_analyze parallelization (depends: T3, T4, T5, T8) [deep]
├── T9:  E2E real run with project_id=7 (depends: ALL T1-T8, T12, T13) [deep]
└── T10: Full regression test suite (depends: T9) [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: T2 → T4/T5 → T8 → T13 → T9 → T10 → F1-F4 → user okay
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 6 (Wave 1)
```

### Dependency Matrix

| Task | Depends On      | Blocks  |
| ---- | --------------- | ------- |
| T1   | —               | T6, T7  |
| T2   | —               | T4, T5  |
| T3   | —               | T8, T13 |
| T4   | T2              | T8      |
| T5   | T2              | T8      |
| T6   | T1              | T9      |
| T7   | T1              | T9      |
| T8   | T3, T4, T5      | T13, T9 |
| T9   | T6-T8, T12, T13 | T10     |
| T10  | T9              | F1-F4   |
| T11  | —               | —       |
| T12  | —               | T9      |
| T13  | T3, T4, T5, T8  | T9      |

### Agent Dispatch Summary

- **Wave 1**: 6 tasks — T1 → `quick`, T2 → `unspecified-high`, T3 → `quick`, T6 → `quick`, T7 → `quick`, T11 → `quick`
- **Wave 2**: 4 tasks — T4 → `quick`, T5 → `quick`, T8 → `unspecified-high`, T12 → `deep`
- **Wave 3**: 3 tasks — T13 → `deep`, T9 → `deep`, T10 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. New DB Models — PriceAnalysis + PromoAnalysis

  **What to do**:
  - Create `pipeline/models/price_analysis.py` with ORM model: id, project_id, asin, price_current, price_avg_30d, price_min_30d, price_max_30d, price_position (TEXT: budget/mid/premium), competitor_prices (JSON), created_at
  - Create `pipeline/models/promo_analysis.py` with ORM model: id, project_id, asin, has_coupon (BOOL), coupon_percent, has_lightning_deal (BOOL), deal_frequency_30d (INT), bsr_trend (JSON: list of {date, rank}), seasonal_pattern (TEXT), created_at
  - Register both in `pipeline/models/__init__.py` — add imports + add to `__all__`
  - Verify `create_all()` creates the new tables
  - Write unit tests: test model instantiation, test create_all creates tables

  **Must NOT do**:
  - Don't modify existing models (competitor_listing, review_cluster, qa_entry, image_brief)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T3, T6, T7)
  - **Blocks**: T6, T7 (they need model imports)
  - **Blocked By**: None

  **References**:
  - `pipeline/models/competitor_listing.py` — follow exact same SQLAlchemy pattern (Column, Integer, String, Text, DateTime, ForeignKey)
  - `pipeline/models/review_cluster.py` — pattern reference for JSON fields
  - `pipeline/models/__init__.py` — see how existing models are registered
  - `pipeline/layers/amazon_data.py:fetch_asin_detail()` — returns price, bsr_rank fields that price_analyzer will consume

  **Acceptance Criteria**:
  - [ ] `pipeline/models/price_analysis.py` exists, PriceAnalysis importable
  - [ ] `pipeline/models/promo_analysis.py` exists, PromoAnalysis importable
  - [ ] `from pipeline.models import PriceAnalysis, PromoAnalysis` works
  - [ ] `pytest tests/ -v` — zero regressions (134+ pass)

  **QA Scenarios**:

  ```
  Scenario: Models importable and DB tables created
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. python -c "from pipeline.models import PriceAnalysis, PromoAnalysis; print('OK')"
      3. python -c "from pipeline.models import Base, engine; Base.metadata.create_all(engine); import sqlite3; conn=sqlite3.connect('data/pipeline.db'); tables=[r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]; assert 'price_analysis' in tables; assert 'promo_analysis' in tables; print('Tables OK')"
    Expected Result: Both print 'OK' / 'Tables OK'
    Evidence: .sisyphus/evidence/task-1-models-import.txt

  Scenario: Existing tests unbroken
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate && pytest tests/ -v 2>&1 | tail -5
    Expected Result: 134+ passed, 0 failed
    Evidence: .sisyphus/evidence/task-1-regression.txt
  ```

  **Commit**: YES (Commit 1)
  - Message: `feat(models): add PriceAnalysis and PromoAnalysis DB models`
  - Files: `pipeline/models/price_analysis.py`, `pipeline/models/promo_analysis.py`, `pipeline/models/__init__.py`, `tests/test_new_models.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 2. Add fetch_reviews() + fetch_qa() to amazon_data.py

  **What to do**:
  - Add `fetch_reviews(asin: str, market: str = "us") -> list[dict]` to `pipeline/layers/amazon_data.py`
    - Each dict: {title, body, rating, date, verified_purchase}
    - Data source: Keepa Product API reviews endpoint (KEEPA_API_KEY in config.py)
    - If Keepa reviews unavailable, return mock data with 5 representative reviews (log warning)
  - Add `fetch_qa(asin: str, market: str = "us") -> list[dict]` to same file
    - Each dict: {question, answer, votes}
    - Data source: Keepa or mock stub
  - Write tests: test with mock responses, test fallback behavior

  **Must NOT do**:
  - Don't change existing function signatures (fetch_asin_detail, fetch_category_top)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T3, T6, T7) — actually can start in Wave 1 since no deps
  - **Blocks**: T4, T5
  - **Blocked By**: None

  **References**:
  - `pipeline/layers/amazon_data.py` — existing fetch_asin_detail() and fetch_category_top() patterns, KEEPA_API_KEY usage
  - `pipeline/config.py` — keepa_api_key location
  - Keepa API docs: https://keepa.com/#!discuss/t/product-api/116 — reviews endpoint

  **Acceptance Criteria**:
  - [ ] `from pipeline.layers.amazon_data import fetch_reviews, fetch_qa` works
  - [ ] Both functions return list[dict] with correct keys
  - [ ] `pytest tests/test_amazon_data.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Functions importable and return correct shape
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. python -c "from pipeline.layers.amazon_data import fetch_reviews, fetch_qa; r=fetch_reviews('B09XS7JWHH'); print(type(r), len(r)); q=fetch_qa('B09XS7JWHH'); print(type(q), len(q))"
    Expected Result: <class 'list'> with length > 0 for both
    Evidence: .sisyphus/evidence/task-2-fetch-shape.txt

  Scenario: Fallback mock works when Keepa unavailable
    Tool: Bash
    Steps:
      1. KEEPA_API_KEY="" python -c "from pipeline.layers.amazon_data import fetch_reviews; r=fetch_reviews('FAKE_ASIN'); print(len(r), type(r[0]))"
    Expected Result: Returns mock data (list of dicts), logs warning
    Evidence: .sisyphus/evidence/task-2-fallback.txt
  ```

  **Commit**: YES (Commit 2)
  - Message: `feat(amazon_data): add fetch_reviews and fetch_qa functions`
  - Files: `pipeline/layers/amazon_data.py`, `tests/test_amazon_data.py`
  - Pre-commit: `pytest tests/test_amazon_data.py -v`

- [ ] 3. Wire listing_analyzer into orchestrator.step_analyze

  **What to do**:
  - In `pipeline/orchestrator.py` step_analyze, after existing vision_analyzer call:
    - Import listing_analyzer.analyze_listing
    - Call `analyze_listing(asin, keepa_data)` → returns CompetitorListing
    - Wrap in try/except, log warning on failure, continue pipeline
    - Upsert: delete existing CompetitorListing for same (project_id, asin), then add new one
    - Store result in session
  - Write integration test: mock analyze_listing, verify orchestrator calls it, verify DB write

  **Must NOT do**:
  - Don't modify listing_analyzer.py signature
  - Don't add new orchestrator steps

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T2, T6, T7)
  - **Blocks**: T8
  - **Blocked By**: None

  **References**:
  - `pipeline/orchestrator.py` — step_analyze function, see how vision_analyzer is called (pattern to follow)
  - `pipeline/layers/listing_analyzer.py` — `analyze_listing(asin: str, keepa_data: Optional[dict]) -> CompetitorListing`
  - `pipeline/models/competitor_listing.py` — CompetitorListing ORM model fields

  **Acceptance Criteria**:
  - [ ] orchestrator.step_analyze calls listing_analyzer.analyze_listing
  - [ ] CompetitorListing written to DB after step_analyze
  - [ ] Failure in listing_analyzer doesn't crash pipeline
  - [ ] `pytest tests/ -v` — zero regressions

  **QA Scenarios**:

  ```
  Scenario: listing_analyzer called in step_analyze
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. grep -n "analyze_listing" pipeline/orchestrator.py
    Expected Result: At least one line with analyze_listing call inside step_analyze
    Evidence: .sisyphus/evidence/task-3-grep-listing.txt

  Scenario: Integration test passes
    Tool: Bash
    Steps:
      1. pytest tests/ -k "listing" -v 2>&1 | tail -10
    Expected Result: Test(s) passed
    Evidence: .sisyphus/evidence/task-3-test.txt
  ```

  **Commit**: YES (Commit 3)
  - Message: `feat(orchestrator): wire listing_analyzer into step_analyze`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_listing.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 4. Wire review_analyzer into step_analyze

  **What to do**:
  - In `orchestrator.py` `step_analyze`, after fetching reviews via `fetch_reviews(asin)` (from T2), call `review_analyzer.analyze_reviews(asin, reviews)`
  - Upsert `ReviewCluster` records (delete old by asin+project_id, insert new)
  - Wrap in try/except — log warning on failure, continue pipeline
  - Write test `tests/test_orchestrator_review.py`: mock `fetch_reviews` + `analyze_reviews`, assert DB rows created

  **Must NOT do**:
  - Change review_analyzer.py signature
  - Skip the try/except partial-failure handling

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T5)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8
  - **Blocked By**: T2

  **References**:
  - `pipeline/orchestrator.py` — step_analyze function, follow vision_analyzer wiring pattern
  - `pipeline/layers/review_analyzer.py` — `analyze_reviews(asin, reviews) -> List[ReviewCluster]`
  - T3 wiring pattern for listing_analyzer — same upsert + try/except pattern

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_orchestrator_review.py -v` → PASS

  **QA Scenarios**:

  ```
  Scenario: review_analyzer called in step_analyze
    Tool: Bash
    Steps:
      1. grep -n "analyze_reviews" pipeline/orchestrator.py
    Expected Result: At least one call to analyze_reviews inside step_analyze
    Evidence: .sisyphus/evidence/task-4-grep-review.txt

  Scenario: Test passes
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate && pytest tests/test_orchestrator_review.py -v
    Expected Result: All tests pass
    Evidence: .sisyphus/evidence/task-4-test.txt
  ```

  **Commit**: YES (Commit 4)
  - Message: `feat(orchestrator): wire review_analyzer into step_analyze`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_review.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 5. Wire qa_analyzer into step_analyze

  **What to do**:
  - In `orchestrator.py` `step_analyze`, after fetching QA via `fetch_qa(asin)` (from T2), call `qa_analyzer.analyze_qa(asin, qa_pairs)`
  - Upsert `QAEntry` records (delete old by asin+project_id, insert new)
  - Wrap in try/except — log warning on failure, continue pipeline
  - Write test `tests/test_orchestrator_qa.py`: mock `fetch_qa` + `analyze_qa`, assert DB rows created

  **Must NOT do**:
  - Change qa_analyzer.py signature
  - Skip the try/except partial-failure handling

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T4)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8
  - **Blocked By**: T2

  **References**:
  - `pipeline/orchestrator.py` — step_analyze function
  - `pipeline/layers/qa_analyzer.py` — `analyze_qa(asin, qa_pairs) -> List[QAEntry]`
  - T3/T4 wiring pattern — same upsert + try/except

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_orchestrator_qa.py -v` → PASS

  **QA Scenarios**:

  ```
  Scenario: qa_analyzer called in step_analyze
    Tool: Bash
    Steps:
      1. grep -n "analyze_qa" pipeline/orchestrator.py
    Expected Result: At least one call to analyze_qa inside step_analyze
    Evidence: .sisyphus/evidence/task-5-grep-qa.txt

  Scenario: Test passes
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate && pytest tests/test_orchestrator_qa.py -v
    Expected Result: All tests pass
    Evidence: .sisyphus/evidence/task-5-test.txt
  ```

  **Commit**: YES (Commit 5)
  - Message: `feat(orchestrator): wire qa_analyzer into step_analyze`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_qa.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 6. Build price_analyzer module

  **What to do**:
  - Create `pipeline/layers/price_analyzer.py` with function `analyze_price(asin: str, keepa_data: dict, category_benchmarks: list) -> PriceAnalysis`
  - Pure computation — NO LLM call. Calculate: price_percentile, price_vs_avg_ratio, price_band (budget/mid/premium/luxury based on category distribution)
  - Create `pipeline/models/price_analysis.py` — ORM model: id, asin, current_price, avg_category_price, price_percentile, price_band, project_id, created_at
  - Register model in `pipeline/models/__init__.py`
  - Write test `tests/test_price_analyzer.py`: unit test with mock keepa data

  **Must NOT do**:
  - Use LLM/Gemini for price calculation — pure math only
  - Change any existing model files

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T2, T3, T7)
  - **Parallel Group**: Wave 1
  - **Blocks**: T9
  - **Blocked By**: None

  **References**:
  - `pipeline/models/competitor_listing.py` — ORM model pattern (15 lines)
  - `pipeline/layers/listing_analyzer.py` — module structure pattern
  - `pipeline/layers/amazon_data.py:fetch_category_top()` — returns AmazonBenchmark with price field

  **Acceptance Criteria**:
  - [ ] `pipeline/layers/price_analyzer.py` exists
  - [ ] `pipeline/models/price_analysis.py` exists
  - [ ] `pytest tests/test_price_analyzer.py -v` → PASS

  **QA Scenarios**:

  ```
  Scenario: price_analyzer returns correct price_band
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. python -c "from pipeline.layers.price_analyzer import analyze_price; r = analyze_price('B09XS7JWHH', {'price': 348}, [{'price': 200}, {'price': 300}, {'price': 400}]); print(r.price_band, r.price_percentile)"
    Expected Result: Prints a valid price_band (e.g. "mid" or "premium") and a float percentile
    Evidence: .sisyphus/evidence/task-6-price-calc.txt

  Scenario: Test passes
    Tool: Bash
    Steps:
      1. pytest tests/test_price_analyzer.py -v
    Expected Result: All tests pass
    Evidence: .sisyphus/evidence/task-6-test.txt
  ```

  **Commit**: YES (Commit 6)
  - Message: `feat(analyze): add price_analyzer module with PriceAnalysis model`
  - Files: `pipeline/layers/price_analyzer.py`, `pipeline/models/price_analysis.py`, `pipeline/models/__init__.py`, `tests/test_price_analyzer.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 7. Build promo_analyzer module

  **What to do**:
  - Create `pipeline/layers/promo_analyzer.py` with function `analyze_promo(asin: str, keepa_data: dict) -> PromoAnalysis`
  - Pure computation — NO LLM call. Calculate from Keepa history: promo_frequency (deals per year), avg_discount_pct, last_promo_date, promo_pattern (e.g. "seasonal", "frequent", "rare")
  - Create `pipeline/models/promo_analysis.py` — ORM model: id, asin, promo_frequency, avg_discount_pct, last_promo_date, promo_pattern, project_id, created_at
  - Register model in `pipeline/models/__init__.py`
  - Write test `tests/test_promo_analyzer.py`: unit test with mock keepa data

  **Must NOT do**:
  - Use LLM/Gemini — pure math only
  - Change any existing model files

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1, T2, T3, T6)
  - **Parallel Group**: Wave 1
  - **Blocks**: T9
  - **Blocked By**: None

  **References**:
  - `pipeline/models/price_analysis.py` (T6) — sibling ORM model pattern
  - `pipeline/layers/price_analyzer.py` (T6) — sibling module pattern
  - Keepa data structure: dict with `priceHistory` array of `{timestamp, price}` entries

  **Acceptance Criteria**:
  - [ ] `pipeline/layers/promo_analyzer.py` exists
  - [ ] `pipeline/models/promo_analysis.py` exists
  - [ ] `pytest tests/test_promo_analyzer.py -v` → PASS

  **QA Scenarios**:

  ```
  Scenario: promo_analyzer returns valid analysis
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. python -c "from pipeline.layers.promo_analyzer import analyze_promo; r = analyze_promo('B09XS7JWHH', {'priceHistory': [{'timestamp': 1700000000, 'price': 348}, {'timestamp': 1710000000, 'price': 278}]}); print(r.promo_pattern, r.avg_discount_pct)"
    Expected Result: Prints a valid promo_pattern string and a numeric discount percentage
    Evidence: .sisyphus/evidence/task-7-promo-calc.txt

  Scenario: Test passes
    Tool: Bash
    Steps:
      1. pytest tests/test_promo_analyzer.py -v
    Expected Result: All tests pass
    Evidence: .sisyphus/evidence/task-7-test.txt
  ```

  **Commit**: YES (Commit 7)
  - Message: `feat(analyze): add promo_analyzer module with PromoAnalysis model`
  - Files: `pipeline/layers/promo_analyzer.py`, `pipeline/models/promo_analysis.py`, `pipeline/models/__init__.py`, `tests/test_promo_analyzer.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 8. Wire brief_generator into orchestrator (new step or end of step_analyze)

  **What to do**:
  - After all analyzers complete in `step_analyze`, call `brief_generator.generate_brief(project_id, competitor_listing, review_clusters, qa_entries)`
  - Pass the collected analysis results from T3 (listing), T4 (reviews), T5 (QA)
  - If any upstream analyzer failed (partial failure), pass None for that input — brief_generator should handle gracefully
  - Upsert ImageBrief records
  - Write test `tests/test_orchestrator_brief.py`: mock all upstream + generate_brief, assert ImageBrief rows created

  **Must NOT do**:
  - Change brief_generator.py signature
  - Create a new orchestrator step — keep it at end of step_analyze
  - Skip passing partial results when some analyzers failed

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential after T4, T5)
  - **Blocks**: T9
  - **Blocked By**: T3, T4, T5

  **References**:
  - `pipeline/layers/brief_generator.py` — `generate_brief(project_id, competitor_listing, review_clusters, qa_entries, session=None) -> ImageBrief`
  - `pipeline/orchestrator.py` — step_analyze, after all analyzer calls
  - `pipeline/models/image_brief.py` — ImageBrief ORM model
  - `pipeline/layers/slot_planner.py` — consumes ImageBrief (downstream, don't modify)

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_orchestrator_brief.py -v` → PASS
  - [ ] brief_generator called after listing+review+qa analyzers in orchestrator

  **QA Scenarios**:

  ```
  Scenario: brief_generator wired after analyzers
    Tool: Bash
    Steps:
      1. grep -n "generate_brief" pipeline/orchestrator.py
    Expected Result: Call to generate_brief in step_analyze, after analyzer calls
    Evidence: .sisyphus/evidence/task-8-grep-brief.txt

  Scenario: Test passes
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate && pytest tests/test_orchestrator_brief.py -v
    Expected Result: All tests pass
    Evidence: .sisyphus/evidence/task-8-test.txt
  ```

  **Commit**: YES (Commit 8)
  - Message: `feat(orchestrator): wire brief_generator after all analyzers in step_analyze`
  - Files: `pipeline/orchestrator.py`, `tests/test_orchestrator_brief.py`
  - Pre-commit: `pytest tests/ -v`

- [ ] 9. E2E real run with project_id=7 (Sony WH-1000XM5)

     **What to do**:
  - Run the full pipeline end-to-end: `PYTHONPATH=. python -m pipeline.__main__ run --project-id 7`
  - This will consume real API credits (Gemini, Keepa, Amazon scraper)
  - Verify all new DB tables populated: CompetitorListing, ReviewCluster, QAEntry, ImageBrief, PriceAnalysis, PromoAnalysis
  - Check pipeline.log for errors
  - Capture evidence of successful run

  **Must NOT do**:
  - Use mocks — this is the REAL run
  - Modify any code — just run and observe

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after all implementation)
  - **Blocks**: T10
  - **Blocked By**: T1, T2, T3, T4, T5, T6, T7, T8

  **References**:
  - `pipeline/__main__.py` — CLI entry point
  - `data/pipeline.db` — SQLite database to inspect after run

  **Acceptance Criteria**:
  - [ ] Pipeline completes without fatal errors
  - [ ] All 6 analysis tables have data for project_id=7
  - [ ] ImageBrief records exist for project_id=7

  **QA Scenarios**:

  ```
  Scenario: Full pipeline E2E
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. PYTHONPATH=. python -m pipeline.__main__ run --project-id 7 2>&1 | tee .sisyphus/evidence/task-9-e2e-output.txt
    Expected Result: Pipeline completes, no fatal errors in output
    Evidence: .sisyphus/evidence/task-9-e2e-output.txt

  Scenario: DB tables populated
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. python -c "
  from pipeline.models import get_session, CompetitorListing, ReviewCluster, QAEntry, PriceAnalysis, PromoAnalysis
  from pipeline.models.image_brief import ImageBrief
  s = get_session()
  for M in [CompetitorListing, ReviewCluster, QAEntry, PriceAnalysis, PromoAnalysis, ImageBrief]:
    n = s.query(M).filter_by(project_id=7).count()
    print(f'{M.__name__}: {n} rows')
  " 2>&1 | tee .sisyphus/evidence/task-9-db-check.txt
    Expected Result: All 6 models show >0 rows for project_id=7
    Evidence: .sisyphus/evidence/task-9-db-check.txt
  ```

  **Commit**: NO (observation only, no code changes)

- [ ] 10. Full regression — all existing + new tests pass

  **What to do**:
  - Run `pytest tests/ -v` and verify ALL tests pass (existing 134 + new tests from T1-T8)
  - Fix any regressions introduced by the integration work
  - Target: 150+ tests, 0 failures

  **Must NOT do**:
  - Delete or skip existing tests to make suite pass
  - Introduce `pytest.mark.skip` on failing tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after T9)
  - **Blocks**: F1-F4
  - **Blocked By**: T9

  **References**:
  - `tests/` directory — all test files
  - Previous baseline: 134 tests pass

  **Acceptance Criteria**:
  - [ ] `pytest tests/ -v` → ALL PASS, 0 failures
  - [ ] Total test count ≥ 150

  **QA Scenarios**:

  ```
  Scenario: Full test suite
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. pytest tests/ -v 2>&1 | tee .sisyphus/evidence/task-10-regression.txt
      3. pytest tests/ -v 2>&1 | tail -5
    Expected Result: All tests pass, 0 failures, count >= 150
    Evidence: .sisyphus/evidence/task-10-regression.txt
  ```

  **Commit**: YES (Commit 9 — if any fixes needed)
  - Message: `fix(tests): resolve regressions from L2 integration`
  - Files: any files that needed fixing
  - Pre-commit: `pytest tests/ -v`

- [ ] 11. Install obra/superpowers framework (OpenCode plugin)

  **What to do**:
  - Edit `~/.config/opencode/opencode.json` to add `"superpowers@git+https://github.com/obra/superpowers.git"` to the `plugin` array
  - Restart OpenCode session to activate the plugin
  - Verify skills are loaded: check that TDD, systematic-debugging, verification-before-completion skills are available

  **Must NOT do**:
  - Modify any project source files — this is config-only
  - Remove existing plugins from opencode.json
  - Change any other opencode settings

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T2)
  - **Blocks**: None (enables workflow discipline for subsequent tasks)
  - **Blocked By**: None

  **References**:
  - `~/.config/opencode/opencode.json` — current plugin config (add to existing `plugin` array)
  - GitHub: `https://github.com/obra/superpowers` — README for install instructions
  - Framework is pure Markdown skill files, zero code dependencies

  **Acceptance Criteria**:
  - [ ] `opencode.json` contains superpowers plugin entry
  - [ ] OpenCode recognizes TDD skill (available in skill list)
  - [ ] No existing plugins removed or broken

  **QA Scenarios**:

  ```
  Scenario: Verify plugin installation
    Tool: Bash
    Steps:
      1. cat ~/.config/opencode/opencode.json | python3 -m json.tool
      2. Verify "superpowers" appears in the plugin array
      3. grep -c "superpowers" ~/.config/opencode/opencode.json
    Expected Result: Valid JSON, superpowers entry present, grep returns 1
    Evidence: .sisyphus/evidence/task-11-superpowers-install.txt
  ```

  **Commit**: NO (config file outside project repo)

- [ ] 12. Rewrite qa_gate.py → Goal-Driven LLM QA loop

  **What to do**:
  - **Phase A — Replace 6 hardcoded checks with single LLM call**:
    - Create new function `llm_qa_evaluate(image_path, goal_brief, brand_profile, expected_text) -> QAResult` in `qa_gate.py`
    - LLM receives: the generated image + slot's goal/brief from ImageBrief + project's brand_profile from Project model + expected_text from PromptAsset
    - LLM returns structured JSON: `{"pass": bool, "score": 0-100, "issues": [{"category": str, "severity": str, "description": str}], "reasoning": str}`
    - Use Gemini API (consistent with other analyzers), model `gemini-2.0-flash`
    - Keep old `run_qa_checks()` renamed to `run_qa_checks_legacy()` for fallback
    - New `run_qa_checks(slot_plan_id)` calls `llm_qa_evaluate` and writes single QARecord with full LLM reasoning in `details` field
  - **Phase B — Add retry loop to orchestrator step_qa**:
    - In `orchestrator.py` `step_qa()`: if QA fails (score < 70), extract LLM feedback from QARecord.details
    - Call `step_generate()` for that specific slot only, passing LLM feedback as additional context to prompt_engine
    - Re-run QA on regenerated image
    - Max 2 retries per slot (3 total attempts). After max retries, log warning and continue
    - Track retry count in SlotPlan or QARecord
  - **Phase C — Tests**:
    - Unit test for `llm_qa_evaluate` with mocked Gemini response
    - Unit test for retry loop logic (mock qa_gate to fail then pass)
    - Test that legacy function still works

  **Must NOT do**:
  - Delete legacy QA functions — rename with `_legacy` suffix for fallback
  - Use OpenAI for QA — use Gemini API to stay consistent
  - Make retry loop infinite — hard cap at 2 retries
  - Block entire pipeline on single slot QA failure — partial failure is OK

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Reason: Complex multi-phase refactor touching qa_gate.py + orchestrator.py + tests, needs careful reasoning about retry state management

  **Parallelization**:
  - **Can Run In Parallel**: YES (within Wave 2)
  - **Parallel Group**: Wave 2 (with T3, T4, T5, T8)
  - **Blocks**: T10, T13
  - **Blocked By**: T1 (models), T2 (amazon_data)

  **References**:

  **Pattern References**:
  - `pipeline/layers/qa_gate.py` — current 6 hardcoded checks, `run_qa_checks(slot_plan_id)` main entry at ~line 90
  - `pipeline/layers/vision_analyzer.py` — Gemini API call pattern (model init, generate_content, JSON parse)
  - `pipeline/orchestrator.py:220-243` — current `step_qa()` implementation (loop over SlotPlans, call run_qa_checks)

  **API/Type References**:
  - `pipeline/models/qa_record.py` — QARecord model: slot_plan_id, check_name, score, passed, details
  - `pipeline/models/image_brief.py` — ImageBrief: brief_json contains goal/requirements per slot
  - `pipeline/models/__init__.py` — Project model: has brand_profile field
  - `pipeline/layers/prompt_engine.py` — how prompts are generated (need to pass retry feedback here)

  **External References**:
  - Gemini API: `google.generativeai` — same pattern as listing_analyzer.py

  **Acceptance Criteria**:
  - [ ] `llm_qa_evaluate()` returns structured QAResult with pass/fail, score, issues, reasoning
  - [ ] `run_qa_checks()` calls LLM instead of 6 hardcoded checks
  - [ ] `run_qa_checks_legacy()` preserved and callable
  - [ ] `step_qa()` retries failed slots up to 2 times with LLM feedback
  - [ ] After max retries, pipeline continues (doesn't crash)
  - [ ] New tests: ≥ 5 tests covering LLM QA + retry logic
  - [ ] `pytest tests/ -k qa` → all pass

  **QA Scenarios**:

  ```
  Scenario: LLM QA evaluates a generated image
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. PYTHONPATH=. python -c "
         from pipeline.layers.qa_gate import llm_qa_evaluate
         result = llm_qa_evaluate('output/7/delivery/slot_1.png', {'goal': 'test'}, None, None)
         print(f'pass={result[\"pass\"]}, score={result[\"score\"]}')
         print(f'issues={len(result.get(\"issues\", []))}')
         assert 'pass' in result and 'score' in result and 'reasoning' in result
         print('PASS')
         "
    Expected Result: Structured result with pass, score, reasoning fields; no crash
    Evidence: .sisyphus/evidence/task-12-llm-qa-eval.txt

  Scenario: Legacy QA still works
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. PYTHONPATH=. python -c "
         from pipeline.layers.qa_gate import run_qa_checks_legacy
         print('Legacy function exists and is callable')
         print('PASS')
         "
    Expected Result: No ImportError, function is accessible
    Evidence: .sisyphus/evidence/task-12-legacy-qa.txt

  Scenario: Unit tests pass
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. pytest tests/ -k qa -v 2>&1 | tee .sisyphus/evidence/task-12-tests.txt
    Expected Result: All QA-related tests pass, ≥ 5 new tests
    Evidence: .sisyphus/evidence/task-12-tests.txt
  ```

  **Commit**: YES (Commit 9)
  - Message: `feat(qa): replace hardcoded QA checks with Goal-Driven LLM evaluation + retry loop`
  - Files: `pipeline/layers/qa_gate.py`, `pipeline/orchestrator.py`, `tests/test_qa_gate.py`
  - Pre-commit: `pytest tests/ -k qa -v`

- [ ] 13. Orchestrator step_analyze parallelization (ThreadPoolExecutor)

  **What to do**:
  - **Phase A — Parallel data fetching in step_analyze**:
    - Use `concurrent.futures.ThreadPoolExecutor(max_workers=5)` in `step_analyze()`
    - Phase 1 parallel: `fetch_asin_detail()` + `fetch_category_top()` (2 independent Keepa API calls)
    - Phase 2 parallel: Vision benchmark loop — submit each competitor image analysis to thread pool instead of sequential loop
    - Phase 3 parallel: After T3/T4/T5 wiring done, `listing_analyzer` + `review_analyzer` + `qa_analyzer` (3 independent Gemini calls)
  - **Phase B — Thread-safe DB writes**:
    - Worker functions return results only (no `session.add()` in threads)
    - Main thread collects all futures via `as_completed()`, then does all DB writes sequentially
    - Wrap in try/except per future to handle partial failures gracefully
  - **Phase C — Tests**:
    - Test that parallelization produces same results as sequential (mock external APIs)
    - Test partial failure handling (one analyzer fails, others succeed)
    - Test thread count doesn't exceed max_workers

  **Must NOT do**:
  - Use asyncio — entire codebase is synchronous, stay with ThreadPoolExecutor
  - Do DB writes inside worker threads — SQLite is not thread-safe for writes
  - Call `genai.configure()` inside threads — call once in main thread before spawning
  - Make step_plan/step_generate/step_qa parallel — they have sequential dependencies
  - Break existing sequential fallback — add `PARALLEL_ANALYZE=True` config flag, default True

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Reason: Concurrency refactor requiring careful thread-safety reasoning around SQLite and Gemini global state

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential — needs all analyzers wired first)
  - **Blocks**: T10
  - **Blocked By**: T3, T4, T5, T8, T12

  **References**:

  **Pattern References**:
  - `pipeline/orchestrator.py` — entire `step_analyze()` function (~line 50-130): current sequential flow
  - `pipeline/layers/vision_analyzer.py` — `analyze_competitor_images()`: current sequential benchmark loop
  - `pipeline/layers/amazon_data.py` — `fetch_asin_detail()`, `fetch_category_top()`: independent API calls

  **API/Type References**:
  - `concurrent.futures.ThreadPoolExecutor` — Python stdlib, `submit()`, `as_completed()`, `result()`
  - `pipeline/config.py` — where to add `PARALLEL_ANALYZE` flag

  **External References**:
  - Python docs: `concurrent.futures` — ThreadPoolExecutor usage pattern

  **Acceptance Criteria**:
  - [ ] `step_analyze()` uses ThreadPoolExecutor for data fetching and analyzer calls
  - [ ] All DB writes happen in main thread only
  - [ ] `PARALLEL_ANALYZE` config flag exists, defaults to True
  - [ ] Setting `PARALLEL_ANALYZE=False` falls back to sequential execution
  - [ ] Partial failure: if one analyzer throws, others still complete and save
  - [ ] New tests: ≥ 4 tests covering parallel execution + partial failure
  - [ ] `pytest tests/ -k parallel -v` → all pass
  - [ ] Wall-clock time for step_analyze measurably reduced (logged)

  **QA Scenarios**:

  ```
  Scenario: Parallel step_analyze completes successfully
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. PYTHONPATH=. python -c "
         from pipeline.orchestrator import step_analyze
         from pipeline.models import Session, Project
         s = Session()
         p = s.query(Project).get(7)
         import time; t0 = time.time()
         step_analyze(p, s)
         elapsed = time.time() - t0
         print(f'step_analyze completed in {elapsed:.1f}s')
         print('PASS')
         " 2>&1 | tee .sisyphus/evidence/task-13-parallel.txt
    Expected Result: step_analyze completes without error, time logged
    Evidence: .sisyphus/evidence/task-13-parallel.txt

  Scenario: Partial failure — one analyzer fails, others succeed
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. pytest tests/ -k "parallel and partial_failure" -v 2>&1 | tee .sisyphus/evidence/task-13-partial-failure.txt
    Expected Result: Test passes — pipeline continues despite one analyzer error
    Evidence: .sisyphus/evidence/task-13-partial-failure.txt

  Scenario: Sequential fallback works
    Tool: Bash
    Steps:
      1. cd ~/Projects/auto-image-pipeline && source .venv/bin/activate
      2. PYTHONPATH=. PARALLEL_ANALYZE=false python -c "
         from pipeline.config import PARALLEL_ANALYZE
         assert PARALLEL_ANALYZE == False, 'Flag not respected'
         print('Sequential fallback flag works')
         print('PASS')
         "
    Expected Result: Config flag correctly disables parallelization
    Evidence: .sisyphus/evidence/task-13-sequential-fallback.txt
  ```

  **Commit**: YES (Commit 10)
  - Message: `perf(orchestrator): parallelize step_analyze with ThreadPoolExecutor`
  - Files: `pipeline/orchestrator.py`, `pipeline/config.py`, `tests/test_parallel.py`
  - Pre-commit: `pytest tests/ -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run `pytest tests/ -v`. Review all changed files for: empty catches, bare except, unused imports, print statements in prod code. Check AI slop: excessive comments, over-abstraction, generic names. Verify all new modules follow listing_analyzer.py pattern.
      Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
      Start from clean state. Run `PYTHONPATH=. python -m pipeline.__main__ run --project-id 7`. Verify all DB tables have data for project_id=7. Check pipeline.log for errors/warnings. Capture output.
      Output: `Pipeline [PASS/FAIL] | DB Tables [N/N populated] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: read "What to do", read actual diff (git diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance (slot_planner untouched, no signature changes, no new orchestrator steps).
      Output: `Tasks [N/N compliant] | Scope [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

| Commit | Tasks   | Message                                                                      | Test Command                          |
| ------ | ------- | ---------------------------------------------------------------------------- | ------------------------------------- |
| 1      | T1      | `feat(models): add PriceAnalysis and PromoAnalysis DB models`                | `pytest tests/ -v`                    |
| 2      | T2      | `feat(amazon_data): add fetch_reviews and fetch_qa functions`                | `pytest tests/test_amazon_data.py -v` |
| 3      | T3      | `feat(orchestrator): wire listing_analyzer into step_analyze`                | `pytest tests/ -v`                    |
| 4      | T4, T5  | `feat(orchestrator): wire review_analyzer and qa_analyzer into step_analyze` | `pytest tests/ -v`                    |
| 5      | T6, T7  | `feat(layers): add price_analyzer and promo_analyzer modules`                | `pytest tests/ -v`                    |
| 6      | T8      | `feat(orchestrator): wire brief_generator and complete analysis chain`       | `pytest tests/ -v`                    |
| 7      | T9, T10 | `test(e2e): verify full pipeline with project_id=7`                          | `pytest tests/ -v`                    |
| 8      | T11     | Config only — no commit (opencode.json outside repo)                         | N/A                                   |
| 9      | T12     | `feat(qa): replace hardcoded QA checks with Goal-Driven LLM eval + retry`    | `pytest tests/ -k qa -v`              |
| 10     | T13     | `perf(orchestrator): parallelize step_analyze with ThreadPoolExecutor`       | `pytest tests/ -v`                    |

---

## Success Criteria

### Verification Commands

```bash
# Baseline — all existing tests pass
pytest tests/ -v  # Expected: 134+ tests PASSED

# E2E pipeline run
PYTHONPATH=. python -m pipeline.__main__ run --project-id 7  # Expected: exit 0

# DB verification
sqlite3 data/pipeline.db "SELECT COUNT(*) FROM review_cluster WHERE project_id=7;"  # Expected: > 0
sqlite3 data/pipeline.db "SELECT COUNT(*) FROM qa_entry WHERE project_id=7;"  # Expected: > 0
sqlite3 data/pipeline.db "SELECT COUNT(*) FROM image_brief WHERE project_id=7;"  # Expected: > 0
sqlite3 data/pipeline.db "SELECT COUNT(*) FROM price_analysis WHERE project_id=7;"  # Expected: > 0
sqlite3 data/pipeline.db "SELECT COUNT(*) FROM promo_analysis WHERE project_id=7;"  # Expected: > 0

# QA Gate LLM verification
PYTHONPATH=. python -c "from pipeline.layers.qa_gate import llm_qa_evaluate; print('LLM QA function exists')"  # Expected: no error

# Parallelization verification
PYTHONPATH=. python -c "from pipeline.config import PARALLEL_ANALYZE; assert PARALLEL_ANALYZE == True; print('Parallel enabled')"

# Superpowers plugin
grep superpowers ~/.config/opencode/opencode.json  # Expected: match found
```

### Final Checklist

- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass (134 existing + new ≥ 160 total)
- [ ] project_id=7 full pipeline run completes
- [ ] All 5 new DB tables populated for project_id=7
- [ ] QA gate uses LLM evaluation (not hardcoded checks)
- [ ] QA retry loop works (max 2 retries per slot)
- [ ] step_analyze runs analyzers in parallel (ThreadPoolExecutor)
- [ ] PARALLEL_ANALYZE=False falls back to sequential
- [ ] obra/superpowers plugin installed in opencode.json
