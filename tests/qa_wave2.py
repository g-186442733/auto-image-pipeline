"""Wave 2 QA scenarios — T5 through T9.

Run: .venv/bin/python -m tests.qa_wave2
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

# ── Setup in-memory DB BEFORE importing any pipeline modules ──
os.environ["AIP_DB_URL"] = "sqlite:///:memory:"
os.environ["AIP_DB_PATH"] = ":memory:"

import pipeline.models.base as base_mod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_mem_engine = create_engine("sqlite:///:memory:", echo=False)
_mem_session_factory = sessionmaker(bind=_mem_engine)

base_mod._engine = _mem_engine
base_mod._SessionLocal = _mem_session_factory

from pipeline.models.base import Base

Base.metadata.create_all(_mem_engine)

# Now safe to import layers
from pipeline.layers.input_layer import create_project, upsert_brand_profile
from pipeline.layers.amazon_data import (
    fetch_category_top,
    fetch_asin_detail,
    scrape_listing_images,
)
from pipeline.layers.vision_analyzer import analyze_image, analyze_competitor_listing
from pipeline.layers.prompt_manager import (
    create_prompt_asset,
    update_prompt_asset,
    seed_default_templates,
)
from pipeline.layers.prompt_engine import assemble_prompt, generate_slot_prompts
from pipeline.config import config
from pipeline.models.slot_plan import SlotPlan

passed = 0
failed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"  ✅ {name}")


def fail(name: str, err):
    global failed
    failed += 1
    print(f"  ❌ {name}: {err}")


# ═══════════════════════════════════════════
# T5 — input_layer
# ═══════════════════════════════════════════
print("\n── T5: input_layer ──")

# T5-1: create_project happy path
try:
    proj = create_project(
        {"name": "Test Product", "asin": "B0TESTAA01", "category": "Electronics"}
    )
    assert proj.id is not None
    assert proj.status == "draft"
    assert proj.asin == "B0TESTAA01"
    ok("create_project happy path")
except Exception as e:
    fail("create_project happy path", e)

# T5-2: missing fields
try:
    create_project({"name": "No ASIN"})
    fail("create_project missing fields", "should have raised ValueError")
except ValueError as e:
    assert "E_INPUT_001" in str(e)
    ok("create_project missing fields → E_INPUT_001")
except Exception as e:
    fail("create_project missing fields", e)

# T5-3: invalid ASIN format
try:
    create_project({"name": "Bad", "asin": "INVALID", "category": "X"})
    fail("create_project invalid ASIN", "should have raised ValueError")
except ValueError as e:
    assert "E_INPUT_002" in str(e)
    ok("create_project invalid ASIN → E_INPUT_002")
except Exception as e:
    fail("create_project invalid ASIN", e)

# T5-4: upsert_brand_profile
try:
    bp = upsert_brand_profile({"project_id": proj.id, "brand_tone": "premium"})
    assert bp.brand_tone == "premium"
    # update
    bp2 = upsert_brand_profile({"project_id": proj.id, "brand_tone": "luxury"})
    assert bp2.id == bp.id  # same record updated
    ok("upsert_brand_profile create + update")
except Exception as e:
    fail("upsert_brand_profile", e)

# T5-5: upsert_brand_profile bad project
try:
    upsert_brand_profile({"project_id": 99999, "brand_tone": "Ghost"})
    fail("upsert_brand_profile bad project", "should have raised ValueError")
except ValueError as e:
    assert "E_INPUT_003" in str(e)
    ok("upsert_brand_profile bad project → E_INPUT_003")
except Exception as e:
    fail("upsert_brand_profile bad project", e)


# ═══════════════════════════════════════════
# T6 — amazon_data
# ═══════════════════════════════════════════
print("\n── T6: amazon_data ──")

# T6-1: fetch_category_top (mock HTTP)
try:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "asinList": ["B0AAAA0001", "B0AAAA0002", "B0AAAA0003"]
    }

    with (
        patch("pipeline.layers.amazon_data._api_key", return_value="FAKE_KEY"),
        patch(
            "pipeline.layers.amazon_data._get", return_value=fake_resp.json.return_value
        ),
        patch("pipeline.layers.amazon_data.time"),
    ):
        results = fetch_category_top("Electronics", market="US", top_n=3)
        assert len(results) == 3
        assert results[0].competitor_asin == "B0AAAA0001"
        ok("fetch_category_top returns 3 benchmarks")
except Exception as e:
    fail("fetch_category_top", e)

# T6-2: fetch_category_top empty → E_AMAZON_002
try:
    with (
        patch("pipeline.layers.amazon_data._api_key", return_value="FAKE_KEY"),
        patch("pipeline.layers.amazon_data._get", return_value={"asinList": []}),
        patch("pipeline.layers.amazon_data.time"),
    ):
        fetch_category_top("NonExistent")
    fail("fetch_category_top empty", "should raise")
except ValueError as e:
    assert "E_AMAZON_002" in str(e)
    ok("fetch_category_top empty → E_AMAZON_002")
except Exception as e:
    fail("fetch_category_top empty", e)

# T6-3: fetch_asin_detail
try:
    detail_resp = {
        "products": [
            {
                "title": "Test Widget",
                "csv": [[100, 2999]],
                "reviewCount": 150,
                "rating": 45,
                "salesRanks": {"12345": [1, 2, 50]},
            }
        ]
    }
    with (
        patch("pipeline.layers.amazon_data._api_key", return_value="FAKE_KEY"),
        patch("pipeline.layers.amazon_data._get", return_value=detail_resp),
        patch("pipeline.layers.amazon_data.time"),
    ):
        detail = fetch_asin_detail("B0TESTAA01")
        assert detail["title"] == "Test Widget"
        assert detail["bsr_rank"] == 50
        ok("fetch_asin_detail parses correctly")
except Exception as e:
    fail("fetch_asin_detail", e)

# T6-4: scrape_listing_images
try:
    img_resp = {
        "products": [
            {
                "imagesCSV": "41abc,51def,61ghi",
            }
        ]
    }
    with (
        patch("pipeline.layers.amazon_data._api_key", return_value="FAKE_KEY"),
        patch("pipeline.layers.amazon_data._get", return_value=img_resp),
        patch("pipeline.layers.amazon_data.time"),
    ):
        urls = scrape_listing_images("B0TESTAA01")
        assert len(urls) == 3
        assert "41abc" in urls[0]
        ok("scrape_listing_images returns 3 URLs")
except Exception as e:
    fail("scrape_listing_images", e)

# T6-5: missing API key
try:
    original_key = config.keepa_api_key
    config.keepa_api_key = ""
    fetch_category_top("Electronics")
    fail("fetch_category_top no key", "should raise")
except ValueError as e:
    assert "E_AMAZON_001" in str(e)
    ok("fetch_category_top no key → E_AMAZON_001")
except Exception as e:
    fail("fetch_category_top no key", e)
finally:
    config.keepa_api_key = original_key


# ═══════════════════════════════════════════
# T7 — vision_analyzer
# ═══════════════════════════════════════════
print("\n── T7: vision_analyzer ──")

# T7-1: analyze_image (mock everything)
try:
    config.openai_api_key = "FAKE_KEY"
    config.openai_base_url = "https://fake.openai.com/v1"

    mock_head = MagicMock()
    mock_head.status_code = 200

    vision_result = {
        "intent_tag": "INT_HERO",
        "role_tags": ["ROLE_PRODUCT", "ROLE_BG"],
        "composition": "centered product",
        "color_palette": ["#FFFFFF", "#000000"],
        "text_detected": False,
        "quality_score": 85,
    }
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.raise_for_status = MagicMock()
    mock_post_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(vision_result)}}]
    }

    with (
        patch("pipeline.layers.vision_analyzer.httpx.head", return_value=mock_head),
        patch(
            "pipeline.layers.vision_analyzer.httpx.post", return_value=mock_post_resp
        ),
    ):
        result = analyze_image("https://example.com/img.jpg")
        assert result["intent_tag"] == "INT_HERO"
        assert result["quality_score"] == 85
        ok("analyze_image returns correct dict")
except Exception as e:
    fail("analyze_image", e)

# T7-2: missing API key
try:
    config.openai_api_key = ""
    analyze_image("https://example.com/img.jpg")
    fail("analyze_image no key", "should raise")
except ValueError as e:
    assert "E_VISION_001" in str(e)
    ok("analyze_image no key → E_VISION_001")
except Exception as e:
    fail("analyze_image no key", e)
finally:
    config.openai_api_key = "FAKE_KEY"

# T7-3: inaccessible image URL
try:
    mock_head_404 = MagicMock()
    mock_head_404.status_code = 404
    with patch(
        "pipeline.layers.vision_analyzer.httpx.head", return_value=mock_head_404
    ):
        analyze_image("https://example.com/missing.jpg")
    fail("analyze_image bad URL", "should raise")
except ValueError as e:
    assert "E_VISION_002" in str(e)
    ok("analyze_image bad URL → E_VISION_002")
except Exception as e:
    fail("analyze_image bad URL", e)

# T7-4: analyze_competitor_listing (mock scrape + analyze)
try:
    with (
        patch(
            "pipeline.layers.vision_analyzer.scrape_listing_images",
            return_value=["https://img1.jpg", "https://img2.jpg"],
        ),
        patch(
            "pipeline.layers.vision_analyzer.analyze_image", return_value=vision_result
        ),
    ):
        results = analyze_competitor_listing("B0TESTAA01")
        assert len(results) == 2
        ok("analyze_competitor_listing returns 2 results")
except Exception as e:
    fail("analyze_competitor_listing", e)


# ═══════════════════════════════════════════
# T8 — prompt_manager
# ═══════════════════════════════════════════
print("\n── T8: prompt_manager ──")

# T8-1: create_prompt_asset (uses proj from T5)
try:
    pa = create_prompt_asset(
        project_id=proj.id,
        slot_index=1,
        prompt_text="A {{subject}} on {{environment}} background",
        negative_prompt="blurry, low quality",
        model_name="flux-1.1-pro",
    )
    assert pa.id is not None
    assert pa.version == 1
    ok("create_prompt_asset happy path")
except Exception as e:
    fail("create_prompt_asset", e)

# T8-2: bad project_id
try:
    create_prompt_asset(project_id=99999, slot_index=1, prompt_text="x")
    fail("create_prompt_asset bad project", "should raise")
except ValueError as e:
    assert "E_PROMPT_001" in str(e)
    ok("create_prompt_asset bad project → E_PROMPT_001")
except Exception as e:
    fail("create_prompt_asset bad project", e)

# T8-3: bad slot_index
try:
    create_prompt_asset(project_id=proj.id, slot_index=99, prompt_text="x")
    fail("create_prompt_asset bad slot", "should raise")
except ValueError as e:
    assert "E_PROMPT_002" in str(e)
    ok("create_prompt_asset bad slot → E_PROMPT_002")
except Exception as e:
    fail("create_prompt_asset bad slot", e)

# T8-4: update_prompt_asset
try:
    pa2 = update_prompt_asset(pa.id, prompt_text="Updated prompt")
    assert pa2.version == 2
    assert pa2.prompt_text == "Updated prompt"
    ok("update_prompt_asset increments version")
except Exception as e:
    fail("update_prompt_asset", e)

# T8-5: seed_default_templates with temp dir
try:
    with tempfile.TemporaryDirectory() as tmpdir:
        template_data = {
            "slot_index": 2,
            "prompt_text": "Template prompt for slot 2",
            "negative_prompt": "bad quality",
            "model_name": "flux-1.1-pro",
        }
        with open(os.path.join(tmpdir, "tpl1.json"), "w") as f:
            json.dump(template_data, f)

        config.templates_dir = tmpdir
        count = seed_default_templates()
        assert count == 1
        ok("seed_default_templates imports 1 template")
except Exception as e:
    fail("seed_default_templates", e)

# T8-6: seed with nonexistent dir
try:
    config.templates_dir = "/nonexistent/path"
    count = seed_default_templates()
    assert count == 0
    ok("seed_default_templates missing dir → 0")
except Exception as e:
    fail("seed_default_templates missing dir", e)


# ═══════════════════════════════════════════
# T9 — prompt_engine
# ═══════════════════════════════════════════
print("\n── T9: prompt_engine ──")

# T9-1: assemble_prompt
try:
    # First recreate a prompt asset with Jinja2 template
    pa3 = create_prompt_asset(
        project_id=proj.id,
        slot_index=3,
        prompt_text="A {{ subject }} in {{ environment }}, {{ composition }} layout",
        negative_prompt="blurry",
        model_name="flux-1.1-pro",
    )

    variables = {
        "composition": "centered",
        "subject": "wireless charger",
        "environment": "marble table",
        "camera": "eye-level",
        "tone": "premium",
        "constraints": "no text overlay",
    }
    result = assemble_prompt(pa3.id, variables)
    assert "wireless charger" in result
    assert "marble table" in result
    assert "--no blurry" in result
    ok("assemble_prompt renders Jinja2 + negative_prompt")
except Exception as e:
    fail("assemble_prompt", e)

# T9-2: assemble_prompt with brand_profile
try:
    from pipeline.models.base import get_session as _gs

    sess = _gs()
    bp_obj = (
        sess.query(
            __import__(
                "pipeline.models.brand_profile", fromlist=["BrandProfile"]
            ).BrandProfile
        )
        .filter_by(project_id=proj.id)
        .first()
    )
    sess.close()

    if bp_obj:
        result_with_brand = assemble_prompt(pa3.id, variables, brand_profile=bp_obj)
        assert "Brand tone: premium" in result_with_brand
        ok("assemble_prompt with brand_profile appends tone")
    else:
        fail("assemble_prompt with brand", "brand profile not found")
except Exception as e:
    fail("assemble_prompt with brand", e)

# T9-3: missing variable keys
try:
    assemble_prompt(pa3.id, {"composition": "x"})
    fail("assemble_prompt missing keys", "should raise")
except ValueError as e:
    assert "E_ENGINE_001" in str(e)
    ok("assemble_prompt missing keys → E_ENGINE_001")
except Exception as e:
    fail("assemble_prompt missing keys", e)

# T9-4: bad prompt_asset_id
try:
    assemble_prompt(99999, variables)
    fail("assemble_prompt bad id", "should raise")
except ValueError as e:
    assert "E_PROMPT_003" in str(e)
    ok("assemble_prompt bad id → E_PROMPT_003")
except Exception as e:
    fail("assemble_prompt bad id", e)

# T9-5: generate_slot_prompts (needs SlotPlan + PromptAsset)
try:
    sess = _gs()
    sp = SlotPlan(
        project_id=proj.id,
        slot_index=3,
        layout_tag="centered",
        style_tag="premium",
        color_tag="neutral palette",
        description="wireless charger hero shot",
    )
    sess.add(sp)
    sess.commit()
    sess.close()

    result = generate_slot_prompts(proj.id)
    assert len(result) >= 1
    ok("generate_slot_prompts returns dict with at least 1 slot")
except Exception as e:
    fail("generate_slot_prompts", e)

# T9-6: generate_slot_prompts no SlotPlan
try:
    generate_slot_prompts(99999)
    fail("generate_slot_prompts no plan", "should raise")
except ValueError as e:
    assert "E_ENGINE_002" in str(e)
    ok("generate_slot_prompts no plan → E_ENGINE_002")
except Exception as e:
    fail("generate_slot_prompts no plan", e)


# ═══════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════
print(f"\n{'=' * 50}")
print(f"Wave 2 QA: {passed} passed, {failed} failed out of {passed + failed}")
print(f"{'=' * 50}")
sys.exit(0 if failed == 0 else 1)
