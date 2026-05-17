"""Integration test: step_analyze wires review_analyzer into orchestrator."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config

_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="test_orch_review_")
config.db_path = _tmp_db
config.output_dir = _tmp_out
config.keepa_api_key = "test-key"
config.openai_api_key = "test-key"

from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.project import Project
from pipeline.models.review_cluster import ReviewCluster

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
            name="Review Test Product",
            asin="B0REVTEST1",
            category="Electronics",
            status="initialized",
        )
        session.add(proj)
        session.commit()
        return proj.id
    finally:
        session.close()


_FAKE_ASIN_DETAIL = {
    "title": "Test Review Product",
    "price": 29.99,
    "bsr_rank": 1200,
}

_FAKE_CATEGORY_TOP = []

_FAKE_REVIEWS = [
    {"text": "Great product!", "rating": 5},
    {"text": "Works well.", "rating": 4},
]


def _make_review_clusters(asin: str) -> list[ReviewCluster]:
    return [
        ReviewCluster(
            asin=asin, cluster_label="Positive", sentiment="positive", count=10
        ),
        ReviewCluster(asin=asin, cluster_label="Neutral", sentiment="neutral", count=5),
    ]


class TestStepAnalyzeCallsReviewAnalyzer:
    def test_analyze_reviews_called_once(self):
        project_id = _seed_project()

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
                return_value=CompetitorListing(
                    asin="B0REVTEST1", title="Test Review Product"
                ),
            ),
            patch(
                "pipeline.layers.amazon_data.fetch_reviews",
                return_value=_FAKE_REVIEWS,
            ),
            patch(
                "pipeline.layers.review_analyzer.analyze_reviews",
                return_value=_make_review_clusters("B0REVTEST1"),
            ) as mock_analyze,
            patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
            patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
            patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip")),
            patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")),
            patch(
                "pipeline.layers.brief_generator.generate_brief",
                side_effect=Exception("skip"),
            ),
        ):
            from pipeline.orchestrator import step_analyze

            step_analyze(project_id)

        mock_analyze.assert_called_once_with("B0REVTEST1", _FAKE_REVIEWS)

    def test_review_cluster_rows_exist_in_db(self):
        project_id = _seed_project()

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
                return_value=CompetitorListing(
                    asin="B0REVTEST1", title="Test Review Product"
                ),
            ),
            patch(
                "pipeline.layers.amazon_data.fetch_reviews",
                return_value=_FAKE_REVIEWS,
            ),
            patch(
                "pipeline.layers.review_analyzer.analyze_reviews",
                return_value=_make_review_clusters("B0REVTEST1"),
            ),
            patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
            patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
            patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip")),
            patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")),
            patch(
                "pipeline.layers.brief_generator.generate_brief",
                side_effect=Exception("skip"),
            ),
        ):
            from pipeline.orchestrator import step_analyze

            step_analyze(project_id)

        session = get_session()
        try:
            rows = (
                session.query(ReviewCluster)
                .filter(
                    ReviewCluster.project_id == project_id,
                    ReviewCluster.asin == "B0REVTEST1",
                )
                .all()
            )
            assert len(rows) == 2
            labels = {r.cluster_label for r in rows}
            assert "Positive" in labels
            assert "Neutral" in labels
        finally:
            session.close()

    def test_review_analyzer_failure_does_not_crash_pipeline(self):
        project_id = _seed_project()

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
                return_value=CompetitorListing(
                    asin="B0REVTEST1", title="Test Review Product"
                ),
            ),
            patch(
                "pipeline.layers.amazon_data.fetch_reviews",
                side_effect=RuntimeError("API down"),
            ),
            patch("pipeline.layers.amazon_data.fetch_qa", return_value=[]),
            patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[]),
            patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip")),
            patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")),
            patch(
                "pipeline.layers.brief_generator.generate_brief",
                side_effect=Exception("skip"),
            ),
        ):
            from pipeline.orchestrator import step_analyze

            result = step_analyze(project_id)

        assert "asin_detail" in result
