"""A+ 内容生成器测试 — TDD first."""

import json
import os
import sys
from unittest.mock import patch, MagicMock, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.aplus_content import APlusContent


SAMPLE_PROJECT_ID = 42

MODULE_TYPES = [
    "HERO",
    "BENEFIT",
    "DETAIL",
    "LIFESTYLE",
    "COMPARISON",
    "BRAND_STORY",
    "CROSS_SELL",
]

FAKE_APLUS_RESPONSE = json.dumps(
    {
        "modules": [
            {
                "module_type": "HERO",
                "headline": "极致音质体验",
                "body": "专业级降噪，沉浸式聆听",
                "layout": "full_width",
            },
            {
                "module_type": "BENEFIT",
                "headline": "全天候舒适佩戴",
                "body": "人体工学设计，轻若无物",
                "layout": "text_left_image_right",
            },
            {
                "module_type": "DETAIL",
                "headline": "精密工艺细节",
                "body": "航空级铝合金框架，耐久可靠",
                "layout": "image_left_text_right",
            },
            {
                "module_type": "LIFESTYLE",
                "headline": "随心所欲的生活方式",
                "body": "从通勤到健身，无缝切换场景",
                "layout": "full_width",
            },
            {
                "module_type": "COMPARISON",
                "headline": "对比同类产品",
                "body": "在降噪和音质方面超越竞品",
                "layout": "comparison_table",
            },
            {
                "module_type": "BRAND_STORY",
                "headline": "源于对音乐的热爱",
                "body": "十年专注音频技术研发",
                "layout": "text_left_image_right",
            },
            {
                "module_type": "CROSS_SELL",
                "headline": "搭配推荐",
                "body": "搭配耳机支架和收纳盒，体验更完整",
                "layout": "grid_3col",
            },
        ]
    }
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestGenerateAplusStoryboard:
    """测试 generate_aplus_storyboard 函数。"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_generates_7_records(self, mock_gemini, db_session):
        """应生成恰好7条 APlusContent 记录。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        assert len(result) == 7
        assert all(isinstance(r, APlusContent) for r in result)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_all_module_types_present(self, mock_gemini, db_session):
        """应包含全部7种 module_type。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        types = [r.module_type for r in result]
        assert sorted(types) == sorted(MODULE_TYPES)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_position_index_sequential(self, mock_gemini, db_session):
        """position_index 应为 0-6 连续排列。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        indices = sorted(r.position_index for r in result)
        assert indices == list(range(7))

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_records_written_to_db(self, mock_gemini, db_session):
        """记录应写入数据库。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        records = db_session.query(APlusContent).all()
        assert len(records) == 7
        assert all(r.project_id == SAMPLE_PROJECT_ID for r in records)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_headline_not_empty(self, mock_gemini, db_session):
        """每条记录的 headline 不应为空。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        for r in result:
            assert r.headline and len(r.headline) > 0

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_correct_project_id(self, mock_gemini, db_session):
        """每条记录的 project_id 应正确。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        result = generate_aplus_storyboard(99, session=db_session)
        assert all(r.project_id == 99 for r in result)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_gemini_failure_returns_defaults(self, mock_gemini, db_session):
        """LLM 失败时应 raise。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.side_effect = Exception("API error")
        with pytest.raises(Exception):
            generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_no_api_key_returns_defaults(self, db_session):
        """无 API key 时应返回默认模块列表。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        assert isinstance(result, list)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_invalid_json_returns_defaults(self, mock_gemini, db_session):
        """无效 JSON 响应时应返回默认模块列表。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = "not valid json {{{{"
        result = generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        assert isinstance(result, list)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_clears_existing_records(self, mock_gemini, db_session):
        """重新生成时应清除旧记录。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = FAKE_APLUS_RESPONSE
        generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        assert db_session.query(APlusContent).count() == 7

        # 再次生成，应清除旧的再写入新的
        generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)
        assert db_session.query(APlusContent).count() == 7


def _make_module(module_type: str, headline: str = "测试标题") -> APlusContent:
    """构造最简 APlusContent 对象（不写库）。"""
    m = APlusContent()
    m.module_type = module_type
    m.headline = headline
    m.body_text = ""
    return m


class TestLightingSlot:
    """_build_image_prompt 按模块类型注入正确灯光词（T1 验收）。"""

    def _prompt(self, module_type: str) -> str:
        from pipeline.layers.aplus_image_generator import _build_image_prompt

        return _build_image_prompt(_make_module(module_type), {})

    def test_hero_uses_key_fill_rim_light(self):
        """HERO 模块应包含 key light + fill light + rim light 三点打光词。"""
        p = self._prompt("HERO")
        assert "key light" in p
        assert "fill light" in p
        assert "rim light" in p

    def test_lifestyle_uses_window_light(self):
        """LIFESTYLE 模块应包含自然窗光词。"""
        p = self._prompt("LIFESTYLE")
        assert "window light" in p
        assert "5500K" in p

    def test_brand_story_uses_cinematic_light(self):
        """BRAND_STORY 模块应包含电影感灯光词。"""
        p = self._prompt("BRAND_STORY")
        assert "cinematic" in p
        assert "4500K" in p

    def test_detail_uses_ring_flash(self):
        """DETAIL 模块应包含 ring flash 微距灯光词。"""
        p = self._prompt("DETAIL")
        assert "ring flash" in p
        assert "macro" in p

    def test_benefit_uses_soft_box(self):
        """BENEFIT 模块应包含柔光箱词。"""
        p = self._prompt("BENEFIT")
        assert "soft box" in p

    def test_no_photorealistic_in_wide_technical(self):
        """宽幅模块 technical 槽位不应出现劣化词 photorealistic。"""
        p = self._prompt("HERO")
        assert "photorealistic" not in p.lower()

    def test_hyperrealistic_in_wide_technical(self):
        """宽幅模块 technical 槽位应包含 hyperrealistic。"""
        p = self._prompt("HERO")
        assert "hyperrealistic" in p.lower()

    def test_no_photorealistic_in_tile_technical(self):
        """Tile 模块 technical 槽位不应出现劣化词 photorealistic。"""
        p = self._prompt("BENEFIT")
        assert "photorealistic" not in p.lower()

    def test_hyperrealistic_in_tile_technical(self):
        """Tile 模块 technical 槽位应包含 hyperrealistic。"""
        p = self._prompt("DETAIL")
        assert "hyperrealistic" in p.lower()

    def test_wide_technical_contains_focal_length(self):
        """宽幅模块 technical 槽位应包含焦距参数。"""
        p = self._prompt("LIFESTYLE")
        assert "85mm" in p

    def test_tile_technical_contains_aperture(self):
        """Tile 模块 technical 槽位应包含光圈参数。"""
        p = self._prompt("BENEFIT")
        assert "f/5.6" in p or "f/" in p


# ─────────────────────────────────────────────────────────────────────────────
# T2 _build_style_anchor 测试
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildStyleAnchor:
    """_build_style_anchor 生成 listing 级风格锚点。"""

    def test_returns_string(self):
        from pipeline.layers.aplus_image_generator import _build_style_anchor

        result = _build_style_anchor({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_color_system_when_present(self):
        from pipeline.layers.aplus_image_generator import _build_style_anchor

        result = _build_style_anchor({"color_system": "navy blue + gold"})
        assert "navy blue + gold" in result

    def test_includes_brand_tone_when_present(self):
        from pipeline.layers.aplus_image_generator import _build_style_anchor

        result = _build_style_anchor({"brand_tone": "luxury"})
        assert "luxury" in result

    def test_consistent_temperature_always_present(self):
        from pipeline.layers.aplus_image_generator import _build_style_anchor

        result = _build_style_anchor({})
        assert "lighting color temperature" in result


# ─────────────────────────────────────────────────────────────────────────────
# TILE 参考图修复测试
# ─────────────────────────────────────────────────────────────────────────────


class TestTileModuleRefImage:
    """_generate_tile_module_image 在有/无参考图时分别走正确分支。"""

    def _make_adapter(self):
        adapter = MagicMock()
        result = MagicMock()
        result.image_path = "/fake/output.png"
        adapter.edit.return_value = result
        adapter.generate.return_value = result
        return adapter

    def _make_session(self):
        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.rollback = MagicMock()
        return session

    def test_tile_uses_edit_when_ref_images_provided(self):
        """有参考图时应调用 adapter.edit，不调用 adapter.generate。"""
        from pipeline.layers.aplus_image_generator import _generate_tile_module_image

        module = _make_module("BENEFIT")
        module.id = 1
        module.project_id = 1
        adapter = self._make_adapter()
        session = self._make_session()

        _generate_tile_module_image(
            module, {}, adapter, session, ref_image_paths=["/fake/white_bg.png"]
        )

        adapter.edit.assert_called_once()
        adapter.generate.assert_not_called()

    def test_tile_falls_back_to_generate_without_ref_images(self):
        """无参考图时应降级为 adapter.generate，不调用 adapter.edit。"""
        from pipeline.layers.aplus_image_generator import _generate_tile_module_image

        module = _make_module("DETAIL")
        module.id = 2
        module.project_id = 1
        adapter = self._make_adapter()
        session = self._make_session()

        _generate_tile_module_image(module, {}, adapter, session, ref_image_paths=None)

        adapter.generate.assert_called_once()
        adapter.edit.assert_not_called()

    def test_tile_edit_prompt_has_preserve_prefix(self):
        """有参考图时 adapter.edit 接收的 prompt 必须以 PRESERVE EXACTLY 开头。"""
        from pipeline.layers.aplus_image_generator import _generate_tile_module_image

        module = _make_module("BENEFIT")
        module.id = 3
        module.project_id = 1
        adapter = self._make_adapter()
        session = self._make_session()

        _generate_tile_module_image(
            module, {}, adapter, session, ref_image_paths=["/fake/white_bg.png"]
        )

        _, prompt_arg = adapter.edit.call_args[0]
        assert prompt_arg.startswith("PRESERVE EXACTLY")

    def test_tile_edit_passes_correct_size(self):
        """有参考图时 adapter.edit 应传入 1024x1024 尺寸参数。"""
        from pipeline.layers.aplus_image_generator import _generate_tile_module_image

        module = _make_module("DETAIL")
        module.id = 4
        module.project_id = 1
        adapter = self._make_adapter()
        session = self._make_session()

        _generate_tile_module_image(
            module, {}, adapter, session, ref_image_paths=["/fake/white_bg.png"]
        )

        kwargs = adapter.edit.call_args[1]
        assert kwargs.get("params", {}).get("size") == "1024x1024"

    def test_tile_module_path_saved_after_edit(self):
        """生图成功后 module.image_path 应被写入，session.commit 应被调用。"""
        from pipeline.layers.aplus_image_generator import _generate_tile_module_image

        module = _make_module("BENEFIT")
        module.id = 5
        module.project_id = 1
        adapter = self._make_adapter()
        session = self._make_session()

        _generate_tile_module_image(
            module, {}, adapter, session, ref_image_paths=["/fake/white_bg.png"]
        )

        assert module.image_path == "/fake/output.png"
        session.commit.assert_called_once()
