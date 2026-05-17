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

## Result (1-slot run)

```
MAIN: data/images/gpt_image/e2c3815b7784.png (1,137,865 bytes, exists=True)
tokens: in=135, out=1056
```

**Status**: PASSED — 1/1

## Result (8-slot full run, 2026-04-18)

```
MAIN:         bbe703a61f97.png  1,175,255 bytes  in=135 out=1056
ALT1:         b71c822748dd.png  1,497,991 bytes  in=112 out=1056
ALT2:         f63759e0a429.png  1,241,698 bytes  in=115 out=1056
ALT3:         b7526715002e.png  1,463,202 bytes  in=121 out=1056
ALT4:         213ff52215cc.png  1,559,072 bytes  in=112 out=1056
ALT5:         251fcd2aa34e.png  1,399,933 bytes  in=120 out=1056
ALT6:         8c5f52a78a7d.png  1,384,734 bytes  in=121 out=1056
VIDEO_THUMB:  90bb1ac34932.png  1,470,475 bytes  in=130 out=1056
```

**Status**: 🎉 PASSED — 8/8 images generated successfully
**Total output tokens**: 8,448 (1,056 × 8)
**Total image size**: ~11.2 MB
