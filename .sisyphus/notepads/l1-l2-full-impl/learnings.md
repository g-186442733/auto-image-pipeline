## Wave 0 Findings (2026-04-20)

### Test baseline

- 489 passed (INTACT), 35 failed (pre-existing from test_l5_migration.py — near-term-gaps tests written but not implemented)
- Ignore test_l5_migration.py failures for now — they are intentional red-tests
- Key assertion: ≥489 passed, ≤35 failed (all in test_l5_migration.py)

### Brand tables

- brand_profiles: 0 rows (EMPTY)
- brand_profile_cards: 0 rows (EMPTY)
- Task 1a strategy: simple DROP brand_profiles table + delete brand.py + update imports. NO data migration needed.

### Project conventions

- Test command: PYTHONPATH=. .venv/bin/pytest tests/ -q --ignore=tests/test_e2e_tws.py --ignore=tests/test_e2e_pipeline.py
- Python: .venv/bin/python (NOT python3 or python in PATH)
- DB engine: from pipeline.models import get_engine
- CSS rule: external style.css only, no <style> inline blocks
- No Alembic; use db_migrate.py with idempotent ALTER TABLE

### Gate 5

- Threshold: ≥0.6 PASS, <0.6 FAIL
- Formula: 0.4 _ tag_coverage_norm + 0.4 _ brand_consistency + 0.2 \* resolution_pass

## Task 1a Learnings (2026-04-20)

- Removing a parameterized test entry (brand model from test_l5_migration.py list) reduces passed count by ~4. New baseline: 485 passed.
- Field mapping: brand.tone→brand_tone, brand.color_palette→color_system, brand.font_family→font_preference. brand_name has no equivalent—just drop it.
- Dynamic imports in qa_wave2.py use `__import__("pipeline.models.brand", fromlist=["BrandProfile"])` — must update the module string too.
- prompt_engine.py accesses `.tone` and `.color_palette` on BrandProfile objects in prompt-building logic — field renames propagate into business logic.
- input_layer.py `upsert_brand_profile()` had a hardcoded old field list — needed full rewrite to match new model's 11 optional fields.

## Task 1d — Gemini Vision routing (2026-04-20)
- `config.py` uses dataclass fields with `default_factory=lambda: os.getenv(...)` — added `vision_provider` same way
- `vision_analyzer.py` routing: check `config.vision_provider == "gemini"` then dispatch to `_analyze_image_gemini` vs `_analyze_image_openai`
- `_analyze_image_gemini` downloads image to tempfile then calls `GeminiVisionAdapter.analyze()`
- Tests use `importlib.reload(va)` after monkeypatching env + `cfg_mod.config = cfg_mod.Config()` to pick up new env var
- Registry already had `gemini_vision` registered in `_bootstrap()` — no change needed
- 491 passed after task (was 485 baseline from task 1a)
