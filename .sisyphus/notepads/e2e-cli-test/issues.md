# E2E CLI Test Issues

## 2026-04-20: Full Pipeline Run (Project 5, ASIN B0CJTXBFPK)

### Issue 1: DB Schema Drift — Missing Columns (CRITICAL)

- **Symptom**: `sqlite3.OperationalError: table projects has no column named live_at`
- **Root Cause**: Model classes have columns (`live_at`, `drl_triggered_at`, `tenant_id`, `lora_type`, `parent_category_lora_id`) that were never migrated to the existing DB
- **Affected Tables**: ALL 31 tables missing `tenant_id`; `projects` missing `live_at`/`drl_triggered_at`; `brand_profile_cards` missing `lora_type`/`parent_category_lora_id`
- **Fix Applied**: Manual ALTER TABLE statements (idempotent)
- **Action Needed**: Need a startup migration routine that syncs ALL model columns to DB, not just the 2 ALTER TABLE statements in `__main__.py._migrate_schema()`

### Issue 2: Category Must Be Numeric Keepa ID

- **Symptom**: `E_AMAZON_005: Category must be a numeric Keepa category ID (e.g. '172541'), not a text name (got: 'TWS Earbuds')`
- **Impact**: `fetch_category_top` fails → no `AmazonBenchmark` rows → `slot_planner` returns 0 slots
- **Action Needed**: Brief schema should validate/document that `category` must be a Keepa numeric ID, or auto-resolve text names

### Issue 3: Slot Planner Returns 0 Slots When No Benchmarks

- **Symptom**: `E_PLANNER_001: No AmazonBenchmark rows for project 5 — returning empty slot plan`
- **Impact**: No slots → no prompts generated → `step_generate` produces 0 images → pipeline effectively stops
- **Action Needed**: Slot planner should have a fallback (e.g., default 7-slot plan) when benchmark data is missing

### Issue 4: QA Gate Always Returns score=0

- **Symptom**: `LLM QA evaluation failed (empty response); returning safe default` → score=0, passed=False
- **Impact**: QA retry loop exhausts 3 attempts, all fail. QA effectively non-functional in this run.
- **Possible Cause**: Gemini/OpenAI QA evaluation endpoint returning empty response

### Issue 5: ASIN Data Mismatch

- **Symptom**: ASIN B0CJTXBFPK returned "GVVDLW Flannel Fleece Throw Blanket" instead of Anker Soundcore P40i
- **Impact**: Competitor analysis based on wrong product data
- **Possible Cause**: Keepa API returning stale/wrong data for this ASIN, or ASIN mapping issue

### Issue 6: Report Step Missing Column

- **Symptom**: `no such column: brand_profile_cards.lora_type`
- **Resolution**: Same as Issue 1 — DB schema drift
