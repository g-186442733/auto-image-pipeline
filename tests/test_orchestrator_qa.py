"""Integration test: step_analyze wires qa_analyzer into orchestrator."""

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
_tmp_out = tempfile.mkdtemp(prefix="test_orch_qa_")
config.db_path = _tmp_db
config.output_dir = _tmp_out
config.keepa_api_key = "test-key"
config.openai_api_key = "test-key"

from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.project import Project
from pipeline.models.qa_entry import QAEntry

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
            name="QA Test Product",
            asin="B0QATEST01",
            category="Electronics",
            status="initialized",
        )
        session.add(proj)
        session.commit()
        return proj.id
    finally:
        session.close()


_FAKE_ASIN_DETAIL = {"title": "QA Test Headphones", "price": 29.99, "bsr_rank": 1200}
_FAKE_CATEGORY_TOP = []
_FAKE_QA_PAIRS = [
    {"question": "Is it waterproof?", "answer": "Yes, IPX5 rated."},
    {"question": "Does it have a mic?", "answer": "Yes, built-in microphone."},
]


def _make_qa_entries(asin: str) -> list:
    return [
        QAEntry(
            asin=asin,
            question="Is it waterproof?",
            answer="Yes, IPX5 rated.",
            frequency=5,
            category="Features",
        ),
        QAEntry(
            asin=asin,
            question="Does it have a mic?",
            answer="Yes, built-in microphone.",
            frequency=3,
            category="Features",
        ),
    ]


class TestStepAnalyzeCallsQaAnalyzer:
    def test_analyze_qa_called_once(self):
        project_id = _seed_project()
        mock_entries = _make_qa_entries("B0QATEST01")

        with (
            patch(
                "pipeline.orchestrator.fetch_asin_detail",
                return_value=_FAKE_ASIN_DETAIL,
            ),
            patch(
                "pipeline.orchestrator.fetch_category_top",
                return_value=_FAKE_CATEGORY_TOP,
            ),
            patch("pipeline.layers.amazon_data.fetch_qa", return_value=_FAKE_QA_PAIRS),
            patch(
                "pipeline.orchestrator.analyze_competitor_listing",
                return_value={"vision": "ok"},
            ),
            patch(
                "pipeline.layers.listing_analyzer.analyze_listing",
                return_value=CompetitorListing(
                    asin="B0QATEST01", title="QA Test Headphones"
                ),
            ),
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
            patch(
                "pipeline.layers.qa_analyzer.analyze_qa", return_value=mock_entries
            ) as mock_analyze,
            patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip")),
            patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip")),
            patch(
                "pipeline.layers.brief_generator.generate_brief",
                side_effect=Exception("skip"),
            ),
        ):
            from pipeline.orchestrator import step_analyze

            step_analyze(project_id)

        mock_analyze.assert_called_once_with("B0QATEST01", _FAKE_QA_PAIRS)

    def test_qa_entry_rows_exist_in_db(self):
        project_id = _seed_project()
        mock_entries = _make_qa_entries("B0QATEST01")

        with (
            patch(
                "pipeline.orchestrator.fetch_asin_detail",
                return_value=_FAKE_ASIN_DETAIL,
            ),
            patch(
                "pipeline.orchestrator.fetch_category_top",
                return_value=_FAKE_CATEGORY_TOP,
            ),
            patch("pipeline.layers.amazon_data.fetch_qa", return_value=_FAKE_QA_PAIRS),
            patch(
                "pipeline.orchestrator.analyze_competitor_listing",
                return_value={"vision": "ok"},
            ),
            patch(
                "pipeline.layers.listing_analyzer.analyze_listing",
                return_value=CompetitorListing(
                    asin="B0QATEST01", title="QA Test Headphones"
                ),
            ),
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
            patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=mock_entries),
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
                session.query(QAEntry)
                .filter(QAEntry.project_id == project_id, QAEntry.asin == "B0QATEST01")
                .all()
            )
            assert len(rows) == 2
            questions = {r.question for r in rows}
            assert "Is it waterproof?" in questions
            assert "Does it have a mic?" in questions
        finally:
            session.close()

    def test_qa_analyzer_failure_does_not_crash_pipeline(self):
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
                "pipeline.layers.amazon_data.fetch_qa",
                side_effect=RuntimeError("Keepa API down"),
            ),
            patch(
                "pipeline.orchestrator.analyze_competitor_listing",
                return_value={"vision": "ok"},
            ),
            patch(
                "pipeline.layers.listing_analyzer.analyze_listing",
                return_value=CompetitorListing(
                    asin="B0QATEST01", title="QA Test Headphones"
                ),
            ),
            patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[]),
            patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[]),
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
