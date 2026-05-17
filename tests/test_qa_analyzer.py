import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from pipeline.models.qa_entry import QAEntry

SAMPLE_ASIN = "B09V3KXJPB"

SAMPLE_QA_PAIRS = [
    {"question": "Is this waterproof?", "answer": "Yes, it has IPX7 rating."},
    {"question": "How long does the battery last?", "answer": "About 8 hours."},
    {"question": "Does it work with iPhone?", "answer": "Yes, via Bluetooth 5.0."},
    {
        "question": "Can I use it while charging?",
        "answer": "No, charging disables use.",
    },
]

FAKE_GEMINI_RESPONSE = json.dumps(
    [
        {
            "question": "Is this waterproof?",
            "answer": "Yes, it has IPX7 rating.",
            "frequency": 5,
            "category": "durability",
        },
        {
            "question": "How long does the battery last?",
            "answer": "About 8 hours.",
            "frequency": 8,
            "category": "battery",
        },
        {
            "question": "Does it work with iPhone?",
            "answer": "Yes, via Bluetooth 5.0.",
            "frequency": 3,
            "category": "compatibility",
        },
        {
            "question": "Can I use it while charging?",
            "answer": "No, charging disables use.",
            "frequency": 2,
            "category": "usage",
        },
    ]
)


class TestAnalyzeQA:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_returns_list_of_qa_entries(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_qa(SAMPLE_ASIN, SAMPLE_QA_PAIRS)

        assert isinstance(result, list)
        assert len(result) == 4
        assert all(isinstance(e, QAEntry) for e in result)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_entry_fields_populated(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        result = analyze_qa(SAMPLE_ASIN, SAMPLE_QA_PAIRS)

        entry = result[0]
        assert entry.asin == SAMPLE_ASIN
        assert entry.question == "Is this waterproof?"
        assert entry.answer == "Yes, it has IPX7 rating."
        assert entry.frequency == 5
        assert entry.category == "durability"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_empty_qa_returns_empty_list(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        result = analyze_qa(SAMPLE_ASIN, [])

        assert result == []
        mock_gemini.assert_not_called()

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_gemini_called_with_asin_and_qa(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        mock_gemini.return_value = FAKE_GEMINI_RESPONSE
        analyze_qa(SAMPLE_ASIN, SAMPLE_QA_PAIRS)

        mock_gemini.assert_called_once()
        prompt = mock_gemini.call_args[0][0]
        assert SAMPLE_ASIN in prompt
        assert "waterproof" in prompt

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_invalid_json_returns_empty_list(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        mock_gemini.return_value = "not valid json at all"
        result = analyze_qa(SAMPLE_ASIN, SAMPLE_QA_PAIRS)

        assert result == []

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    @patch("pipeline.layers.qa_analyzer._call_gemini")
    def test_default_frequency_and_category(self, mock_gemini):
        from pipeline.layers.qa_analyzer import analyze_qa

        mock_gemini.return_value = json.dumps([{"question": "Q?", "answer": "A."}])
        result = analyze_qa(SAMPLE_ASIN, [{"question": "Q?", "answer": "A."}])

        assert result[0].frequency == 1
        assert result[0].category == "general"


class TestCallGeminiQA:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key"})
    def test_call_gemini_returns_text(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value.generate_content.return_value.text = (
            '[{"question": "test"}]'
        )
        google_mock = MagicMock()
        google_mock.generativeai = mock_genai

        with patch.dict(
            sys.modules, {"google": google_mock, "google.generativeai": mock_genai}
        ):
            from pipeline.layers.qa_analyzer import _call_gemini

            result = _call_gemini("Analyze QA")
            assert result == '[{"question": "test"}]'

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_call_gemini_no_key_returns_empty_array(self):
        from pipeline.layers.qa_analyzer import _call_gemini

        result = _call_gemini("anything")
        assert result == "[]"
