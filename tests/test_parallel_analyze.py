"""Tests for parallel step_analyze() with ThreadPoolExecutor."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch, call

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config

_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="test_parallel_")
config.db_path = _tmp_db
config.output_dir = _tmp_out
config.keepa_api_key = "test-key"
config.openai_api_key = "test-key"

from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.project import Project

base_mod._engine = create_engine(f"sqlite:///{_tmp_db}", echo=False)
base_mod._SessionLocal = None
Base.metadata.create_all(base_mod._engine)


@pytest.fixture(autouse=True)
def _ensure_api_keys():
    config.keepa_api_key = "test-key"
    config.openai_api_key = "test-key"
    yield


def _seed_project() -> int:
    session = get_session()
    try:
        proj = Project(
            name="Parallel Test Product",
            asin="B0PARTEST",
            category="Electronics",
            status="initialized",
        )
        session.add(proj)
        session.commit()
        return proj.id
    finally:
        session.close()


_FAKE_ASIN_DETAIL = {"title": "Parallel Headphones", "price": 29.99}
_FAKE_CATEGORY_TOP = []

_PATCHES = {
    "pipeline.orchestrator.fetch_asin_detail": _FAKE_ASIN_DETAIL,
    "pipeline.orchestrator.fetch_category_top": _FAKE_CATEGORY_TOP,
    "pipeline.orchestrator.analyze_competitor_listing": {"vision": "ok"},
    "pipeline.layers.listing_analyzer.analyze_listing": None,
    "pipeline.layers.amazon_data.fetch_reviews": [],
    "pipeline.layers.review_analyzer.analyze_reviews": [],
    "pipeline.layers.amazon_data.fetch_qa": [],
    "pipeline.layers.qa_analyzer.analyze_qa": [],
}


def _make_patches(extra=None):
    """Return a list of patch context managers for step_analyze dependencies."""
    targets = dict(_PATCHES)
    if extra:
        targets.update(extra)
    patches = {}
    for target, rv in targets.items():
        if rv is None:
            mock_listing = CompetitorListing(
                asin="B0PARTEST",
                title="Parallel Headphones",
                bullet_points="{}",
                selling_points_map="{}",
            )
            patches[target] = patch(target, return_value=mock_listing)
        else:
            patches[target] = patch(target, return_value=rv)
    patches["pipeline.orchestrator.analyze_price"] = patch(
        "pipeline.orchestrator.analyze_price", side_effect=Exception("skip")
    )
    patches["pipeline.orchestrator.analyze_promo"] = patch(
        "pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")
    )
    patches["pipeline.layers.brief_generator.generate_brief"] = patch(
        "pipeline.layers.brief_generator.generate_brief", side_effect=Exception("skip")
    )
    return patches


class TestParallelAnalyze:
    def _run_with_parallel(self, parallel: bool):
        project_id = _seed_project()
        old_val = config.parallel_analyze
        config.parallel_analyze = parallel
        try:
            patches = _make_patches()
            with (
                patches["pipeline.orchestrator.fetch_asin_detail"],
                patches["pipeline.orchestrator.fetch_category_top"],
                patches["pipeline.orchestrator.analyze_competitor_listing"],
                patches["pipeline.layers.listing_analyzer.analyze_listing"],
                patches["pipeline.layers.amazon_data.fetch_reviews"],
                patches["pipeline.layers.review_analyzer.analyze_reviews"],
                patches["pipeline.layers.amazon_data.fetch_qa"],
                patches["pipeline.layers.qa_analyzer.analyze_qa"],
                patches["pipeline.orchestrator.analyze_price"],
                patches["pipeline.orchestrator.analyze_promo"],
                patches["pipeline.layers.brief_generator.generate_brief"],
            ):
                from pipeline.orchestrator import step_analyze

                result = step_analyze(project_id)
        finally:
            config.parallel_analyze = old_val
        return result, project_id

    def test_parallel_true_returns_correct_keys(self):
        result, _ = self._run_with_parallel(True)
        assert "asin_detail" in result
        assert "category_top" in result
        assert "competitor_analysis" in result
        assert "vision_analyzed" in result

    def test_parallel_false_returns_correct_keys(self):
        result, _ = self._run_with_parallel(False)
        assert "asin_detail" in result
        assert "category_top" in result

    def test_parallel_sets_status_analyzed(self):
        _, project_id = self._run_with_parallel(True)
        session = get_session()
        try:
            proj = session.get(Project, project_id)
            assert proj.status == "analyzed"
        finally:
            session.close()

    def test_phase1_both_fetchers_called(self):
        project_id = _seed_project()
        old_val = config.parallel_analyze
        config.parallel_analyze = True
        try:
            with (
                patch(
                    "pipeline.orchestrator.fetch_asin_detail",
                    return_value=_FAKE_ASIN_DETAIL,
                ) as mock_asin,
                patch(
                    "pipeline.orchestrator.fetch_category_top",
                    return_value=_FAKE_CATEGORY_TOP,
                ) as mock_cat,
                patch(
                    "pipeline.orchestrator.analyze_competitor_listing",
                    return_value={"vision": "ok"},
                ),
                patch(
                    "pipeline.layers.listing_analyzer.analyze_listing",
                    return_value=CompetitorListing(
                        asin="B0PARTEST",
                        title="Parallel Headphones",
                    ),
                ),
                patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
                patch(
                    "pipeline.layers.review_analyzer.analyze_reviews", return_value=[]
                ),
                patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
                patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
                patch(
                    "pipeline.orchestrator.analyze_price", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.layers.brief_generator.generate_brief",
                    side_effect=Exception("skip"),
                ),
            ):
                from pipeline.orchestrator import step_analyze

                step_analyze(project_id)

            mock_asin.assert_called_once_with("B0PARTEST")
            mock_cat.assert_called_once_with("Electronics")
        finally:
            config.parallel_analyze = old_val

    def test_analyzer_failure_does_not_crash(self):
        project_id = _seed_project()
        old_val = config.parallel_analyze
        config.parallel_analyze = True
        try:
            with (
                patch(
                    "pipeline.orchestrator.fetch_asin_detail",
                    return_value=_FAKE_ASIN_DETAIL,
                ),
                patch(
                    "pipeline.orchestrator.fetch_category_top",
                    return_value=_FAKE_CATEGORY_TOP,
                ),
                patch(
                    "pipeline.orchestrator.analyze_competitor_listing",
                    return_value={"vision": "ok"},
                ),
                patch(
                    "pipeline.layers.listing_analyzer.analyze_listing",
                    side_effect=RuntimeError("API down"),
                ),
                patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
                patch(
                    "pipeline.layers.review_analyzer.analyze_reviews", return_value=[]
                ),
                patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
                patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
                patch(
                    "pipeline.orchestrator.analyze_price", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.layers.brief_generator.generate_brief",
                    side_effect=Exception("skip"),
                ),
            ):
                from pipeline.orchestrator import step_analyze

                result = step_analyze(project_id)

            assert "asin_detail" in result
        finally:
            config.parallel_analyze = old_val

    def test_vision_phase3_parallel(self):
        project_id = _seed_project()
        old_val = config.parallel_analyze
        config.parallel_analyze = True
        try:
            cat_top = [
                {"competitor_asin": "B0CMP1", "image_url": "http://img1.jpg"},
                {"competitor_asin": "B0CMP2", "image_url": "http://img2.jpg"},
            ]
            with (
                patch(
                    "pipeline.orchestrator.fetch_asin_detail",
                    return_value=_FAKE_ASIN_DETAIL,
                ),
                patch(
                    "pipeline.orchestrator.fetch_category_top",
                    return_value=cat_top,
                ),
                patch(
                    "pipeline.orchestrator.analyze_competitor_listing",
                    return_value={"vision": "ok"},
                ),
                patch(
                    "pipeline.layers.listing_analyzer.analyze_listing",
                    return_value=CompetitorListing(
                        asin="B0PARTEST",
                        title="Parallel Headphones",
                    ),
                ),
                patch(
                    "pipeline.orchestrator._call_vision",
                    return_value={"score": 85},
                ) as mock_vision,
                patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
                patch(
                    "pipeline.layers.review_analyzer.analyze_reviews", return_value=[]
                ),
                patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
                patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
                patch(
                    "pipeline.orchestrator.analyze_price", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")
                ),
                patch(
                    "pipeline.layers.brief_generator.generate_brief",
                    side_effect=Exception("skip"),
                ),
            ):
                from pipeline.orchestrator import step_analyze

                result = step_analyze(project_id)

            assert result["vision_analyzed"] == 2
            assert mock_vision.call_count == 2
        finally:
            config.parallel_analyze = old_val
