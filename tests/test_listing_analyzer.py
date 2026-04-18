import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from pipeline.models.competitor_listing import CompetitorListing

SAMPLE_ASIN = "B09V3KXJPB"

SAMPLE_KEEPA_DATA = {
    "title": "Wireless Bluetooth Headphones",
    "price": 29.99,
    "bsr_rank": 1500,
    "review_count": 3200,
    "rating": 4.5,
    "category_path": "Electronics > Headphones",
}

FAKE_GEMINI_RESPONSE = json.dumps(
    {
        "noise_cancellation": "Active noise cancellation with transparency mode",
        "battery_life": "40-hour battery life with quick charge",
        "comfort": "Memory foam ear cushions for extended wear",
    }
)


class TestAnalyzeListingWithKeepa:
    @patch.dict(
        os.environ,
        {"KEEPA_API_KEY": "fake-keepa-key", "GOOGLE_API_KEY": "fake-google-key"},
    )
    @patch("pipeline.layers.listing_analyzer._call_gemini")
    def test_returns_competitor_listing(self, mock_gemini):
        from pipeline.layers.listing_analyzer import analyze_listing

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_listing(SAMPLE_ASIN, SAMPLE_KEEPA_DATA)

        assert isinstance(result, CompetitorListing)
        assert result.asin == SAMPLE_ASIN
        assert result.title == "Wireless Bluetooth Headphones"
        assert result.selling_points_map == FAKE_GEMINI_RESPONSE

    @patch.dict(
        os.environ,
        {"KEEPA_API_KEY": "fake-keepa-key", "GOOGLE_API_KEY": "fake-google-key"},
    )
    @patch("pipeline.layers.listing_analyzer._call_gemini")
    def test_bullet_points_stored(self, mock_gemini):
        from pipeline.layers.listing_analyzer import analyze_listing

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_listing(SAMPLE_ASIN, {**SAMPLE_KEEPA_DATA})

        assert result.bullet_points is not None
        bp = json.loads(result.bullet_points)
        assert bp["price"] == 29.99

    @patch.dict(
        os.environ,
        {"KEEPA_API_KEY": "fake-keepa-key", "GOOGLE_API_KEY": "fake-google-key"},
    )
    @patch("pipeline.layers.listing_analyzer._call_gemini")
    def test_gemini_called_with_title(self, mock_gemini):
        from pipeline.layers.listing_analyzer import analyze_listing

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        analyze_listing(SAMPLE_ASIN, SAMPLE_KEEPA_DATA)

        mock_gemini.assert_called_once()
        prompt = mock_gemini.call_args[0][0]
        assert "Wireless Bluetooth Headphones" in prompt


class TestAnalyzeListingNoKeepa:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"}, clear=False)
    @patch("pipeline.layers.listing_analyzer._call_gemini")
    def test_no_keepa_returns_listing_with_empty_title(self, mock_gemini):
        from pipeline.layers.listing_analyzer import analyze_listing

        env = os.environ.copy()
        env.pop("KEEPA_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            mock_gemini.return_value = FAKE_GEMINI_RESPONSE
            result = analyze_listing(SAMPLE_ASIN, None)

            assert isinstance(result, CompetitorListing)
            assert result.asin == SAMPLE_ASIN
            assert result.title is None or result.title == ""

    @patch.dict(os.environ, {}, clear=True)
    def test_no_keepa_no_gemini_returns_empty_selling_points(self):
        from pipeline.layers.listing_analyzer import analyze_listing

        result = analyze_listing(SAMPLE_ASIN, None)

        assert isinstance(result, CompetitorListing)
        assert result.selling_points_map == "{}"


class TestCallGemini:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    def test_call_gemini_returns_text(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value.generate_content.return_value.text = (
            '{"key": "value"}'
        )
        google_mock = MagicMock()
        google_mock.generativeai = mock_genai

        with patch.dict(
            sys.modules, {"google": google_mock, "google.generativeai": mock_genai}
        ):
            from pipeline.layers.listing_analyzer import _call_gemini

            result = _call_gemini("Extract selling points for Test Product")
            assert result == '{"key": "value"}'

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_call_gemini_no_key_returns_empty(self):
        from pipeline.layers.listing_analyzer import _call_gemini

        result = _call_gemini("anything")
        assert result == "{}"
