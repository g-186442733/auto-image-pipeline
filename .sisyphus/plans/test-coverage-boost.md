# Test Coverage Boost + Warning Cleanup

## TL;DR

> **Quick Summary**: 补齐 4 个关键模块的测试覆盖率（confidence_routing 0%→95%+, prompt_manager 37%→80%+, qa_gate 65%→80%+, feedback_loop 56%→80%+），清理 247 个 pytest warnings，可选添加 CI。
>
> **Deliverables**:
>
> - 4 个新/扩展测试文件，覆盖 17 个未测试函数
> - `tests/conftest.py` 共享 fixture
> - 6 个文件的 `datetime.utcnow()` 修复
> - `orchestrator.py:235` SAWarning 修复
> - （可选）`.github/workflows/test.yml`
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Baseline → conftest.py → test files → warning fixes

---

## Context

### Original Request

用户粘贴了测试健康度报告的建议行动，要求按建议执行：

1. 立即补：confidence_routing.py（0%）和 prompt_manager.py（37%）
2. 重点补：qa_gate.py 和 feedback_loop.py
3. 清理 218 个 warnings（实际 247 个）
4. 考虑 CI 流水线

### Interview Summary

**Key Discussions**:

- 测试基线已验证：722 passed, 0 failed, 247 warnings
- 不引入新 pip 依赖
- 使用现有 unittest.mock + in-memory SQLite 模式
- DB 模式：`_reset_db()` + `create_all("sqlite:///:memory:")`

**Research Findings**:

- confidence_routing.py: 20 行纯数值逻辑，零依赖，最简单
- prompt_manager.py: 268 行，5 个未测函数，需 DB session mock
- qa_gate.py: 742 行，10 个未测/部分函数，需 Pillow + httpx mock，最复杂
- feedback_loop.py: 406 行，3 个完全未测 + 3 个部分未测，DB 模式已有
- Warnings: ~200 SAWarning（orchestrator.py:235 flush handler）+ ~40 DeprecationWarning（utcnow）
- 无 conftest.py（只有 conftest_e2e.py 非自动加载）
- 无 CI 流水线

### Metis Review

**Identified Gaps** (addressed):

- SAWarning 修复是行为变更需独立任务 → 已分离为独立 Wave 3 任务
- conftest.py fixture 命名可能冲突 → 任务中要求先 grep 检查
- 缺少精确数值目标 → 已添加 per-module coverage targets
- 缺少"不修改源码"护栏 → 已添加明确 Must NOT

---

## Work Objectives

### Core Objective

将 4 个低覆盖率模块提升至 ≥80%，消除全部 DeprecationWarning 和 SAWarning。

### Concrete Deliverables

- `tests/conftest.py` — 共享 DB 和 Flask fixture
- `tests/test_confidence_routing.py` — 扩展，覆盖 ConfidenceRouter 类
- `tests/test_prompt_manager.py` — 新建，覆盖 5 个函数
- `tests/test_qa_gate_coverage.py` — 新建，覆盖 10 个未测路径
- `tests/test_feedback_loop.py` — 扩展，覆盖 3+3 个函数/分支
- 6 个文件 `utcnow()` → `now(UTC)` 修复
- `orchestrator.py:235` SAWarning 修复

### Definition of Done

- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py` → ≥722 passed, 0 failed
- [ ] 4 个目标模块覆盖率均达标
- [ ] Warnings < 30（从 247 降）

### Must Have

- 每个测试文件独立可运行（`pytest tests/test_X.py -q` 单独通过）
- 复用现有 mock 模式（unittest.mock + in-memory SQLite）
- 每个 commit 后全量测试通过

### Must NOT Have (Guardrails)

- ❌ 不修改现有通过的测试代码
- ❌ 不修改源码（除 utcnow 替换和 SAWarning 修复）
- ❌ 不引入新 pip 依赖或 pytest 插件
- ❌ 不写集成测试，只写单元测试
- ❌ 不"顺手"重构发现的代码问题（记录但不修）
- ❌ 不添加 type hints、docstring 等非测试改动

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES (pytest 9.x)
- **Automated tests**: Tests-after（写测试覆盖已有代码）
- **Framework**: pytest + unittest.mock

### QA Policy

Every task MUST run full test suite and per-module coverage check.
Evidence saved to `.sisyphus/evidence/task-{N}-*.txt`.

- **Test verification**: Bash — `PYTHONPATH=. .venv/bin/pytest ...`
- **Coverage verification**: Bash — same + `--cov=pipeline/layers/{module} --cov-report=term-missing`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (Prerequisite — baseline capture):
└── Task 0: Capture baseline snapshot [quick]

Wave 1 (After baseline — independent):
├── Task 1: Create conftest.py [quick]
└── Task 2: Write confidence_routing tests [quick]

Wave 2 (After conftest — 3 parallel):
├── Task 3: Write prompt_manager tests [unspecified-low]
├── Task 4: Write feedback_loop tests [unspecified-low]
└── Task 5: Write qa_gate tests [unspecified-high]

Wave 3 (After all tests — 2 parallel):
├── Task 6: Fix datetime.utcnow warnings [quick]
└── Task 7: Fix SAWarning in orchestrator [deep]

Wave 4 (Optional):
└── Task 8: Add GitHub Actions CI [quick]

Wave FINAL (After ALL):
├── F1: Plan compliance audit [oracle]
├── F2: Code quality review [unspecified-high]
├── F3: Real QA — full suite [unspecified-high]
└── F4: Scope fidelity check [deep]
→ Present results → Get user okay
```

### Dependency Matrix

| Task  | Depends On          | Blocks        |
| ----- | ------------------- | ------------- |
| 0     | —                   | 1,2,3,4,5,6,7 |
| 1     | 0                   | 3,4,5         |
| 2     | 0                   | —             |
| 3     | 1                   | 6,7           |
| 4     | 1                   | 6,7           |
| 5     | 1                   | 6,7           |
| 6     | 3,4,5               | 8             |
| 7     | 3,4,5               | 8             |
| 8     | 6,7                 | F1-F4         |
| F1-F4 | 8 (or 6,7 if no CI) | user okay     |

### Agent Dispatch Summary

| Wave  | Tasks | Categories                                |
| ----- | ----- | ----------------------------------------- |
| 0     | 1     | quick                                     |
| 1     | 2     | quick × 2                                 |
| 2     | 3     | unspecified-low × 2, unspecified-high × 1 |
| 3     | 2     | quick, deep                               |
| 4     | 1     | quick                                     |
| FINAL | 4     | oracle, unspecified-high × 2, deep        |

---

## TODOs

- [x] 0. Capture baseline test snapshot

  **What to do**:
  - Run full test suite with coverage: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py --cov=pipeline/layers/confidence_routing --cov=pipeline/layers/prompt_manager --cov=pipeline/layers/qa_gate --cov=pipeline/layers/feedback_loop --cov-report=term-missing 2>&1 | tee .sisyphus/evidence/task-0-baseline.txt`
  - Record: test count, per-module coverage %, warning count

  **Must NOT do**:
  - Modify any files

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 0 (prerequisite)
  - **Blocks**: Tasks 1-8
  - **Blocked By**: None

  **References**:
  - `pyproject.toml` — pytest config section `[tool.pytest.ini_options]`

  **Acceptance Criteria**:

  **QA Scenarios:**

  ```
  Scenario: Baseline capture produces complete output
    Tool: Bash
    Preconditions: .sisyphus/evidence/ directory exists
    Steps:
      1. Run the full test + coverage command above
      2. Verify output file `.sisyphus/evidence/task-0-baseline.txt` exists
      3. Verify output contains "passed" (expect 722+)
      4. Verify output contains coverage lines for all 4 modules
    Expected Result: File exists with 722 passed, 0 failed, coverage percentages for 4 modules
    Failure Indicators: File missing, "ERRORS" in output, fewer than 722 passed
    Evidence: .sisyphus/evidence/task-0-baseline.txt
  ```

  **Commit**: NO (read-only task)

- [x] 1. Create tests/conftest.py with shared fixtures

  **What to do**:
  - First: `grep -r "def db_session\|def client\|def app" tests/test_*.py` to check for fixture name conflicts
  - Create `tests/conftest.py` with:
    - `db_session` fixture: in-memory SQLite, `create_all`, yield session, teardown
    - `flask_client` fixture (NOT `client` — avoid conflicts): test client from `create_app()`
  - Follow exact pattern from `tests/test_feedback_loop.py` DB setup
  - Run full test suite to verify no regressions

  **Must NOT do**:
  - Rename or move `conftest_e2e.py`
  - Change any existing test files
  - Add pytest plugins

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 3, 4, 5
  - **Blocked By**: Task 0

  **References**:
  - `tests/test_feedback_loop.py` — DB session fixture pattern (in-memory SQLite + `_reset_db()`)
  - `tests/conftest_e2e.py` — existing shared utilities (`setup_tmp_db`, `make_flask_client`, `make_png_file`)
  - `pipeline/models/base.py` — `create_all()` function and `_engine` override pattern

  **Acceptance Criteria**:

  **QA Scenarios:**

  ```
  Scenario: conftest.py loads without breaking existing tests
    Tool: Bash
    Preconditions: tests/conftest.py created
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
      2. Compare pass count to baseline (≥722)
      3. Verify 0 failures
    Expected Result: ≥722 passed, 0 failed
    Failure Indicators: Any test failure, import errors mentioning conftest
    Evidence: .sisyphus/evidence/task-1-conftest-verify.txt

  Scenario: conftest fixtures are importable
    Tool: Bash
    Preconditions: tests/conftest.py exists
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/python -c "import pytest; print('conftest importable')"
      2. Run: PYTHONPATH=. .venv/bin/pytest tests/conftest.py --collect-only -q
    Expected Result: No import errors, fixtures listed
    Failure Indicators: ImportError, ModuleNotFoundError
    Evidence: .sisyphus/evidence/task-1-conftest-import.txt
  ```

  **Commit**: YES
  - Message: `test: add conftest.py with shared db_session fixture`
  - Files: `tests/conftest.py`
  - Pre-commit: full test suite

- [x] 2. Write confidence_routing tests (0% → ≥95%)

  **What to do**:
  - Add `TestConfidenceRouter` class to existing `tests/test_confidence_routing.py`
  - Test `ConfidenceRouter.route(score)`:
    - score=100 → "pass"
    - score=80 → "pass" (boundary)
    - score=79.9 → "retry_alt_prompt"
    - score=50 → "retry_alt_prompt" (boundary)
    - score=49.9 → "human_review"
    - score=0 → "human_review"
  - Test `ConfidenceRouter.is_pass(score)`: True at 80, False at 79.9
  - Test `ConfidenceRouter.is_human_review(score)`: True at 49.9, False at 50
  - Use `@pytest.mark.parametrize` for concise coverage

  **Must NOT do**:
  - Modify existing `TestRouteByConfidence` class
  - Import anything from orchestrator

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 1)
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: Task 0

  **References**:
  - `pipeline/layers/confidence_routing.py:1-20` — 全部源码，3 个方法，阈值 80.0 和 50.0
  - `tests/test_confidence_routing.py:1-37` — 现有测试（测 orchestrator 函数，非 ConfidenceRouter 类）

  **Acceptance Criteria**:

  **QA Scenarios:**

  ```
  Scenario: confidence_routing coverage ≥95%
    Tool: Bash
    Preconditions: Tests written in test_confidence_routing.py
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/pytest tests/test_confidence_routing.py --cov=pipeline/layers/confidence_routing --cov-report=term-missing -q
      2. Parse coverage percentage from output
      3. Verify ≥95%
    Expected Result: ≥95% coverage, all tests pass
    Failure Indicators: Coverage <95%, any test failure
    Evidence: .sisyphus/evidence/task-2-confidence-coverage.txt

  Scenario: Boundary values return correct results
    Tool: Bash
    Preconditions: Tests include boundary cases 80.0 and 50.0
    Steps:
      1. Run: PYTHONPATH=. .venv/bin/pytest tests/test_confidence_routing.py -v -q
      2. Verify parametrized test names include boundary values
    Expected Result: All boundary tests pass
    Evidence: .sisyphus/evidence/task-2-confidence-verbose.txt
  ```

  **Commit**: YES
  - Message: `test: add ConfidenceRouter tests (0% → 95%+)`
  - Files: `tests/test_confidence_routing.py`
  - Pre-commit: full test suite

- [x] 3. Write prompt_manager tests (37% → ≥80%)

  **What to do**:
  - Create `tests/test_prompt_manager_coverage.py`
  - Mock DB session using pattern from `tests/test_prompt_editor.py`
  - Test `create_prompt_asset(session, name, template, style, category)`: happy path, duplicate name raises
  - Test `update_prompt_asset(session, id, **kwargs)`: found→updates, not found→returns None
  - Test `get_prompt_asset(session, id)`: found→returns obj, not found→None
  - Test `list_prompt_assets(session, category=None)`: all, filtered by category
  - Test `seed_default_templates(session)`: idempotent (call twice, no duplicates)

  **Must NOT do**:
  - Modify `prompt_manager.py` source
  - Modify existing `tests/test_prompt_editor.py`
  - Add new pip dependencies

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4, 5)
  - **Parallel Group**: Wave 2
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1

  **References**:
  - `pipeline/layers/prompt_manager.py` — 5 functions: create_prompt_asset, update_prompt_asset, get_prompt_asset, list_prompt_assets, seed_default_templates
  - `tests/test_prompt_editor.py:1-40` — DB session mock pattern (in-memory SQLite)

  **QA Scenarios:**

  ```
  Scenario: prompt_manager coverage ≥80%
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_prompt_manager_coverage.py --cov=pipeline/layers/prompt_manager --cov-report=term-missing -q 2>&1 | tee .sisyphus/evidence/task-3-prompt-coverage.txt
      2. Verify ≥80% coverage
    Expected Result: ≥80% coverage, all tests pass
    Evidence: .sisyphus/evidence/task-3-prompt-coverage.txt
  ```

  **Commit**: YES
  - Message: `test: add prompt_manager tests (37% → 80%+)`
  - Files: `tests/test_prompt_manager_coverage.py`
  - Pre-commit: full test suite

- [x] 4. Write feedback_loop tests (56% → ≥80%)

  **What to do**:
  - Extend existing `tests/test_feedback_loop.py` OR create `tests/test_feedback_loop_coverage.py`
  - Using existing DB fixture pattern (`_reset_db()` + in-memory SQLite)
  - Test `record_ab_test(session, project_id, variant_a, variant_b)`: happy path, DB record created
  - Test `record_delivery_result(session, project_id, slot_id, score)`: happy path, record saved
  - Test `get_category_insights(session, category)`: empty→[], with data→correct insights
  - Test exception/rollback branches in `record_ab_result`: DB error → rollback called
  - Test `update_brand_profile_from_results`: no results→no-op, with results→profile updated
  - Test `export_conclusions`: empty DB→empty dict, with data→correct structure

  **Must NOT do**:
  - Modify `feedback_loop.py` source
  - Break existing tests in `test_feedback_loop.py`

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3, 5)
  - **Parallel Group**: Wave 2
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1

  **References**:
  - `pipeline/layers/feedback_loop.py` — functions: record_ab_test, record_delivery_result, get_category_insights, record_ab_result (rollback), update_brand_profile_from_results, export_conclusions
  - `tests/test_feedback_loop.py` — existing DB fixture pattern to follow

  **QA Scenarios:**

  ```
  Scenario: feedback_loop coverage ≥80%
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_feedback_loop.py tests/test_feedback_loop_coverage.py --cov=pipeline/layers/feedback_loop --cov-report=term-missing -q 2>&1 | tee .sisyphus/evidence/task-4-feedback-coverage.txt
      2. Verify ≥80%
    Expected Result: ≥80% coverage, 0 failures
    Evidence: .sisyphus/evidence/task-4-feedback-coverage.txt
  ```

  **Commit**: YES
  - Message: `test: add feedback_loop tests (56% → 80%+)`
  - Files: `tests/test_feedback_loop_coverage.py` (or extended test_feedback_loop.py)
  - Pre-commit: full test suite

- [x] 5. Write qa_gate coverage tests (65% → ≥80%)

  **What to do**:
  - Create `tests/test_qa_gate_coverage.py`
  - Mock Pillow (`PIL.Image.open`) and httpx for vision API calls
  - Test `validate_image(path)`: valid image→passes, missing file→raises, wrong size→fails
  - Test `check_resolution(img)`: ≥1000×1000→pass, 999×999→fail
  - Test `check_aspect_ratio(img)`: 1:1 OK, extreme ratio→fail
  - Test `check_background(img)`: pure white bg (mock pixel analysis)→pass
  - Test `check_text_overlay(img)`: mock OCR/vision→no text→pass, text found→fail
  - Test `run_qa_checks_legacy(image_path)`: calls sub-checks, returns dict
  - Test `llm_qa_evaluate` JSON repair branch: malformed JSON→repaired→parsed
  - Test `run_qa_checks` error branch: step raises→error captured in result dict
  - Test `run_qa_gate` Gate5 fallback: Gate5 unavailable→fallback path used

  **Must NOT do**:
  - Modify `qa_gate.py` source
  - Make real API calls (mock ALL external calls)
  - Break existing `test_qa_gate_v2.py`, `test_qa_gate_5doors.py`, `test_qa_gate5.py`

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3, 4)
  - **Parallel Group**: Wave 2
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1

  **References**:
  - `pipeline/layers/qa_gate.py` — 742 lines; focus: validate_image, check_resolution, check_aspect_ratio, check_background, check_text_overlay, run_qa_checks_legacy, llm_qa_evaluate (JSON repair), run_qa_checks (error branch), run_qa_gate (Gate5 fallback)
  - `tests/test_qa_gate_v2.py` — mock patterns (httpx, PIL)
  - `tests/test_qa_gate_5doors.py` — gates 1-4 mock patterns

  **QA Scenarios:**

  ```
  Scenario: qa_gate coverage ≥80%
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_qa_gate_coverage.py --cov=pipeline/layers/qa_gate --cov-report=term-missing -q 2>&1 | tee .sisyphus/evidence/task-5-qgate-coverage.txt
      2. Verify ≥80%
    Expected Result: ≥80% coverage, 0 failures
    Evidence: .sisyphus/evidence/task-5-qgate-coverage.txt
  ```

  **Commit**: YES
  - Message: `test: add qa_gate coverage tests (65% → 80%+)`
  - Files: `tests/test_qa_gate_coverage.py`
  - Pre-commit: full test suite

- [x] 6. Fix datetime.utcnow() DeprecationWarnings (~40 warnings)

  **What to do**:
  - In **source files**: replace `datetime.utcnow()` with `datetime.now(UTC)` and `datetime.utcnow` (Column default) with `lambda: datetime.now(UTC)`
    - `pipeline/layers/ranking_tracker.py:20` — `cutoff = datetime.utcnow()` → `datetime.now(UTC)`
    - `pipeline/layers/hypothesis_tracker.py:16,36` — `now = datetime.utcnow()` → `datetime.now(UTC)`
    - `pipeline/models/aplus_content.py:38,39` — Column defaults `datetime.utcnow` → `lambda: datetime.now(UTC)`
  - Add `from datetime import UTC` import to each file (Python 3.11+); fallback: `from datetime import timezone; UTC = timezone.utc`
  - In **test files**: same fix
    - `tests/test_hypothesis_tracker.py`
    - `tests/test_integration_pipeline.py`
    - `tests/test_ranking_tracker.py:91`
  - Run full suite; verify DeprecationWarning count drops significantly

  **Must NOT do**:
  - Change any business logic (only datetime construction)
  - Modify other source files

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 7)
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 3, 4, 5

  **References**:
  - Affected source: `pipeline/layers/ranking_tracker.py:20`, `pipeline/layers/hypothesis_tracker.py:16,36`, `pipeline/models/aplus_content.py:38,39`
  - Affected tests: `tests/test_hypothesis_tracker.py`, `tests/test_integration_pipeline.py`, `tests/test_ranking_tracker.py:91`

  **QA Scenarios:**

  ```
  Scenario: DeprecationWarnings eliminated
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py -W error::DeprecationWarning 2>&1 | tee .sisyphus/evidence/task-6-utcnow.txt
      2. Verify 0 DeprecationWarning failures
    Expected Result: 0 DeprecationWarning, all tests still pass
    Evidence: .sisyphus/evidence/task-6-utcnow.txt
  ```

  **Commit**: YES
  - Message: `fix: replace datetime.utcnow with datetime.now(UTC) in 6 files`
  - Files: 3 source + 3 test files
  - Pre-commit: full test suite

- [x] 7. Fix SAWarning in orchestrator flush handler (~200 warnings)

  **What to do**:
  - Investigate `pipeline/orchestrator.py:235` — the `session.commit()` call inside a flush event handler causing identity map collision
  - Likely fix: wrap the commit in `session.no_autoflush` context, or defer the commit outside the event handler, or use `session.expire_all()` after commit
  - Pattern: check if there's an `@event.listens_for(session, "after_flush")` or similar; restructure to avoid commit-in-flush
  - Run suite with `-W error::SAWarning` to confirm elimination
  - If fix is risky: add a code comment explaining the issue and why it's safe to suppress with `warnings.filterwarnings`

  **Must NOT do**:
  - Change pipeline business logic
  - Break any orchestrator tests

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 6)
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 3, 4, 5

  **References**:
  - `pipeline/orchestrator.py:225-245` — flush handler context
  - SQLAlchemy docs on session events and identity map

  **QA Scenarios:**

  ```
  Scenario: SAWarning count drops to near-zero
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py 2>&1 | grep -c "SAWarning" | tee .sisyphus/evidence/task-7-sawarning.txt
      2. Verify count < 5 (ideally 0)
    Expected Result: <5 SAWarnings
    Evidence: .sisyphus/evidence/task-7-sawarning.txt
  ```

  **Commit**: YES
  - Message: `fix: resolve SAWarning in orchestrator flush handler`
  - Files: `pipeline/orchestrator.py`
  - Pre-commit: full test suite

- [x] 8. (Optional) Add GitHub Actions CI pipeline

  **What to do**:
  - Create `.github/workflows/test.yml`
  - Trigger: `push` and `pull_request` on `main`
  - Steps: checkout, Python 3.11, pip install, pytest full suite command
  - Use the exact test command: `PYTHONPATH=. pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`

  **Must NOT do**:
  - Add new pip dependencies to requirements.txt just for CI
  - Create matrix builds (single Python version is fine)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 4, after warnings fixed)
  - **Parallel Group**: Wave 4
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 6, 7

  **QA Scenarios:**

  ```
  Scenario: YAML is valid
    Tool: Bash
    Steps:
      1. python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo OK
    Expected Result: prints "OK"
    Evidence: .sisyphus/evidence/task-8-ci-yaml.txt
  ```

  **Commit**: YES
  - Message: `ci: add GitHub Actions pytest workflow`
  - Files: `.github/workflows/test.yml`
  - Pre-commit: YAML lint

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — `oracle`
      Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files in `.sisyphus/evidence/`. Compare deliverables against plan.
      Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
      Run full test suite + coverage. Review all new test files for: proper assertions (not just `assert True`), proper isolation, no hardcoded paths, clean imports. Check no `as any` equivalent patterns.
      Output: `Tests [N pass/N fail] | Coverage [per-module] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
      Execute every QA scenario from every task — follow exact steps, capture evidence. Test cross-task: run full suite after ALL changes. Verify warning count < 30.
      Output: `Scenarios [N/N pass] | Full Suite [pass/fail] | Warnings [N] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
      For each task: verify only specified files were changed. No source code changes except utcnow + SAWarning. No existing tests modified. No unaccounted files.
      Output: `Tasks [N/N compliant] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Order | Message                                                | Files                              | Pre-commit |
| ----- | ------------------------------------------------------ | ---------------------------------- | ---------- |
| 1     | `test: add conftest.py with shared db_session fixture` | `tests/conftest.py`                | full suite |
| 2     | `test: add ConfidenceRouter tests (0% → 95%+)`         | `tests/test_confidence_routing.py` | full suite |
| 3     | `test: add prompt_manager tests (37% → 80%+)`          | `tests/test_prompt_manager.py`     | full suite |
| 4     | `test: add feedback_loop tests (56% → 80%+)`           | `tests/test_feedback_loop.py`      | full suite |
| 5     | `test: add qa_gate coverage tests (65% → 80%+)`        | `tests/test_qa_gate_coverage.py`   | full suite |
| 6     | `fix: replace datetime.utcnow with datetime.now(UTC)`  | 6 files (3 source + 3 test)        | full suite |
| 7     | `fix: resolve SAWarning in orchestrator flush handler` | `pipeline/orchestrator.py`         | full suite |
| 8     | `ci: add GitHub Actions pytest workflow`               | `.github/workflows/test.yml`       | YAML lint  |

---

## Success Criteria

### Verification Commands

```bash
# Full suite
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: ≥760 passed, 0 failed, <30 warnings

# Per-module coverage
PYTHONPATH=. .venv/bin/pytest tests/ --cov=pipeline/layers/confidence_routing --cov=pipeline/layers/prompt_manager --cov=pipeline/layers/qa_gate --cov=pipeline/layers/feedback_loop --cov-report=term-missing -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: confidence_routing ≥95%, prompt_manager ≥80%, qa_gate ≥80%, feedback_loop ≥80%
```

### Final Checklist

- [ ] All 4 module coverage targets met
- [ ] ≥722 existing tests still pass (zero regressions)
- [ ] Warnings < 30 (from 247)
- [ ] No source code changes beyond utcnow + SAWarning fix
- [ ] No new pip dependencies added
- [ ] Each test file runs independently
- [ ] All evidence files present in `.sisyphus/evidence/`
