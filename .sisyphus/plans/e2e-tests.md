# E2E Tests for auto-image-pipeline (L1-L4)

## TL;DR

> **Quick Summary**: Write E2E tests covering CLI orchestrator (9-step pipeline) and Flask Web app (~30 routes) for all L1-L4 features. All external APIs mocked, only test files created, no business code changes.
>
> **Deliverables**:
>
> - `tests/test_e2e_orchestrator.py` — CLI/orchestrator full pipeline E2E
> - `tests/test_e2e_web_app.py` — Flask routes E2E
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Task 1 → Task 2 (parallel with Task 3) → verify

---

## Context

### Original Request

E2E tests for auto-image-pipeline covering CLI and Web entry points, cross-referencing PRD §4 functional requirements and SYSTEM_SPEC §6 data flow as test baselines.

### Interview Summary

**Key Discussions**:

- Two test lines: CLI orchestrator (9 steps) and Web Flask app (~30 routes + 4 blueprints)
- All external APIs (Keepa, Gemini, GPT-4o, gpt-image-1, 147AI) mocked at function level
- QA Gate loop: max 2 retries, thresholds ≥80/60-80/<60
- Delivery filtering: avg QA score ≥70
- Test baseline: 619 passed, 27 pre-existing failures — no new failures allowed
- Reuse patterns from existing test_e2e_tws.py / test_e2e_pipeline.py (temp DB, \_minimal_png, mock patterns)
- New files only — don't modify existing --ignore'd test files
- No new pip dependencies, no L5 code, no business source changes

---

## Work Objectives

### Core Objective

Validate L1-L4 end-to-end flows through both CLI orchestrator and Web interfaces with comprehensive mocking.

### Concrete Deliverables

- `tests/test_e2e_orchestrator.py` — orchestrator pipeline E2E tests
- `tests/test_e2e_web_app.py` — Flask Web app E2E tests

### Definition of Done

- [x] `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py` → 619+ passed, 27 failures (no new)

### Must Have

- Happy path: full 9-step pipeline init→feedback
- QA retry loop: score 60-80 triggers retry, max 2 retries
- QA failure path: score <60 → qa_failed status
- QA pass path: score ≥80 → direct pass
- Delivery filtering: only slots with avg score ≥70 included
- Web: project CRUD, pipeline trigger, status polling, file upload/delete
- Web: customer input form validation (14 required fields)
- Web: QA dashboard, approval flow
- Web: blueprint routes (hypotheses CRUD, tag review, decisions)
- All external APIs mocked (no real network calls)
- DB state verification at each pipeline step

### Must NOT Have (Guardrails)

- NO modifications to any business source code (pipeline/\*_/_.py)
- NO modifications to existing test files (test_e2e_tws.py, test_e2e_pipeline.py, test_l5_migration.py, or the 6 L1-L4 test files)
- NO L5 features (ab_tests, performance_score, feedback loop)
- NO new pip dependencies
- NO real API calls — all external services fully mocked
- NO unnecessary inline comments (test docstrings for boundary conditions are OK)
- NO Alembic usage

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision

- **Infrastructure exists**: YES (pytest, fixtures dir, 6 existing test files)
- **Automated tests**: Tests-after (we ARE writing the tests)
- **Framework**: pytest (existing)

### QA Policy

Every task verified by running the full test suite command.
Evidence saved to `.sisyphus/evidence/task-{N}-*.txt`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation):
├── Task 1: Shared test helpers module [quick]

Wave 2 (Core tests — PARALLEL):
├── Task 2: CLI/Orchestrator E2E tests (depends: 1) [deep]
├── Task 3: Flask Web App E2E tests (depends: 1) [deep]

Wave FINAL (Verification):
├── Task F1: Full test suite run — baseline verification [quick]
```

### Dependency Matrix

- **1**: none → 2, 3
- **2**: 1 → F1
- **3**: 1 → F1
- **F1**: 2, 3 → done

### Agent Dispatch Summary

- **Wave 1**: 1 task — T1 → `quick`
- **Wave 2**: 2 tasks — T2 → `deep`, T3 → `deep`
- **FINAL**: 1 task — F1 → `quick`

---

## TODOs

- [x] 1. Shared E2E Test Helpers (conftest_e2e.py)

  **What to do**:
  - Create `tests/conftest_e2e.py` with shared fixtures:
    - `tmp_db` fixture: temp SQLite DB, `Base.metadata.create_all()`, patch `get_session`/`get_engine`, yield session, teardown
    - `_minimal_png(path)` helper: valid 1200×1200 PNG (passes Gate1 ≥1000×1000) — reuse pattern from test_e2e_tws.py
    - `mock_external_apis` fixture: patches Keepa, Gemini/OpenAI, 147AI, vision APIs with reasonable returns
    - `flask_test_client` fixture: `create_app()` + test DB → `app.test_client()`
    - `sample_brief_data` fixture: valid brief dict matching `fixtures/tws_brief.json` structure
  - Follow patterns from existing `tests/test_e2e_tws.py` lines 1-60

  **Must NOT do**: Don't duplicate existing conftest.py fixtures; no new pip deps

  **Recommended Agent Profile**: **Category**: `quick` | **Skills**: []

  **Parallelization**: Wave 1 (solo) | **Blocks**: 2, 3 | **Blocked By**: None

  **References**:
  - `tests/test_e2e_tws.py:1-60` — Mock patterns, \_minimal_png, DB setup
  - `tests/test_e2e_pipeline.py:1-40` — Alternative DB fixture pattern
  - `pipeline/web/app.py:create_app()` — Flask app factory
  - `pipeline/models.py` — Base, get_session, get_engine

  **Acceptance Criteria**:
  - [x] `PYTHONPATH=. .venv/bin/python -c "from tests.conftest_e2e import _minimal_png; print('OK')"` → prints OK

  **QA Scenarios:**

  ```
  Scenario: Helpers importable
    Tool: Bash
    Steps: PYTHONPATH=. .venv/bin/python -c "from tests.conftest_e2e import _minimal_png; print('OK')"
    Expected Result: prints "OK"
    Evidence: .sisyphus/evidence/task-1-import.txt
  ```

  **Commit**: NO (groups with final)

- [x] 2. CLI/Orchestrator E2E Tests

  **What to do**:
  Create `tests/test_e2e_orchestrator.py`:

  a) **Happy Path — Full Pipeline** (F-DA-01→F-DRL-05): `run_full_pipeline(brief_path)` with mocks, QA scores ≥80. Assert status transitions init→analyzed→planned→generated→qa_passed→completed. Assert DB records at each step.

  b) **QA Retry Loop** (PRD §6.4, F-QA-05): Mock scores 65 then 85. Assert 2 QA runs, final status=qa_passed.

  c) **QA Failure → Manual** (PRD iron rule #10): All attempts <60. Assert max 3 attempts (1+2 retries), status=qa_failed.

  d) **QA Direct Pass** (F-QA-04): Score ≥80 first attempt. Assert 1 QA run, no retries.

  e) **Delivery Filtering** (F-DEL-01): Mixed scores, assert only slots avg ≥70 in package.

  f) **Step-by-Step**: Test each step individually, assert correct status + DB state.

  g) **Error Handling**: Exception in step_analyze → status="failed", exception re-raised.

  **Must NOT do**: No L5 features, no real API calls, no modifying orchestrator.py

  **Recommended Agent Profile**: **Category**: `deep` | **Skills**: []

  **Parallelization**: Wave 2 (parallel with Task 3) | **Blocks**: F1 | **Blocked By**: 1

  **References**:
  - `pipeline/orchestrator.py` — All 9 steps, status transitions, QA retry loop
  - `pipeline/layers/qa_gate.py:run_qa_gate` — 5-door QA, scoring
  - `pipeline/layers/delivery.py:build_delivery_package` — Score filtering (avg ≥70)
  - `tests/test_e2e_tws.py` — Existing E2E patterns
  - `docs/PRD.md:160-168` — L4 status table
  - `docs/SYSTEM_SPEC.md:§6` — 11-step data flow

  **Acceptance Criteria**:
  - [x] `PYTHONPATH=. .venv/bin/pytest tests/test_e2e_orchestrator.py -v` → all PASSED, ≥7 tests

  **QA Scenarios:**

  ```
  Scenario: All orchestrator E2E tests pass
    Tool: Bash
    Steps: PYTHONPATH=. .venv/bin/pytest tests/test_e2e_orchestrator.py -v 2>&1 | tee .sisyphus/evidence/task-2-orchestrator.txt
    Expected Result: All PASSED, 0 failures
    Evidence: .sisyphus/evidence/task-2-orchestrator.txt
  ```

  **Commit**: NO (groups with final)

- [x] 3. Flask Web App E2E Tests

  **What to do**:
  Create `tests/test_e2e_web_app.py`:

  a) **Project CRUD**: POST/GET /api/projects, GET /api/projects/<id>
  b) **Pipeline Trigger & Status**: POST /api/projects/<id>/run, GET status, \_run_status tracking
  c) **File Upload & Delete**: valid PNG→200, invalid ext→400, >10MB→400, DELETE
  d) **Customer Input Form**: all 14 fields→200, missing fields→400 (CUSTOMER_INPUT_REQUIRED)
  e) **Brand Profile**: GET/PUT /api/brand-profile/<id>
  f) **QA Dashboard**: GET /qa-dashboard with QA data
  g) **Approval Flow**: POST approve/reject
  h) **Blueprint Routes**: hypotheses CRUD, tag review approve/reject/edit, decisions list
  i) **Error Cases**: nonexistent project→404, invalid JSON→400

  **Must NOT do**: Don't test pipeline execution (Task 2), no real API calls, no modifying app.py

  **Recommended Agent Profile**: **Category**: `deep` | **Skills**: []

  **Parallelization**: Wave 2 (parallel with Task 2) | **Blocks**: F1 | **Blocked By**: 1

  **References**:
  - `pipeline/web/app.py` — Flask app (822 lines), routes, upload validation, CUSTOMER_INPUT_REQUIRED
  - `pipeline/web/routes/project_routes.py:83` — Project CRUD
  - `pipeline/web/routes/hypothesis_routes.py:109` — Hypotheses CRUD
  - `pipeline/web/routes/tag_review_routes.py:75` — Tag review
  - `pipeline/web/routes/decision_routes.py:36` — Decisions
  - `tests/test_e2e_pipeline.py` — Flask test_client() patterns

  **Acceptance Criteria**:
  - [x] `PYTHONPATH=. .venv/bin/pytest tests/test_e2e_web_app.py -v` → all PASSED, ≥15 tests

  **QA Scenarios:**

  ```
  Scenario: All web E2E tests pass
    Tool: Bash
    Steps: PYTHONPATH=. .venv/bin/pytest tests/test_e2e_web_app.py -v 2>&1 | tee .sisyphus/evidence/task-3-webapp.txt
    Expected Result: All PASSED, 0 failures
    Evidence: .sisyphus/evidence/task-3-webapp.txt
  ```

  **Commit**: NO (groups with final)

---

## Final Verification Wave

- [x] F1. **Full Test Suite Baseline Verification** — `quick`

  **What to do**:
  - Run: `PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py`
  - Verify: 619+ passed, exactly 27 failures (all pre-existing)
  - If new failures: read failure output, identify root cause, fix ONLY in new test files

  **QA Scenarios:**

  ```
  Scenario: Full suite passes baseline
    Tool: Bash
    Steps:
      1. cd /Users/axureboutique/Projects/auto-image-pipeline
      2. PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py 2>&1 | tee .sisyphus/evidence/task-F1-baseline.txt
      3. Assert: output contains "passed" with count ≥ 619
      4. Assert: output contains "failed" with count = 27 (or fewer)
    Expected Result: ≥619 passed, ≤27 failed
    Evidence: .sisyphus/evidence/task-F1-baseline.txt
  ```

  **Commit**: YES
  - Message: `test(e2e): add end-to-end tests for CLI orchestrator and Flask web app`
  - Files: `tests/test_e2e_orchestrator.py`, `tests/test_e2e_web_app.py`, `tests/conftest_e2e.py` (if created)
  - Pre-commit: full test suite command

---

## Commit Strategy

- Single commit after all tests pass: `test(e2e): add end-to-end tests for CLI orchestrator and Flask web app`

---

## Success Criteria

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py --ignore=tests/test_l5_migration.py
# Expected: ≥619 passed, 27 failed (pre-existing)

PYTHONPATH=. .venv/bin/pytest tests/test_e2e_orchestrator.py -v
# Expected: all tests PASSED

PYTHONPATH=. .venv/bin/pytest tests/test_e2e_web_app.py -v
# Expected: all tests PASSED
```

### Final Checklist

- [x] All "Must Have" scenarios tested
- [x] All "Must NOT Have" constraints respected
- [x] No new test failures introduced
- [x] All external APIs mocked (no network calls)
- [x] DB state verified at each pipeline step
