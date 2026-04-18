"""Integration test: step_analyze wires listing_analyzer into orchestrator."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config

_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="test_orch_listing_")
config.db_path = _tmp_db
config.output_dir = _tmp_out
config.keepa_api_key = "test-key"
config.openai_api_key = "test-key"


@pytest.fixture(autouse=True)
def _ensure_api_keys():
    config.keepa_api_key = "test-key"
    config.openai_api_key = "test-key"
    yield


from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.project import Project

base_mod._engine = create_engine(f"sqlite:///{_tmp_db}", echo=False)
base_mod._SessionLocal = None
Base.metadata.create_all(base_mod._engine)


def _seed_project() -> int:
    session = get_session()
    try:
        proj = Project(
            name="Listing Test Product",
            asin="B0LISTTEST",
            category="Electronics",
            status="initialized",
        )
        session.add(proj)
        session.commit()
        return proj.id
    finally:
        session.close()


_FAKE_ASIN_DETAIL = {
    "title": "Test Headphones Pro",
    "price": 49.99,
    "bsr_rank": 800,
}

_FAKE_CATEGORY_TOP = []


class TestStepAnalyzeCallsListingAnalyzer:
    def test_analyze_listing_called_once(self):
        project_id = _seed_project()

        mock_listing = CompetitorListing(
            asin="B0LISTTEST",
            title="Test Headphones Pro",
            bullet_points='{"price": 49.99}',
            selling_points_map='{"quality": "Excellent build quality"}',
        )

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
                return_value=mock_listing,
            ) as mock_analyze,
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
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

        mock_analyze.assert_called_once_with("B0LISTTEST", _FAKE_ASIN_DETAIL)

    def test_competitor_listing_row_exists_in_db(self):
        project_id = _seed_project()

        mock_listing = CompetitorListing(
            asin="B0LISTTEST",
            title="Test Headphones Pro",
            bullet_points='{"price": 49.99}',
            selling_points_map='{"quality": "Excellent build quality"}',
        )

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
                return_value=mock_listing,
            ),
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
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
            row = (
                session.query(CompetitorListing)
                .filter(
                    CompetitorListing.project_id == project_id,
                    CompetitorListing.asin == "B0LISTTEST",
                )
                .first()
            )
            assert row is not None
            assert row.title == "Test Headphones Pro"
        finally:
            session.close()

    def test_listing_analyzer_failure_does_not_crash_pipeline(self):
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
                side_effect=RuntimeError("Gemini API down"),
            ),
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
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
