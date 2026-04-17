# L3 E2E Real Generation Test — QA Evidence

**Date**: 2026-04-18
**Test**: `tests/test_e2e_real_gen.py`
**Adapter**: gpt-image-1 via 147AI (`https://api.147ai.cn/v1`)

## Test Flow

1. `create_all()` — DB initialized
2. `create_project(brief)` — project id=2, asin=B0E2ETEST0
3. Insert 8 fake `AmazonBenchmark` rows (bypass Keepa)
4. `generate_slot_plan(pid)` — 8 slots created
5. Copy default template (project_id=0, slot_index=1) → project-specific
6. `generate_slot_prompts(pid)` — 1 prompt assembled (MAIN slot)
7. `adapter.generate(prompt)` — real gpt-image-1 API call

## Result

```
MAIN: data/images/gpt_image/e2c3815b7784.png (1,137,865 bytes, exists=True)
tokens: in=135, out=1056
```

**Status**: 🎉 PASSED — 1/1 images generated successfully

## Cost Control

Only 1 slot (MAIN) tested. Set `E2E_ALL_SLOTS=1` to test all 8.
