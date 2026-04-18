
## APlusContent Model & Upload Endpoint (2026-04-19)
- Project model 原先没有任何 relationship，添加 back_populates 需同时 import relationship
- Flask upload 用 `file.read()` 检查大小后需 `file.seek(0)` 或直接写 `file_data`（选了后者更高效）
- `secure_filename` 来自 `werkzeug.utils`，Flask 已依赖 werkzeug
- 测试中用 `monkeypatch.chdir(tmp_path)` 隔离 uploads 目录写入

## brief_generator multi-slot refactor (2026-04-19)

- Changed `generate_brief()` return type from `ImageBrief` → `list[ImageBrief]`
- Each slot from Gemini response gets its own row with `slot_index=i`
- 0 slots → empty list + `log.warning`, no exception
- `source_analysis_ids` defaults to `json.dumps([])` until callers supply real IDs
- Each brief row stores individual slot JSON (not the full `{"slots":[...]}` wrapper)
- Orchestrator: `brief = ...` renamed to `briefs = ...`, log updated to show slot count
- Existing tests in `test_brief_generator.py` updated (return type, DB count assertions)
- `test_e2e_pipeline.py` and `test_orchestrator_brief.py` also needed updates for list return
- `test_orchestrator_brief.py::test_brief_with_partial_upstream_failure` had mock returning `{"slots":[]}` — updated to valid 1-slot JSON to preserve test intent
- New file: `tests/test_brief_multi_slot.py` — 3-slot happy path + 0-slot warning test
- Final: 204 passed, 0 failed

## step_deliver (2026-04-19)
- `build_delivery_package` uses local import inside `step_deliver` — consistent with `_call_vision` pattern
- Guard: `not delivery_path or not any(Path(delivery_path).iterdir())` covers both empty string and empty dir
- Patch target for tests: `pipeline.layers.delivery.build_delivery_package` (the local import resolves through the module, not orchestrator namespace)
- `run_full_pipeline` return dict now includes `delivery_path` (may be None if guard triggered)
