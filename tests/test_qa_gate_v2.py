import json
import os
import struct
import sys
from unittest.mock import MagicMock, patch

import pytest

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _make_png(tmp_path, width=2000, height=2000):
    from PIL import Image

    p = tmp_path / "test.png"
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    img.save(str(p), "PNG")
    return str(p)


def _setup_mock_genai(response_text: str):
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_model.generate_content.return_value = mock_response
    mock_genai.GenerativeModel.return_value = mock_model
    return mock_genai


class TestCheckBrandConsistency:
    def test_no_api_key_returns_neutral(self, tmp_path):
        png = _make_png(tmp_path)
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            from pipeline.layers.qa_gate import check_brand_consistency

            score = check_brand_consistency(png)
        assert score == 0.5

    def test_with_mocked_gemini(self, tmp_path):
        png = _make_png(tmp_path)
        mock_genai = _setup_mock_genai('{"brand_score": 0.85}')
        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}, clear=False),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
        ):
            from pipeline.layers.qa_gate import check_brand_consistency

            score = check_brand_consistency(png, {"color": "blue"})
        assert 0.0 <= score <= 1.0
        assert score == 0.85

    def test_none_image_path_returns_neutral(self):
        from pipeline.layers.qa_gate import check_brand_consistency

        assert check_brand_consistency(None) == 0.5


class TestCheckTextAccuracy:
    def test_no_api_key_returns_neutral(self, tmp_path):
        png = _make_png(tmp_path)
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            from pipeline.layers.qa_gate import check_text_accuracy

            score = check_text_accuracy(png, "Expected Product Name")
        assert score == 0.5

    def test_with_mocked_gemini(self, tmp_path):
        png = _make_png(tmp_path)
        mock_genai = _setup_mock_genai('{"text_score": 0.92}')
        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}, clear=False),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
        ):
            from pipeline.layers.qa_gate import check_text_accuracy

            score = check_text_accuracy(png, "Product X")
        assert 0.0 <= score <= 1.0
        assert score == 0.92


class TestRunQaChecksIncludesNewScores:
    def test_result_includes_brand_and_text_scores(self, tmp_path):
        png = _make_png(tmp_path)

        mock_slot_plan = MagicMock()
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 0

        mock_asset = MagicMock()
        mock_asset.id = 42
        mock_asset.image_path = png

        mock_session = MagicMock()
        mock_session.get.return_value = mock_slot_plan
        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_asset
        mock_session.query.return_value = mock_query

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False),
        ):
            from pipeline.layers.qa_gate import run_qa_checks

            records = run_qa_checks(1)

        assert len(records) == 1
        check_types = [r.check_type for r in records]
        assert "llm_qa" in check_types
