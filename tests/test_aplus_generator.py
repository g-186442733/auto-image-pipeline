"""A+ 内容生成器测试 — TDD first."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

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
        """无 API key 时应 raise。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        with pytest.raises(Exception):
            generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.aplus_generator._call_gemini")
    def test_invalid_json_returns_defaults(self, mock_gemini, db_session):
        """无效 JSON 响应时应 raise。"""
        from pipeline.layers.aplus_generator import generate_aplus_storyboard

        mock_gemini.return_value = "not valid json {{{{"
        with pytest.raises(Exception):
            generate_aplus_storyboard(SAMPLE_PROJECT_ID, session=db_session)

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
