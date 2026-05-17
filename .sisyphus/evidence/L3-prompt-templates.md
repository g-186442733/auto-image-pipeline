# QA Evidence: L3 Prompt Template Loading & Assembly

**Date**: 2026-04-18
**Task**: T-L3-6 — Validate prompt template seeding and Jinja2 prompt assembly

## Test: seed_default_templates()

- **Input**: 8 JSON files in `templates/` directory (slot_1 through slot_8)
- **Expected**: 8 PromptAsset records created with project_id=0
- **Result**: ✅ PASS — 8 templates loaded, all slots 1-8 present, model_name=gpt-image-1

## Test: generate_slot_prompts()

- **Setup**: Created test project "Test Widget Pro" (electronics), 8 SlotPlans with realistic tags, copied templates as project-specific PromptAssets
- **Expected**: 8 rendered prompts with no raw Jinja2 `{{ }}` markers, negative_prompt appended
- **Result**: ✅ PASS — All 8 slots rendered:
  - MAIN: Hero shot, white bg, centered composition ✅
  - ALT1: Lifestyle, rule-of-thirds ✅
  - ALT2: Infographic, split-screen ✅
  - ALT3: Detail close-up, macro ✅
  - ALT4: Comparison, side-by-side ✅
  - ALT5: Packaging, flat-lay ✅
  - ALT6: Lifestyle/model, environmental ✅
  - VIDEO_THUMB: Cinematic, dynamic ✅
- **Jinja2 Rendering**: All `{{ subject }}`, `{{ composition }}`, `{{ tone }}`, `{{ constraints }}` variables correctly substituted
- **Negative Prompts**: All 8 prompts include `--no ...` suffix ✅
- **Conditional Blocks**: `{% if constraints %}` / `{% if environment %}` / `{% if camera %}` render correctly (constraints shown, environment/camera omitted when empty) ✅

## Test Script

`tests/test_prompt_templates.py` — reproducible, run with `.venv/bin/python tests/test_prompt_templates.py`

## Verdict

**PASS** — Prompt template system fully functional.
