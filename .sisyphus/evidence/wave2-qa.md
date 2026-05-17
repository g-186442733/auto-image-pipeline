# Wave 2 QA Evidence

**Date**: 2026-04-17
**Runner**: `.venv/bin/python -m tests.qa_wave2`
**Result**: 26 passed, 0 failed out of 26

## T5: input_layer (5/5)
- ✅ create_project happy path
- ✅ create_project missing fields → E_INPUT_001
- ✅ create_project invalid ASIN → E_INPUT_002
- ✅ upsert_brand_profile create + update
- ✅ upsert_brand_profile bad project → E_INPUT_003

## T6: amazon_data (5/5)
- ✅ fetch_category_top returns 3 benchmarks
- ✅ fetch_category_top empty → E_AMAZON_002
- ✅ fetch_asin_detail parses correctly
- ✅ scrape_listing_images returns 3 URLs
- ✅ fetch_category_top no key → E_AMAZON_001

## T7: vision_analyzer (4/4)
- ✅ analyze_image returns correct dict
- ✅ analyze_image no key → E_VISION_001
- ✅ analyze_image bad URL → E_VISION_002
- ✅ analyze_competitor_listing returns 2 results

## T8: prompt_manager (6/6)
- ✅ create_prompt_asset happy path
- ✅ create_prompt_asset bad project → E_PROMPT_001
- ✅ create_prompt_asset bad slot → E_PROMPT_002
- ✅ update_prompt_asset increments version
- ✅ seed_default_templates imports 1 template
- ✅ seed_default_templates missing dir → 0

## T9: prompt_engine (6/6)
- ✅ assemble_prompt renders Jinja2 + negative_prompt
- ✅ assemble_prompt with brand_profile appends tone
- ✅ assemble_prompt missing keys → E_ENGINE_001
- ✅ assemble_prompt bad id → E_PROMPT_003
- ✅ generate_slot_prompts returns dict with at least 1 slot
- ✅ generate_slot_prompts no plan → E_ENGINE_002
