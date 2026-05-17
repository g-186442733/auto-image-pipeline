# Fix 27 Pre-existing Test Failures + Coverage + Ignored E2E Tests

## TL;DR

> **Quick Summary**: Fix all 27 pre-existing test failures by adding missing model columns, registering missing routes, and updating stale test imports. Then add coverage reporting, and fix 2 ignored E2E test files.
>
> **Deliverables**:
>
> - 0 test failures (from 27)
> - `test_e2e_tws.py` and `test_e2e_pipeline.py` passing (un-ignored)
> - Coverage report via `pytest-cov`
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Wave 1 (model fixes) → Wave 2 (route/logic fixes) → Wave 3 (E2E + coverage)

---

## Context

### Original Request

Round 3 of test health improvement: fix 27 pre-existing failures, add coverage, fix ignored integration tests.

### Baseline

- **695 tests passing**, 27 failing
- Test command: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`

---

## Work Objectives

### Core Objective

Achieve 0 failures across the entire test suite and un-ignore 2 E2E test files.

### Must Have

- All 27 failures fixed
- `test_e2e_tws.py` and `test_e2e_pipeline.py` running and passing
- Coverage report generated

### Must NOT Have

- No new pip dependencies (pytest-cov is likely already available; if not, it's the ONE exception)
- No L5 code changes
- No Alembic migrations
- No unnecessary inline comments

---

## Verification Strategy

### Test Decision

- **Infrastructure exists**: YES (pytest)
- **Automated tests**: Fixing existing tests (not TDD)
- **Framework**: pytest

### QA Policy

Run full test suite after each wave. Evidence = pytest output.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Model + Import fixes — independent, can all run in parallel):
├── Task 1: Add live_at, drl_triggered_at to Project model [quick]
├── Task 2: Add status field to TagAssignment model [quick]
├── Task 3: Fix test_adapters.py imports (stub or remove) [quick]
└── Task 4: Verify route registration in create_app() [quick]

Wave 2 (Route + Logic fixes — depend on Wave 1 model changes):
├── Task 5: Fix test_decision_log.py (3 failures) [quick]
├── Task 6: Fix test_drl_scheduler.py (9 failures) [quick]
├── Task 7: Fix test_event_trigger.py (3 failures) [quick]
├── Task 8: Fix test_hypothesis_crud.py (4 failures) [quick]
├── Task 9: Fix test_tag_review_routes.py (4 failures) [quick]
└── Task 10: Fix test_integration_pipeline.py (2 failures) [quick]

Wave 3 (E2E + Coverage — after all failures fixed):
├── Task 11: Fix test_e2e_tws.py [unspecified-high]
├── Task 12: Fix test_e2e_pipeline.py [unspecified-high]
└── Task 13: Add coverage report + identify gaps [quick]

Wave FINAL (Verification):
└── Task F1: Full test suite run (un-ignore all) + coverage report
```

---

## TODOs

- [ ] 1. Add `live_at` and `drl_triggered_at` columns to Project model

  **What to do**:
  - Open `pipeline/models/project.py`
  - Add `live_at = Column(DateTime, nullable=True)` and `drl_triggered_at = Column(DateTime, nullable=True)`
  - Verify `pipeline/layers/drl_scheduler.py` references match

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Blocks**: Tasks 6, 7, 10
  - **Blocked By**: None

  **References**:
  - `pipeline/models/project.py` — Current Project model definition
  - `pipeline/layers/drl_scheduler.py` — Uses `project.live_at`, `project.drl_triggered_at`
  - `tests/test_drl_scheduler.py` — Creates `Project(live_at=..., drl_triggered_at=...)`

  **Acceptance Criteria**:
  - [ ] `Project` model has `live_at` and `drl_triggered_at` columns
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_drl_scheduler.py -q` → 0 failures

  **QA Scenarios**:

  ```
  Scenario: Project model accepts live_at and drl_triggered_at
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.models.project import Project; p = Project(name='test', live_at=None, drl_triggered_at=None); print('OK')"
    Expected Result: Prints "OK" without error
    Evidence: .sisyphus/evidence/task-1-model-check.txt
  ```

  **Commit**: YES (group with Task 2)
  - Message: `fix(models): add missing columns to Project and TagAssignment`

- [ ] 2. Add `status` field to TagAssignment model

  **What to do**:
  - Open `pipeline/models/tag_assignment.py`
  - Add `status = Column(String, nullable=True, default="pending")`
  - Verify test expectations match

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `pipeline/models/tag_assignment.py` — Current model: `id, entity_type, entity_id, tag_code, tag_layer, created_at`
  - `tests/test_tag_review_routes.py` — Creates `TagAssignment(status="pending", ...)`
  - `pipeline/web/routes/tag_review_routes.py` — May reference `status`

  **Acceptance Criteria**:
  - [ ] `TagAssignment` model has `status` field
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_tag_review_routes.py -q` → 0 failures

  **QA Scenarios**:

  ```
  Scenario: TagAssignment accepts status field
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.models.tag_assignment import TagAssignment; t = TagAssignment(status='pending'); print('OK')"
    Expected Result: Prints "OK"
    Evidence: .sisyphus/evidence/task-2-tag-status.txt
  ```

  **Commit**: YES (group with Task 1)

- [ ] 3. Fix test_adapters.py (2 failures)

  **What to do**:
  - Root cause: tests import `Helium10Adapter, JungleScoutAdapter` which don't exist
  - Option A: Create stub adapters (empty classes inheriting base) and export them
  - Option B: Remove/skip the tests if adapters are intentionally removed
  - **Prefer Option A** — stubs preserve test intent and are minimal code
  - Add `Helium10Adapter` and `JungleScoutAdapter` as stub classes in `pipeline/adapters/`
  - Export them from `pipeline/adapters/__init__.py`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `pipeline/adapters/__init__.py` — Current exports
  - `tests/test_adapters.py` — What's imported and tested

  **Acceptance Criteria**:
  - [ ] `from pipeline.adapters import Helium10Adapter, JungleScoutAdapter` works
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_adapters.py -q` → 0 failures

  **QA Scenarios**:

  ```
  Scenario: Adapter imports succeed
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.adapters import Helium10Adapter, JungleScoutAdapter; print('OK')"
    Expected Result: Prints "OK"
    Evidence: .sisyphus/evidence/task-3-adapter-import.txt
  ```

  **Commit**: YES
  - Message: `fix(adapters): add stub Helium10/JungleScout adapters`

- [ ] 4. Verify and fix route registration in create_app()

  **What to do**:
  - Read `pipeline/web/app.py` to check which blueprints/routes are registered
  - Ensure these are all registered: `decision_routes`, `project_routes`, `hypothesis_routes`, `tag_review_routes`
  - If any missing, add the blueprint registration
  - This unblocks Tasks 5-10

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1)
  - **Blocks**: Tasks 5, 7, 8, 9, 10
  - **Blocked By**: None

  **References**:
  - `pipeline/web/app.py` — `create_app()` function
  - `pipeline/web/routes/decision_routes.py`
  - `pipeline/web/routes/project_routes.py`
  - `pipeline/web/routes/hypothesis_routes.py`
  - `pipeline/web/routes/tag_review_routes.py`

  **Acceptance Criteria**:
  - [ ] All 4 route modules registered in `create_app()`
  - [ ] Flask test client can access `/api/decisions`, `/api/projects`, `/api/hypotheses`, `/api/tags`

  **QA Scenarios**:

  ```
  Scenario: All API routes accessible
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/python -c "from pipeline.web.app import create_app; app = create_app(); client = app.test_client(); print([r.rule for r in app.url_map.iter_rules() if '/api/' in r.rule])"
    Expected Result: Output includes /api/decisions, /api/projects, /api/hypotheses, /api/tags paths
    Evidence: .sisyphus/evidence/task-4-routes.txt
  ```

  **Commit**: YES
  - Message: `fix(web): register missing route blueprints in create_app`

- [ ] 5. Fix test_decision_log.py (3 failures)

  **What to do**:
  - After Task 4 ensures routes are registered, run the tests
  - If still failing, debug DB setup (ensure DecisionLog table created in test fixtures)
  - Fix any remaining issues in test or route code

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 6-10)
  - **Blocked By**: Task 4

  **References**:
  - `tests/test_decision_log.py` — Test source
  - `pipeline/web/routes/decision_routes.py` — Route implementation
  - `pipeline/models/decision_log.py` — DecisionLog model

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_decision_log.py -q` → 0 failures

- [ ] 6. Fix test_drl_scheduler.py (9 failures)

  **What to do**:
  - After Task 1 adds model columns, run the tests
  - Fix any remaining issues (mock problems, assertion mismatches)
  - 9 failures is the largest group — carefully verify each test

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2)
  - **Blocked By**: Task 1

  **References**:
  - `tests/test_drl_scheduler.py` — Test source (9 failing tests)
  - `pipeline/layers/drl_scheduler.py` — Business logic
  - `pipeline/models/project.py` — Model with new columns

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_drl_scheduler.py -q` → 0 failures

- [ ] 7. Fix test_event_trigger.py (3 failures)

  **What to do**:
  - After Task 4 ensures routes registered, run tests
  - Fix mock paths if needed (e.g., `pipeline.web.routes.project_routes.threading.Thread`)
  - Fix any DB/model issues

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2)
  - **Blocked By**: Tasks 1, 4

  **References**:
  - `tests/test_event_trigger.py` — Test source
  - `pipeline/web/routes/project_routes.py` — POST /api/projects

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_event_trigger.py -q` → 0 failures

- [ ] 8. Fix test_hypothesis_crud.py (4 failures)

  **What to do**:
  - After Task 4 ensures routes registered, run tests
  - Debug `TypeError` in test_update and test_delete
  - Fix Hypothesis model or route handler as needed

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2)
  - **Blocked By**: Task 4

  **References**:
  - `tests/test_hypothesis_crud.py` — Test source
  - `pipeline/web/routes/hypothesis_routes.py` — Route handlers
  - `pipeline/models/` — Hypothesis model

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_hypothesis_crud.py -q` → 0 failures

- [ ] 9. Fix test_tag_review_routes.py (4 failures)

  **What to do**:
  - After Task 2 adds status field to TagAssignment, run tests
  - Fix any remaining route or assertion issues

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2)
  - **Blocked By**: Tasks 2, 4

  **References**:
  - `tests/test_tag_review_routes.py` — Test source
  - `pipeline/web/routes/tag_review_routes.py` — Route handlers
  - `pipeline/models/tag_assignment.py` — Model with new status field

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_tag_review_routes.py -q` → 0 failures

- [ ] 10. Fix test_integration_pipeline.py (2 failures)

  **What to do**:
  - `test_decision_log_and_api`: depends on decision routes working (Task 5)
  - `test_listing_analysis_updates_brand`: `assert result is True` returns `False` — debug the business logic in the listing analysis layer, find why it returns False and fix
  - This may require reading the listing analysis source code

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2)
  - **Blocked By**: Tasks 1, 4

  **References**:
  - `tests/test_integration_pipeline.py` — Test source
  - `pipeline/layers/` — Listing analysis logic

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_integration_pipeline.py -q` → 0 failures

- [ ] 11. Fix and un-ignore test_e2e_tws.py

  **What to do**:
  - Verify fixture files exist: `tests/fixtures/tws_brief.json`, `tests/fixtures/tws_benchmark.json`
  - If missing, create minimal valid fixtures based on what the test expects
  - Run the test, fix any import errors or API signature mismatches
  - The test mocks Keepa/OpenAI Vision, uses temp SQLite — should be self-contained
  - Fix orchestrator API mismatches if step\_\* function signatures changed

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with Tasks 12-13)
  - **Blocked By**: All Wave 1-2 tasks (need clean baseline)

  **References**:
  - `tests/test_e2e_tws.py` — 431-line E2E test
  - `tests/fixtures/` — Fixture directory
  - `pipeline/orchestrator.py` — step\_\* functions

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_e2e_tws.py -q` → all pass
  - [ ] Remove `--ignore=tests/test_e2e_tws.py` from test command

  **QA Scenarios**:

  ```
  Scenario: TWS E2E test passes
    Tool: Bash
    Steps:
      1. PYTHONPATH=. .venv/bin/pytest tests/test_e2e_tws.py -v
    Expected Result: All tests PASSED
    Evidence: .sisyphus/evidence/task-11-e2e-tws.txt
  ```

- [ ] 12. Fix and un-ignore test_e2e_pipeline.py

  **What to do**:
  - Test calls `generate_brief`, `generate_slot_plan`, `build_prompt`, `build_delivery_package`
  - Verify function signatures match test expectations
  - Fix any import paths or argument mismatches
  - Run and iterate until all pass

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3)
  - **Blocked By**: All Wave 1-2 tasks

  **References**:
  - `tests/test_e2e_pipeline.py` — 259-line E2E test
  - `pipeline/layers/brief_generator.py` — `generate_brief`
  - `pipeline/layers/slot_planner.py` — `generate_slot_plan`
  - `pipeline/layers/prompt_engine.py` — `build_prompt`
  - `pipeline/layers/delivery.py` — `build_delivery_package`

  **Acceptance Criteria**:
  - [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_e2e_pipeline.py -q` → all pass
  - [ ] Remove `--ignore=tests/test_e2e_pipeline.py` from test command

- [ ] 13. Add coverage reporting

  **What to do**:
  - Check if `pytest-cov` is installed: `.venv/bin/pip show pytest-cov`
  - If not, install it (this is the ONE allowed dependency exception)
  - Run: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_l5_migration.py --cov=pipeline --cov-report=html --cov-report=term-missing`
  - Identify modules with <50% coverage for future gap-filling

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3)
  - **Blocked By**: All Wave 1-2 tasks

  **Acceptance Criteria**:
  - [ ] Coverage report generated in `htmlcov/`
  - [ ] Terminal output shows per-module coverage

---

## Final Verification Wave

- [ ] F1. Full test suite run (all tests, only ignoring test_l5_migration.py)

  **What to do**:
  - Run: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_l5_migration.py --cov=pipeline --cov-report=term-missing`
  - Verify: 0 failures, 0 errors
  - Capture total test count and coverage summary

  **Acceptance Criteria**:
  - [ ] 0 failures, 0 errors
  - [ ] Total tests ≥ 722 (695 existing + 27 fixed)
  - [ ] Coverage report shows all modules

---

## Commit Strategy

- **Wave 1**: `fix(models): add missing columns to Project and TagAssignment` + `fix(adapters): add stub Helium10/JungleScout adapters` + `fix(web): register missing route blueprints`
- **Wave 2**: `fix(tests): resolve 27 pre-existing test failures`
- **Wave 3**: `feat(tests): un-ignore E2E tests and add coverage reporting`

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_l5_migration.py  # Expected: 0 failures
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_l5_migration.py --cov=pipeline --cov-report=term-missing  # Expected: coverage report
```

### Final Checklist

- [ ] All 27 pre-existing failures fixed
- [ ] test_e2e_tws.py passing (un-ignored)
- [ ] test_e2e_pipeline.py passing (un-ignored)
- [ ] Coverage report generated
- [ ] No new test failures introduced
- [ ] No L5 code touched
- [ ] No unnecessary comments added
