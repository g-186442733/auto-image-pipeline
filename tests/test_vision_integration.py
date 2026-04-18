"""Task 12 — Vision integration tests for step_analyze().

Tests that _call_vision is invoked for benchmarks with image_url,
results are persisted to bm.analysis, and failures degrade gracefully.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest


def _make_in_memory_db():
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")


def _create_project():
    from pipeline.models.base import get_session
    from pipeline.models.project import Project

    session = get_session()
    proj = Project(
        name="vision-test", asin="B0TESTTEST", category="TestCat", status="initialized"
    )
    session.add(proj)
    session.commit()
    pid = proj.id
    session.close()
    return pid


_MOCK_CATS = [
    {
        "competitor_asin": "B0COMP00AA",
        "slot_index": 0,
        "image_url": "https://img.example.com/a.jpg",
    },
    {
        "competitor_asin": "B0COMP00BB",
        "slot_index": 1,
        "image_url": "https://img.example.com/b.jpg",
    },
    {"competitor_asin": "B0COMP00CC", "slot_index": 2},
]

_VISION_RESULT = {
    "intent_tag": "INT_HERO",
    "role_tags": ["ROLE_PRODUCT"],
    "composition": "centered product",
    "color_palette": ["#FFFFFF"],
    "text_detected": False,
    "quality_score": 85.0,
}


def _run_step_analyze(pid, vision_side_effect=None):
    from pipeline.config import config

    config.keepa_api_key = "test-key"
    config.openai_api_key = "test-key"

    from pipeline.orchestrator import step_analyze

    vision_mock = mock.MagicMock(
        side_effect=vision_side_effect or (lambda url: dict(_VISION_RESULT))
    )

    with (
        mock.patch(
            "pipeline.orchestrator.fetch_asin_detail", return_value={"title": "T"}
        ),
        mock.patch(
            "pipeline.orchestrator.fetch_category_top", return_value=list(_MOCK_CATS)
        ),
        mock.patch("pipeline.orchestrator.analyze_competitor_listing", return_value=[]),
        mock.patch("pipeline.orchestrator._call_vision", vision_mock),
    ):
        result = step_analyze(pid)
    return result, vision_mock


class TestVisionIntegrationHappyPath:
    def test_vision_analyzed_count(self):
        _make_in_memory_db()
        pid = _create_project()
        result, _ = _run_step_analyze(pid)
        assert result["vision_analyzed"] == 2

    def test_analysis_field_persisted(self):
        _make_in_memory_db()
        pid = _create_project()
        _run_step_analyze(pid)

        from pipeline.models.base import get_session
        from pipeline.models.benchmark import AmazonBenchmark

        session = get_session()
        bms = (
            session.query(AmazonBenchmark)
            .filter(
                AmazonBenchmark.project_id == pid, AmazonBenchmark.analysis.isnot(None)
            )
            .all()
        )
        assert len(bms) == 2
        parsed = json.loads(bms[0].analysis)
        assert parsed["intent_tag"] == "INT_HERO"
        session.close()

    def test_call_vision_receives_correct_urls(self):
        _make_in_memory_db()
        pid = _create_project()
        _, vision_mock = _run_step_analyze(pid)
        called_urls = {call.args[0] for call in vision_mock.call_args_list}
        assert "https://img.example.com/a.jpg" in called_urls
        assert "https://img.example.com/b.jpg" in called_urls


class TestVisionIntegrationDegradation:
    def test_no_image_url_skipped(self):
        _make_in_memory_db()
        pid = _create_project()
        result, vision_mock = _run_step_analyze(pid)
        assert vision_mock.call_count == 2
        assert result["vision_analyzed"] == 2

    def test_vision_failure_graceful(self):
        _make_in_memory_db()
        pid = _create_project()

        def flaky(url):
            if "a.jpg" in url:
                raise ValueError("E_VISION_003: API call failed")
            return dict(_VISION_RESULT)

        result, _ = _run_step_analyze(pid, vision_side_effect=flaky)
        assert result["vision_analyzed"] == 1

    def test_all_vision_fail_still_returns(self):
        _make_in_memory_db()
        pid = _create_project()
        result, _ = _run_step_analyze(pid, vision_side_effect=ValueError("boom"))
        assert result["vision_analyzed"] == 0
        assert "asin_detail" in result
