# Learnings & Conventions

## [2026-04-18] Session Start

### Patterns

- Models inherit Base from pipeline.models.base
- Column style: snake_case, Text for JSON-like data (SQLite compatible)
- server_default=func.now() for created_at
- ForeignKey("projects.id") for project_id
- Nullable project_id on CompetitorListing, ReviewCluster, QAEntry
- Non-nullable project_id on IntakeChecklist, ImageBrief
- All new models registered in pipeline/models/**init**.py

### Test Conventions

- venv: .venv/bin/python -m pytest
- Evidence: .sisyphus/evidence/task-{N}-{slug}.txt
- TDD: RED → GREEN → REFACTOR
- Use in-memory SQLite for tests (get_session() or test fixture)

### Adapter Pattern (from gemini_vision_adapter.py)

- All adapters use GOOGLE_API_KEY env var (never hardcoded)
- Return dataclasses/typed objects, not raw dicts

### Wave 1 Completed Tasks

- T1 (B1): image_path persisted after step_generate ✅
- T2 (B2): check_background → vision model ✅
- T3 (B3): ASIN validation on web route ✅
- T4 (B4): Flask secret_key + 24h TTL ✅
- T5: 5 new models created, 9 tests pass ✅
- T7: step_analyze result flows to step_plan, dict→ORM conversion fixed ✅
- T8: listing_analyzer.py — analyze_listing(asin, keepa_data) → CompetitorListing ✅

### T8 Findings

- AmazonBenchmark has NO title field — degraded mode sets title=None
- google.generativeai must be lazy-imported (not in venv); tests mock via sys.modules patch
- selling_points_map stored as JSON string in Text column
- Keepa data minus title stored in bullet_points as JSON

### T10 Findings

- qa_analyzer.py follows identical pattern to review_analyzer.py: lazy Gemini import, \_call_gemini helper, JSON parse with fallback
- QAEntry fields: asin, question, answer, frequency (default=1), category (default="general")
- 8 tests (6 analyze_qa + 2 \_call_gemini), all pass; full suite 71 passed

### T11 Findings

- brief_generator.py integrates all three T8/T9/T10 outputs into a single ImageBrief
- Same lazy import + \_call_gemini pattern; \_call_gemini returns "{}" (not "[]") on no-key since brief is object not array
- generate_brief() accepts optional session param for testability (in-memory SQLite fixture)
- Triple degradation: no key, API error, bad JSON all silently fall back to \_DEFAULT_BRIEF
- ImageBrief.slot_index set to 0 as the brief covers all slots (slot details are inside brief_json)
- 10 tests added; full suite 87 passed (baseline was 77, target was 85)

### T13 Findings

- slot_planner.py refactored: accepts optional `session` param (owns_session pattern)
- ImageBrief per-slot lookup via `brief_json["target_tags"]` dict with 4 tag keys
- `_tags_from_brief()` helper: returns None on any parse/missing error → fallback to \_SLOT_DEFAULTS
- AmazonBenchmark uses `competitor_asin` not `asin` (no `title` field either)
- 7 new tests; full suite 94 passed (baseline was 87)

### T14 Findings

- build_prompt(project_id, slot_index, session=None) added to prompt_engine.py
- owns_session pattern identical to slot_planner.py
- Reads ImageBrief (required, raises E_BUILD_001 if missing), BrandProfile (optional), CompetitorListing (optional)
- brief_json parsed via json.loads with fallback to empty dict on JSONDecodeError/TypeError
- No Gemini call needed — pure DB read + string assembly
- Existing assemble_prompt/generate_slot_prompts untouched
- 7 new tests; full suite 101 passed (baseline was 94, target was ≥100)

## T15: delivery.py (2026-04-18)

- ImageSlot model was NOT pre-existing; created it as new file (not in **init**.py but importing it before Base.metadata.create_all is sufficient)
- owns_session pattern used: `owns_session = session is None; if owns_session: session = get_session()`
- shutil.copy2 for image copy; skip if image_path is None or file missing
- manifest.json written with json.dump; keys: project_id, slots, created_at
- Test fixture uses monkeypatch.chdir(tmp_path) (autouse) so output/ dirs are created in tmp
- 107 total tests passing after this task

## T17: feedback_loop.py activation (2026-04-18)

- ABTestResult model created separately from existing ABTest (different purpose: ABTest tracks A/B between prompt variants, ABTestResult tracks simple variant+score results)
- feedback_loop.py already had 4 functions; added 3 new ones following same patterns
- BrandProfile.guidelines field used to store JSON conclusion from A/B results
- 116 tests passing (baseline was ~107), 6 new tests added

## T16: QA Gate Brand & Text Checks (2026-04-18)

- Lazy Gemini import via `_get_genai()` function, called inside `_call_gemini()` helper
- `_call_gemini()` catches all exceptions and returns empty string on failure
- Degraded mode threshold set to 0.5 (neutral) to avoid breaking existing e2e pipeline
- Dynamic scoring: `100/N` points per check instead of hardcoded 25pts, so adding checks doesn't break score proportions
- E2e test had hardcoded `8×4=32` QA records assertion → updated to `8×6=48`
- `patch("module._get_genai", return_value=mock)` is the clean way to mock the lazy import

## T18: E2E Pipeline Integration Tests (2026-04-18)

- slot_planner uses 1-based slot indices (1-8), not 0-based — affects assertions
- ImageSlot not exported from `pipeline.models.__init__` — import from `pipeline.models.image_slot` directly
- `get_session()` returns raw `Session`, not a context manager — use try/finally
- All models must be imported before `Base.metadata.create_all()` for SQLAlchemy table registration
- `delivery.py` hardcodes `"output"` as base dir, ignores `config.output_dir`
- `brief_generator._call_gemini()` returns `"{}"` without API key → `generate_brief` falls back to `_DEFAULT_BRIEF`
- Full suite: 125 tests passing after adding 6 new E2E tests

## T20: interfaces.md L4 升级 (2026-04-18)

- interfaces.md 从 L2 MVP 升级到 L4（780 → 968 行）
- 新增 L4 模块接口章节：listing_analyzer, review_analyzer, qa_analyzer, brief_generator, slot_planner(L4), prompt_engine.build_prompt, delivery, qa_gate(L4), feedback_loop(L4)
- 错误码表新增 E_BUILD_001（prompt_engine，无 ImageBrief）
- 证据文件写入 `.sisyphus/evidence/task-20-interfaces.txt`
- build_delivery_package 返回目录路径，不是 manifest path（任务说明有误）
- qa_gate L4 共 6 项检查（L2 为 5 项）：新增 brand_consistency, text_accuracy
