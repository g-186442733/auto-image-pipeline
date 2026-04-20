# Remove Mock Data Fallback from amazon_data.py

## TL;DR

> **Quick Summary**: 删除 `amazon_data.py` 中 `fetch_reviews()` 和 `fetch_qa()` 的 mock fallback 机制，API 失败时直接抛出异常，防止假数据污染客户真实内容。
>
> **Deliverables**:
>
> - `amazon_data.py` 改为 API 失败时 raise 异常
> - 删除 `_mock_reviews()` 和 `_mock_qa()` 两个函数
> - 更新所有受影响测试
>
> **Estimated Effort**: Quick
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Task 1 → Task 2 → Final Verification

---

## Context

### Original Request

老板发现项目中 `amazon_data.py` 的 `fetch_reviews()` 和 `fetch_qa()` 在 Keepa API 失败时静默返回 mock 数据（如 "Great product #1"），这些假数据会被下游 Gemini 分析消费，导致生成的设计 brief 不真实。要求 API 失败时直接报错中断。

### 当前行为（问题）

```
Keepa API 失败 → logger.warning → return _mock_reviews(asin)  # 静默返回假数据
```

### 期望行为

```
Keepa API 失败 → raise KeepaDataError("fetch_reviews failed for {asin}: {reason}")
```

---

## Work Objectives

### Core Objective

确保 `fetch_reviews()` 和 `fetch_qa()` 在 API 失败时抛出异常，绝不返回假数据。

### Concrete Deliverables

- `pipeline/layers/amazon_data.py` — 删除 `_mock_reviews()`、`_mock_qa()`，失败时 raise
- `tests/test_amazon_data.py` — 重写 fallback 测试为"验证抛异常"
- 其他测试文件中 patch 这两个函数的地方 — 确认不受影响（它们 patch 的是成功路径）

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py` → 全部 PASS

### Must Have

- API 失败（网络错误、无 key、无数据、空结果）→ 抛出异常
- 删除 `_mock_reviews()` 和 `_mock_qa()` 函数
- 所有现有测试保持 PASS

### Must NOT Have (Guardrails)

- ❌ 不引入新的 pip 依赖
- ❌ 不修改 `fetch_asin_detail()`、`fetch_category_top()`、`scrape_listing_images()` 等其他函数
- ❌ 不碰 `helium10_adapter.py`
- ❌ 不碰 `mock_adapter.py` / `mock_engine.py`（开发工具保留）
- ❌ 不改 DB schema

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES
- **Automated tests**: YES (tests-after — 修改现有测试)
- **Framework**: pytest
- **Test command**: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately):
├── Task 1: 修改 amazon_data.py — 删 mock fallback，失败 raise [quick]
└── (无其他并行任务，此为基础改动)

Wave 2 (After Wave 1):
├── Task 2: 更新 test_amazon_data.py — fallback 测试改为验证 raise [quick]
└── Task 3: 验证其他测试文件不受影响 [quick]

Wave FINAL:
└── Task F1: 运行全套测试，确认 ≥631 passed [quick]
```

### Dependency Matrix

- **1**: None → 2, 3
- **2**: 1 → F1
- **3**: 1 → F1

---

## TODOs

- [ ] 1. 修改 amazon_data.py — 删除 mock fallback，API 失败直接 raise

  **What to do**:
  - 定义自定义异常类 `KeepaDataError(Exception)` 在文件顶部
  - 删除 `_mock_reviews()` 函数（第 238-248 行）
  - 删除 `_mock_qa()` 函数（第 251-259 行）
  - `fetch_reviews()` 中所有 `return _mock_reviews(asin)` 改为 `raise KeepaDataError(f"fetch_reviews failed for {asin}: {reason}")`
    - 第 279 行：API 异常 → raise（保留 logger.warning 后 raise）
    - 第 284 行：无 product data → raise
    - 第 289 行：无 reviews → raise
    - 第 304 行：`results or _mock_reviews(asin)` → 如果 results 为空则 raise
  - `fetch_qa()` 同理处理所有 fallback 点
    - 第 324 行：API 异常 → raise
    - 第 329 行：无 product data → raise
    - 第 334 行：无 Q&A → raise
    - 第 347 行：空结果 → raise
  - 函数 docstring 更新：删掉 "Never raises" 和 "returns mock data" 相关描述

  **Must NOT do**:
  - 不修改 `fetch_asin_detail()`、`fetch_category_top()` 等其他函数
  - 不改函数签名（参数和返回类型不变）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (基础改动)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 2, 3
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `pipeline/layers/amazon_data.py:238-347` — 当前 mock fallback 实现，需要修改的全部代码

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: fetch_reviews 在无 API key 时 raise KeepaDataError
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.layers.amazon_data import fetch_reviews; fetch_reviews('B0TEST')"
      2. 预期抛出 KeepaDataError（因为没有有效 KEEPA_API_KEY）
    Expected Result: 输出包含 "KeepaDataError" 的 traceback，进程退出码非 0
    Evidence: .sisyphus/evidence/task-1-reviews-raise.txt

  Scenario: fetch_qa 在无 API key 时 raise KeepaDataError
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.layers.amazon_data import fetch_qa; fetch_qa('B0TEST')"
    Expected Result: 输出包含 "KeepaDataError" 的 traceback，进程退出码非 0
    Evidence: .sisyphus/evidence/task-1-qa-raise.txt

  Scenario: _mock_reviews 和 _mock_qa 函数已不存在
    Tool: Bash
    Steps:
      1. grep -n "_mock_reviews\|_mock_qa" pipeline/layers/amazon_data.py
    Expected Result: 无输出（grep 退出码 1）
    Evidence: .sisyphus/evidence/task-1-no-mock-functions.txt
  ```

  **Commit**: YES
  - Message: `fix(amazon-data): remove mock fallback, raise on API failure`
  - Files: `pipeline/layers/amazon_data.py`
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/test_amazon_data.py -q`

- [ ] 2. 更新 test_amazon_data.py — fallback 测试改为验证 raise

  **What to do**:
  - `TestFetchReviewsFallback` 类（3 个测试）：改为验证 `fetch_reviews()` 在 key 缺失时 `pytest.raises(KeepaDataError)`
  - `TestFetchQaFallback` 类（3 个测试）：同理改为验证 raise
  - `TestFetchReviewsShape` 类（2 个测试）：这些用 mock config 触发 fallback 来检查数据格式，现在 fallback 不存在了。改为用 `_get` mock 返回正常 Keepa 响应来测试数据解析
  - `TestFetchQaShape` 类（1 个测试）：同理
  - 导入 `KeepaDataError`

  **Must NOT do**:
  - 不删除 `TestFetchAsinDetailEnriched`、`TestCompetitorListingEnrichedFields`、`TestTopNDefault`、`TestFetchCategoryTopHandlesFewerThan50` 等无关测试类
  - 不改其他测试文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 3 并行)
  - **Parallel Group**: Wave 2 (with Task 3)
  - **Blocks**: F1
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `tests/test_amazon_data.py` — 当前测试文件，需要重写的类: `TestFetchReviewsFallback`(L22-41), `TestFetchQaFallback`(L44-63), `TestFetchReviewsShape`(L66-78), `TestFetchQaShape`(L82-88)
  - `tests/test_amazon_data.py:TestFetchAsinDetailEnriched`(L104-148) — 正确的 mock `_get` 模式参考（用于重写 Shape 测试）

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: test_amazon_data.py 全部 PASS
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_amazon_data.py -v
    Expected Result: 所有测试 PASS，0 failures
    Evidence: .sisyphus/evidence/task-2-test-results.txt

  Scenario: fallback 测试确实在验证 raise 而非验证返回值
    Tool: Bash
    Steps:
      1. grep -n "pytest.raises\|KeepaDataError" tests/test_amazon_data.py
    Expected Result: 至少出现 6 次 pytest.raises（3 reviews + 3 qa fallback 测试）
    Evidence: .sisyphus/evidence/task-2-raises-check.txt
  ```

  **Commit**: YES
  - Message: `test(amazon-data): update tests to expect raise on API failure`
  - Files: `tests/test_amazon_data.py`
  - Pre-commit: `PYTHONPATH=. .venv/bin/pytest tests/test_amazon_data.py -q`

- [ ] 3. 验证其他测试文件不受影响

  **What to do**:
  - 检查以下文件中 patch `fetch_reviews` / `fetch_qa` 的用法，确认都是 mock 成功返回值或 `side_effect=Exception`，不依赖 mock fallback 行为：
    - `tests/test_orchestrator_brief.py` — L48-49 用 `return_value=[]`，L132-134 用 `side_effect=Exception` → 第二种现在会让调用方收到异常，需要确认 `step_analyze` 是否 catch 了（已有 `test_brief_with_partial_upstream_failure` 测试）
    - `tests/test_orchestrator_listing.py` — 用 `return_value=[]` patch
    - `tests/test_orchestrator_review.py` — 用 `return_value=[...]` patch
    - `tests/test_orchestrator_qa.py` — 用 `return_value=[...]` patch
    - `tests/test_parallel_analyze.py` — 用 `return_value=[]` patch
  - 重点检查 `test_brief_with_partial_upstream_failure`（L132-134）：它用 `side_effect=Exception` 测试上游失败时 brief 仍能生成。这个测试的行为取决于 `step_analyze` 是否 catch 了异常——确认这个测试仍然 PASS
  - 如果发现某个测试因为改动而 FAIL，修复它

  **Must NOT do**:
  - 不大规模重写其他测试文件（只做必要修复）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 2 并行)
  - **Parallel Group**: Wave 2 (with Task 2)
  - **Blocks**: F1
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `tests/test_orchestrator_brief.py:132-134` — `side_effect=Exception("qa fail")` 测试，重点检查
  - `tests/test_orchestrator_listing.py:96-98` — `return_value=[]` patch 模式
  - `tests/test_orchestrator_review.py:106-113` — `return_value=[...]` patch 模式
  - `tests/test_parallel_analyze.py:66-68` — `return_value=[]` patch 模式

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 全套测试 PASS
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
    Expected Result: ≥631 passed, 0 failures
    Evidence: .sisyphus/evidence/task-3-full-test.txt

  Scenario: 确认 test_brief_with_partial_upstream_failure 仍然 PASS
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_orchestrator_brief.py::test_brief_with_partial_upstream_failure -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-3-partial-failure-test.txt
  ```

  **Commit**: YES (groups with Task 2 if no changes needed, separate if fixes required)
  - Message: `test: fix tests affected by mock fallback removal`
  - Files: (any test files that needed fixing)
  - Pre-commit: full test suite

---

## Final Verification Wave

- [ ] F1. **Full Test Suite** — `quick`
      运行完整测试命令，确认 ≥631 passed, 0 failures。
      验证 `_mock_reviews` 和 `_mock_qa` 在整个 `pipeline/` 目录中不再存在。
      Output: `Tests [N passed] | Mock functions removed [YES/NO] | VERDICT`

---

## Commit Strategy

- **Task 1**: `fix(amazon-data): remove mock fallback, raise on API failure` — `pipeline/layers/amazon_data.py`
- **Task 2+3**: `test(amazon-data): update tests for API failure raise behavior` — `tests/test_amazon_data.py` + 其他受影响测试

---

## Success Criteria

### Verification Commands

```bash
# 全套测试
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: ≥631 passed

# 确认 mock 函数已删除
grep -rn "_mock_reviews\|_mock_qa" pipeline/
# Expected: 无输出

# 确认 fetch_reviews 失败时 raise
PYTHONPATH=. .venv/bin/python -c "from pipeline.layers.amazon_data import fetch_reviews; fetch_reviews('B0TEST')" 2>&1
# Expected: KeepaDataError traceback
```

### Final Checklist

- [ ] `_mock_reviews()` 和 `_mock_qa()` 已从代码中删除
- [ ] `fetch_reviews()` API 失败时 raise `KeepaDataError`
- [ ] `fetch_qa()` API 失败时 raise `KeepaDataError`
- [ ] 全部测试 ≥631 passed
- [ ] 无新增 pip 依赖
