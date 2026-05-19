"""
针对 aplus_image_generator.py T5~T9 改动的单元测试。

覆盖点：
  T5  - _fetch_product_context() 读取 target_audience / product_usp / listing_bullets
  T8a - _build_image_prompt() HERO subject_slot 注入 used_by / highlighting
  T8b - _build_image_prompt() LIFESTYLE subject_slot 注入 used_by
  T8c - _build_image_prompt() BRAND_STORY subject_slot 不注入受众标签
  T8d - _build_image_prompt() HERO/LIFESTYLE 无值时不追加空字符串
  T8e - _build_image_prompt() mood_slot 注入 listing_bullets 前 2 条
  T8f - _build_image_prompt() listing_bullets 为空时不追加 conveying
  T8g - _build_image_prompt() listing_bullets 超过 2 条时只取前 2 条
  T9a - _build_image_prompt() 传入 used_compositions → technical_slot 含 avoid 字符串
  T9b - _build_image_prompt() 传入空列表 → 不追加 avoid
  T9c - _build_image_prompt() used_compositions 超 3 条时只取前 3 条
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.layers.aplus_image_generator import (
    _build_image_prompt,
    _comparison_claim_rows,
    _fetch_product_context,
    _normalize_image_size,
    generate_single,
    generate_aplus_images,
)
from pipeline.models.aplus_content import APlusContent
from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.pipeline_run import PipelineRun


def _module(module_type: str, headline: str = "", body_text: str = "") -> APlusContent:
    m = MagicMock(spec=APlusContent)
    m.module_type = module_type
    m.headline = headline
    m.body_text = body_text
    m.id = 1
    return m


def _brand_ctx(**kwargs) -> dict:
    base = {
        "listing_title": "Super Widget Pro",
        "brand_tone": "",
        "color_system": "",
        "photo_style": "",
        "model_type": "",
        "scene_preference": "",
        "composition_preference": "",
        "material_texture": "",
        "target_audience": "",
        "product_usp": "",
        "listing_bullets": "",
    }
    base.update(kwargs)
    return base


class TestFetchProductContextCosmoFields:
    def _make_session(self, brief_data: dict):
        from pipeline.models.project import Project

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        proj = Project()
        proj.id = 1
        proj.name = "test-stub"
        proj.customer_brief = json.dumps(brief_data)
        session.add(proj)
        session.commit()
        return session

    def test_reads_target_audience(self):
        session = self._make_session({"target_audience": "outdoor athletes"})
        ctx = _fetch_product_context(1, session)
        assert ctx["target_audience"] == "outdoor athletes"

    def test_reads_product_usp(self):
        session = self._make_session({"product_usp": "waterproof up to 50m"})
        ctx = _fetch_product_context(1, session)
        assert ctx["product_usp"] == "waterproof up to 50m"

    def test_reads_listing_bullets(self):
        bullets = "- Triple waterproof\n- Lightweight design"
        session = self._make_session({"listing_bullets": bullets})
        ctx = _fetch_product_context(1, session)
        assert ctx["listing_bullets"] == bullets

    def test_defaults_to_empty_string_when_missing(self):
        session = self._make_session({"listing_title": "Widget"})
        ctx = _fetch_product_context(1, session)
        assert ctx["target_audience"] == ""
        assert ctx["product_usp"] == ""
        assert ctx["listing_bullets"] == ""

    def test_returns_all_three_fields_together(self):
        session = self._make_session(
            {
                "target_audience": "busy professionals",
                "product_usp": "saves 2 hours daily",
                "listing_bullets": "- Fast\n- Reliable",
            }
        )
        ctx = _fetch_product_context(1, session)
        assert ctx["target_audience"] == "busy professionals"
        assert ctx["product_usp"] == "saves 2 hours daily"
        assert "Fast" in ctx["listing_bullets"]


class TestComparisonClaims:
    def test_comparison_claims_only_use_supported_facts(self):
        rows = _comparison_claim_rows(
            _brand_ctx(
                listing_title="Headphones with USB-C Charging",
                listing_bullets="Active noise cancelling\nUp to 24 Hours of Playtime",
                product_usp="Plush over-ear cushions for comfort",
            )
        )

        labels = [row[0] for row in rows]
        assert labels == ["Noise Control", "Battery Life", "Comfort"]

    def test_comparison_claims_do_not_invent_battery_without_fact(self):
        rows = _comparison_claim_rows(_brand_ctx(listing_title="Simple Headphones"))

        rendered = " ".join(" ".join(row) for row in rows)
        assert "24 hours" not in rendered
        assert rows == [("Design", "Verified product details", "Generic design")]

    def test_comparison_claims_do_not_treat_unrelated_24_hour_copy_as_battery_fact(self):
        rows = _comparison_claim_rows(
            _brand_ctx(
                listing_title="Support-ready headphones",
                listing_bullets="24-hour customer support response for warranty questions",
            )
        )

        rendered = " ".join(" ".join(row) for row in rows)
        assert "Battery Life" not in rendered
        assert "Up to 24 hours" not in rendered


class TestAmazonUSLanguagePolicy:
    def test_cjk_headline_body_are_not_copied_into_prompt(self):
        prompt = _build_image_prompt(
            _module("BENEFIT", headline="核心优势", body_text="突出产品价值"),
            _brand_ctx(),
        )

        assert "核心优势" not in prompt
        assert "突出产品价值" not in prompt
        assert "Amazon US English-only" in prompt
        assert "no Chinese/CJK" in prompt

    def test_comparison_prompt_enforces_deterministic_english_layout(self):
        prompt = _build_image_prompt(_module("COMPARISON"), _brand_ctx())

        assert "deterministic two-column comparison" in prompt
        assert "This Headphone" in prompt
        assert "Typical Headphones" in prompt
        assert "minimum 36px" in prompt
        assert "no tiny text" in prompt

    def test_brand_story_prompt_avoids_lifestyle_duplicate(self):
        prompt = _build_image_prompt(_module("BRAND_STORY"), _brand_ctx())

        assert "avoid duplicating the Lifestyle" in prompt
        assert "trust" in prompt
        assert "craftsmanship" in prompt


class TestHeroSubjectSlot:
    def test_hero_with_audience_and_usp(self):
        ctx = _brand_ctx(
            target_audience="fitness enthusiasts", product_usp="ultra-grip sole"
        )
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "used by fitness enthusiasts" in prompt
        assert "highlighting ultra-grip sole" in prompt

    def test_hero_with_audience_only(self):
        ctx = _brand_ctx(target_audience="parents with kids")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "used by parents with kids" in prompt
        assert "highlighting" not in prompt

    def test_hero_with_usp_only(self):
        ctx = _brand_ctx(product_usp="30% lighter than competitors")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "highlighting 30% lighter than competitors" in prompt
        assert "used by" not in prompt

    def test_hero_without_audience_and_usp(self):
        ctx = _brand_ctx()
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "used by" not in prompt
        assert "highlighting" not in prompt

    def test_hero_empty_string_not_injected(self):
        ctx = _brand_ctx(target_audience="", product_usp="")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "used by" not in prompt
        assert "highlighting" not in prompt


class TestLifestyleSubjectSlot:
    def test_lifestyle_with_audience(self):
        ctx = _brand_ctx(target_audience="college students")
        prompt = _build_image_prompt(_module("LIFESTYLE"), ctx)
        assert "used by college students" in prompt

    def test_lifestyle_without_audience(self):
        ctx = _brand_ctx()
        prompt = _build_image_prompt(_module("LIFESTYLE"), ctx)
        assert "used by" not in prompt

    def test_lifestyle_ignores_usp(self):
        ctx = _brand_ctx(product_usp="ultra-durable stitching")
        prompt = _build_image_prompt(_module("LIFESTYLE"), ctx)
        assert "highlighting ultra-durable stitching" not in prompt


class TestBrandStorySubjectSlot:
    def test_brand_story_no_audience_injection(self):
        ctx = _brand_ctx(
            target_audience="premium buyers", product_usp="heritage craftsmanship"
        )
        prompt = _build_image_prompt(_module("BRAND_STORY"), ctx)
        assert "used by" not in prompt
        assert "highlighting" not in prompt

    def test_brand_story_contains_brand_heritage(self):
        ctx = _brand_ctx()
        prompt = _build_image_prompt(_module("BRAND_STORY"), ctx)
        assert "brand heritage" in prompt or "craftsmanship" in prompt


class TestMoodSlotBullets:
    def test_bullets_injected_into_mood(self):
        ctx = _brand_ctx(listing_bullets="- Waterproof\n- Lightweight")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "conveying:" in prompt
        assert "Waterproof" in prompt
        assert "Lightweight" in prompt

    def test_empty_bullets_no_conveying(self):
        ctx = _brand_ctx(listing_bullets="")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "conveying:" not in prompt

    def test_only_first_two_bullets_used(self):
        ctx = _brand_ctx(listing_bullets="- A\n- B\n- C\n- D")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "conveying:" in prompt
        assert "A" in prompt
        assert "B" in prompt
        # C 和 D 不应出现（第3、4条被截断）
        assert "; C" not in prompt
        assert "; D" not in prompt

    def test_bullet_chars_stripped(self):
        ctx = _brand_ctx(listing_bullets="• Durable\n- Strong grip")
        prompt = _build_image_prompt(_module("LIFESTYLE"), ctx)
        assert "Durable" in prompt
        assert "Strong grip" in prompt

    def test_single_bullet_injected(self):
        ctx = _brand_ctx(listing_bullets="- Only one feature")
        prompt = _build_image_prompt(_module("HERO"), ctx)
        assert "Only one feature" in prompt

    def test_bullets_not_injected_into_tile_modules(self):
        ctx = _brand_ctx(listing_bullets="- Fast\n- Reliable")
        prompt = _build_image_prompt(
            _module("BENEFIT", headline="Triple protection"), ctx
        )
        # Tile 模块走不同分支，conveying: 不应出现
        assert "conveying:" not in prompt


class TestUsedCompositions:
    def test_avoid_composition_appended_when_provided(self):
        ctx = _brand_ctx()
        comps = ["hero centered", "lifestyle left-aligned"]
        prompt = _build_image_prompt(_module("HERO"), ctx, used_compositions=comps)
        assert "avoid duplicating composition:" in prompt
        assert "hero centered" in prompt
        assert "lifestyle left-aligned" in prompt

    def test_no_avoid_when_empty_list(self):
        ctx = _brand_ctx()
        prompt = _build_image_prompt(_module("HERO"), ctx, used_compositions=[])
        assert "avoid duplicating composition:" not in prompt

    def test_no_avoid_when_none(self):
        ctx = _brand_ctx()
        prompt = _build_image_prompt(_module("HERO"), ctx, used_compositions=None)
        assert "avoid duplicating composition:" not in prompt

    def test_only_first_three_compositions_used(self):
        ctx = _brand_ctx()
        comps = ["comp-A", "comp-B", "comp-C", "comp-D", "comp-E"]
        prompt = _build_image_prompt(_module("HERO"), ctx, used_compositions=comps)
        assert "comp-A" in prompt
        assert "comp-B" in prompt
        assert "comp-C" in prompt
        assert "comp-D" not in prompt
        assert "comp-E" not in prompt

    def test_avoid_not_injected_into_tile_modules(self):
        ctx = _brand_ctx()
        comps = ["hero centered"]
        prompt = _build_image_prompt(
            _module("BENEFIT", headline="Waterproof"), ctx, used_compositions=comps
        )
        # BENEFIT 走 Tile 分支，technical_slot 不含 avoid
        assert "avoid duplicating composition:" not in prompt

    def test_lifestyle_also_gets_avoid(self):
        ctx = _brand_ctx()
        comps = ["hero wide shot"]
        prompt = _build_image_prompt(_module("LIFESTYLE"), ctx, used_compositions=comps)
        assert "avoid duplicating composition: hero wide shot" in prompt

    def test_brand_story_also_gets_avoid(self):
        ctx = _brand_ctx()
        comps = ["centered product shot"]
        prompt = _build_image_prompt(
            _module("BRAND_STORY"), ctx, used_compositions=comps
        )
        assert "avoid duplicating composition: centered product shot" in prompt


class TestImageSizeNormalization:
    def test_normalizes_generated_image_to_declared_size(self, tmp_path):
        from PIL import Image

        path = tmp_path / "wide.png"
        Image.new("RGB", (1959, 803), color=(200, 200, 200)).save(path)

        _normalize_image_size(str(path), "1536x1024")

        with Image.open(path) as img:
            assert img.size == (1536, 1024)

    def test_compresses_generated_image_under_amazon_limit(self, tmp_path):
        import os
        from PIL import Image

        path = tmp_path / "oversized.png"
        Image.effect_noise((1536, 1024), 100).convert("RGB").save(path)
        assert os.path.getsize(path) > 2 * 1024 * 1024

        _normalize_image_size(str(path), "1536x1024")

        assert os.path.getsize(path) <= 2 * 1024 * 1024
        with Image.open(path) as img:
            assert img.size == (1536, 1024)


class TestGenerateSingleSafety:
    def test_wide_module_retry_uses_edit_with_reference(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)
        out_path = tmp_path / "wide.png"
        Image.new("RGB", (1536, 1024), color=(200, 200, 200)).save(out_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        project = Project(
            id=1,
            name="A+ retry safety",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        module = APlusContent(
            id=1,
            project_id=1,
            module_type="HERO",
            headline="Hero",
            body_text="Premium hero banner",
            position_index=0,
        )
        session.add(project)
        session.add(module)
        session.commit()

        adapter = MagicMock()
        adapter.edit.return_value = MagicMock(image_path=str(out_path))

        result = generate_single(1, session=session, adapter=adapter)

        assert result is not None
        adapter.edit.assert_called_once()
        adapter.generate.assert_not_called()
        assert result.reference_image_paths == str(ref_path)
        assert result.image_size == "1536x1024"
        assert "PRESERVE EXACTLY" in result.image_prompt

    def test_comparison_module_uses_programmatic_renderer_not_adapter(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        project = Project(
            id=2,
            name="A+ comparison generation",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro with USB-C Charging",
                    "listing_bullets": "Active noise cancelling\nUp to 24 Hours of Playtime",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        run = PipelineRun(id=20, project_id=2, status="planned")
        module = APlusContent(
            id=2,
            project_id=2,
            module_type="COMPARISON",
            headline="Why it wins",
            body_text="Compare product advantages",
            position_index=0,
        )
        session.add(project)
        session.add(run)
        session.add(module)
        session.commit()

        adapter = MagicMock()

        with patch("pipeline.layers.aplus_qa_gate.APlusQAGate") as gate_cls:
            gate_cls.return_value.run.return_value = {"passed": True}
            result = generate_aplus_images(2, session=session, adapter=adapter)

        assert len(result) == 1
        adapter.edit.assert_not_called()
        adapter.generate.assert_not_called()
        refreshed = session.get(APlusContent, 2)
        assert refreshed is not None
        assert refreshed.image_path.endswith("comparison_2_2.jpg")
        assert (tmp_path / refreshed.image_path).exists()
        assert "Programmatic Amazon US English-only comparison card" in refreshed.image_prompt
        assert "Battery Life" in refreshed.image_prompt

    def test_comparison_retry_uses_programmatic_renderer_not_adapter(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        project = Project(
            id=5,
            name="A+ comparison retry",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro with USB-C Charging",
                    "listing_bullets": "Active noise cancelling\nUp to 24 Hours of Playtime",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        module = APlusContent(
            id=5,
            project_id=5,
            module_type="COMPARISON",
            headline="Why it wins",
            body_text="Compare product advantages",
            image_prompt="QA refined prompt should not force model rendering",
            position_index=0,
        )
        session.add(project)
        session.add(module)
        session.commit()

        adapter = MagicMock()

        result = generate_single(5, session=session, adapter=adapter)

        assert result is not None
        adapter.edit.assert_not_called()
        adapter.generate.assert_not_called()
        refreshed = session.get(APlusContent, 5)
        assert refreshed is not None
        assert refreshed.image_path.endswith("comparison_5_5.jpg")
        assert (tmp_path / refreshed.image_path).exists()
        assert "Programmatic Amazon US English-only comparison card" in refreshed.image_prompt
        assert "Battery Life" in refreshed.image_prompt
        assert refreshed.reference_image_paths == str(ref_path.resolve())

    def test_programmatic_comparison_rolls_back_session_when_save_fails(self, tmp_path, monkeypatch):
        from PIL import Image
        from pipeline.layers import aplus_image_generator

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        project = Project(
            id=6,
            name="A+ comparison rollback",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro",
                    "listing_bullets": "Active noise cancelling",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        module = APlusContent(
            id=6,
            project_id=6,
            module_type="COMPARISON",
            headline="Why it wins",
            body_text="Compare product advantages",
            position_index=0,
        )
        session.add(project)
        session.add(module)
        session.commit()
        adapter = MagicMock()
        rollback_spy = MagicMock(wraps=session.rollback)
        monkeypatch.setattr(session, "rollback", rollback_spy)

        def fail_normalize(image_path: str, size: str) -> None:
            raise OSError("simulated normalize failure")

        monkeypatch.setattr(aplus_image_generator, "_normalize_image_size", fail_normalize)

        with pytest.raises(OSError, match="simulated normalize failure"):
            generate_single(6, session=session, adapter=adapter)

        rollback_spy.assert_called_once()
        adapter.edit.assert_not_called()
        adapter.generate.assert_not_called()

    def test_reference_collection_rejects_paths_outside_allowed_roots(self, tmp_path, monkeypatch):
        from PIL import Image
        from pipeline.layers.aplus_image_generator import _collect_ref_image_paths

        safe_dir = tmp_path / "safe"
        unsafe_dir = tmp_path / "unsafe"
        safe_dir.mkdir()
        unsafe_dir.mkdir()
        safe_path = safe_dir / "white.png"
        unsafe_path = unsafe_dir / "secret.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(safe_path)
        Image.new("RGB", (16, 16), color=(0, 0, 0)).save(unsafe_path)
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(safe_dir))

        paths = _collect_ref_image_paths(
            {
                "white_bg_image_path": str(safe_path),
                "color_variant_image_paths": [str(unsafe_path)],
            },
            "INT_COMPARISON",
        )

        assert paths == [str(safe_path.resolve())]

    def test_reference_collection_rejects_non_images(self, tmp_path, monkeypatch):
        from pipeline.layers.aplus_image_generator import _collect_ref_image_paths

        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        fake_image = tmp_path / "white.png"
        fake_image.write_text("not actually an image")

        paths = _collect_ref_image_paths(
            {"white_bg_image_path": str(fake_image)}, "INT_HERO"
        )

        assert paths == []

    def test_reference_collection_dedupes_paths(self, tmp_path, monkeypatch):
        from PIL import Image
        from pipeline.layers.aplus_image_generator import _collect_ref_image_paths

        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)

        paths = _collect_ref_image_paths(
            {
                "white_bg_image_path": str(ref_path),
                "color_variant_image_paths": [str(ref_path), str(ref_path)],
            },
            "INT_COMPARISON",
        )

        assert paths == [str(ref_path.resolve())]

    def test_tile_retry_uses_existing_refined_prompt(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        out_path = tmp_path / "tile.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)
        Image.new("RGB", (1024, 1024), color=(200, 200, 200)).save(out_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        refined_prompt = "QA refined prompt emphasizing three clear benefit icons"
        project = Project(
            id=3,
            name="A+ tile retry prompt",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        module = APlusContent(
            id=3,
            project_id=3,
            module_type="BENEFIT",
            headline="Benefits",
            body_text="Show feature benefits",
            image_prompt=refined_prompt,
            position_index=0,
        )
        session.add(project)
        session.add(module)
        session.commit()
        adapter = MagicMock()
        adapter.edit.return_value = MagicMock(image_path=str(out_path))

        result = generate_single(3, session=session, adapter=adapter)

        assert result is not None
        _, prompt_arg = adapter.edit.call_args[0]
        assert refined_prompt in prompt_arg
        assert result.image_prompt.endswith(refined_prompt)

    def test_tile_generation_failure_raises_to_qa_gate(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        ref_path = tmp_path / "white.png"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(ref_path)

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        project = Project(
            id=4,
            name="A+ tile retry error",
            customer_brief=json.dumps(
                {
                    "listing_title": "Super Widget Pro",
                    "white_bg_image_path": str(ref_path),
                    "reference_assets": {"white_bg": [str(ref_path)]},
                }
            ),
        )
        module = APlusContent(
            id=4,
            project_id=4,
            module_type="BENEFIT",
            headline="Benefits",
            body_text="Show feature benefits",
            position_index=0,
        )
        session.add(project)
        session.add(module)
        session.commit()
        adapter = MagicMock()
        adapter.edit.side_effect = RuntimeError("adapter failed")

        with pytest.raises(RuntimeError, match="adapter failed"):
            generate_single(4, session=session, adapter=adapter)
