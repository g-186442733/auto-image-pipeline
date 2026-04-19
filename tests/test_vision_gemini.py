"""Tests for VISION_PROVIDER routing in vision_analyzer."""

import json
import pytest
from unittest.mock import MagicMock, patch


SAMPLE_RESULT = {
    "intent_tag": "INT_HERO",
    "role_tags": ["ROLE_PRODUCT"],
    "composition": "centered product",
    "color_palette": ["#FFFFFF"],
    "text_detected": False,
    "quality_score": 90,
}


def test_gemini_path_called_when_vision_provider_gemini(tmp_path, monkeypatch):
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    monkeypatch.setenv("VISION_PROVIDER", "gemini")

    import importlib
    import pipeline.config as cfg_mod

    cfg_mod.config = cfg_mod.Config()

    import pipeline.layers.vision_analyzer as va

    importlib.reload(va)

    mock_adapter = MagicMock()
    mock_adapter.analyze.return_value = {"analysis": json.dumps(SAMPLE_RESULT)}

    with patch(
        "pipeline.layers.vision_analyzer.GeminiVisionAdapter"
        if False
        else "pipeline.adapters.gemini_vision_adapter.GeminiVisionAdapter"
    ):
        with patch(
            "pipeline.layers.vision_analyzer._analyze_image_gemini",
            return_value=SAMPLE_RESULT,
        ) as mock_gemini:
            with patch(
                "pipeline.layers.vision_analyzer._analyze_image_openai"
            ) as mock_openai:
                result = va.analyze_image("http://example.com/img.png")

    mock_gemini.assert_called_once_with("http://example.com/img.png")
    mock_openai.assert_not_called()
    assert result == SAMPLE_RESULT


def test_openai_path_called_by_default(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)

    import importlib
    import pipeline.config as cfg_mod

    cfg_mod.config = cfg_mod.Config()

    import pipeline.layers.vision_analyzer as va

    importlib.reload(va)

    with patch(
        "pipeline.layers.vision_analyzer._analyze_image_openai",
        return_value=SAMPLE_RESULT,
    ) as mock_openai:
        with patch(
            "pipeline.layers.vision_analyzer._analyze_image_gemini"
        ) as mock_gemini:
            result = va.analyze_image("http://example.com/img.png")

    mock_openai.assert_called_once_with("http://example.com/img.png")
    mock_gemini.assert_not_called()
    assert result == SAMPLE_RESULT


def test_openai_path_when_vision_provider_explicitly_openai(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openai")

    import importlib
    import pipeline.config as cfg_mod

    cfg_mod.config = cfg_mod.Config()

    import pipeline.layers.vision_analyzer as va

    importlib.reload(va)

    with patch(
        "pipeline.layers.vision_analyzer._analyze_image_openai",
        return_value=SAMPLE_RESULT,
    ) as mock_openai:
        with patch(
            "pipeline.layers.vision_analyzer._analyze_image_gemini"
        ) as mock_gemini:
            result = va.analyze_image("http://example.com/img.png")

    mock_openai.assert_called_once()
    mock_gemini.assert_not_called()
