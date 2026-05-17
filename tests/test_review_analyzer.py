import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from pipeline.models.review_cluster import ReviewCluster

SAMPLE_ASIN = "B09V3KXJPB"

SAMPLE_REVIEWS = [
    {"text": "Great sound quality, very clear audio", "rating": 5},
    {"text": "Comfortable to wear for hours", "rating": 4},
    {"text": "Battery dies too fast", "rating": 2},
    {"text": "Amazing bass response", "rating": 5},
    {"text": "Ear cups are too tight", "rating": 2},
]

FAKE_GEMINI_RESPONSE = json.dumps(
    [
        {
            "cluster_label": "sound_quality",
            "sentiment": "positive",
            "count": 2,
            "representative_reviews": [
                "Great sound quality, very clear audio",
                "Amazing bass response",
            ],
        },
        {
            "cluster_label": "comfort",
            "sentiment": "mixed",
            "count": 2,
            "representative_reviews": [
                "Comfortable to wear for hours",
                "Ear cups are too tight",
            ],
        },
        {
            "cluster_label": "battery",
            "sentiment": "negative",
            "count": 1,
            "representative_reviews": ["Battery dies too fast"],
        },
    ]
)


class TestAnalyzeReviews:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_returns_list_of_review_clusters(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_reviews(SAMPLE_ASIN, SAMPLE_REVIEWS)

        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(c, ReviewCluster) for c in result)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_cluster_fields_populated(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_reviews(SAMPLE_ASIN, SAMPLE_REVIEWS)

        cluster = result[0]
        assert cluster.asin == SAMPLE_ASIN
        assert cluster.cluster_label == "sound_quality"
        assert cluster.sentiment == "positive"
        assert cluster.count == 2

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_representative_reviews_stored_as_json(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_reviews(SAMPLE_ASIN, SAMPLE_REVIEWS)

        reps = json.loads(result[0].representative_reviews)
        assert isinstance(reps, list)
        assert "Great sound quality" in reps[0]

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_empty_reviews_returns_empty_list(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        result = analyze_reviews(SAMPLE_ASIN, [])

        assert result == []
        mock_gemini.assert_not_called()

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_gemini_called_with_asin_and_reviews(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        analyze_reviews(SAMPLE_ASIN, SAMPLE_REVIEWS)

        mock_gemini.assert_called_once()
        prompt = mock_gemini.call_args[0][0]
        assert SAMPLE_ASIN in prompt
        assert "Great sound quality" in prompt

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.review_analyzer._call_gemini")
    def test_invalid_json_returns_empty_list(self, mock_gemini):
        from pipeline.layers.review_analyzer import analyze_reviews

        mock_gemini.return_value = "not valid json at all"
        result = analyze_reviews(SAMPLE_ASIN, SAMPLE_REVIEWS)

        assert result == []


class TestCallGeminiReview:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    def test_call_gemini_returns_text(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value.generate_content.return_value.text = (
            '[{"cluster_label": "test"}]'
        )
        google_mock = MagicMock()
        google_mock.generativeai = mock_genai

        with patch.dict(
            sys.modules, {"google": google_mock, "google.generativeai": mock_genai}
        ):
            from pipeline.layers.review_analyzer import _call_gemini

            result = _call_gemini("Analyze reviews")
            assert result == '[{"cluster_label": "test"}]'

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_call_gemini_no_key_returns_empty_array(self):
        from pipeline.layers.review_analyzer import _call_gemini

        result = _call_gemini("anything")
        assert result == "[]"
