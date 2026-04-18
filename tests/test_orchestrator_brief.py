"""Tests for brief_generator wiring in orchestrator step_analyze."""

import pytest
from unittest.mock import patch
from pipeline.config import config
from pipeline.models.base import get_session, create_all
from pipeline.models.competitor_listing import CompetitorListing

config.keepa_api_key = "test-key"
config.openai_api_key = "test-key"


@pytest.fixture(autouse=True)
def _ensure_api_keys():
    config.keepa_api_key = "test-key"
    config.openai_api_key = "test-key"
    yield


@pytest.fixture(autouse=True)
def setup_db():
    create_all()
    yield
    session = get_session()
    session.rollback()
    session.close()


def _make_project(project_id=800):
    from pipeline.models.project import Project

    session = get_session()
    existing = session.get(Project, project_id)
    if not existing:
        p = Project(
            id=project_id, name="Test Project", asin="B0TEST123", status="analyze"
        )
        session.add(p)
        session.commit()
    session.close()


@patch("pipeline.orchestrator.analyze_competitor_listing", return_value={})
@patch(
    "pipeline.layers.brief_generator._call_gemini",
    return_value='{"slots":[{"slot_index":0,"concept":"hero","copy_overlay":"","visual_style":"standard"}]}',
)
@patch("pipeline.layers.amazon_data.fetch_qa", return_value=[])
@patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[])
@patch(
    "pipeline.orchestrator.fetch_asin_detail",
    return_value={"title": "Test Product", "bulletPoints": ["Good"]},
)
@patch("pipeline.orchestrator.fetch_category_top", return_value=[])
@patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip"))
@patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip"))
@patch(
    "pipeline.layers.listing_analyzer.analyze_listing",
    return_value=CompetitorListing(asin="B0TEST123", title="Test Product"),
)
@patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[])
@patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[])
def test_brief_generated_after_analyzers(
    mock_qa_an,
    mock_rev_an,
    mock_list_an,
    mock_promo,
    mock_price,
    mock_cat,
    mock_detail,
    mock_reviews,
    mock_qa,
    mock_gemini,
    mock_vision,
):
    from pipeline.orchestrator import step_analyze
    from pipeline.models.image_brief import ImageBrief

    _make_project(800)
    step_analyze(800)
    session = get_session()
    briefs = session.query(ImageBrief).filter(ImageBrief.project_id == 800).all()
    assert len(briefs) >= 1
    assert briefs[0].brief_json is not None
    session.close()


@patch("pipeline.orchestrator.analyze_competitor_listing", return_value={})
@patch(
    "pipeline.layers.brief_generator.generate_brief",
    side_effect=Exception("brief boom"),
)
@patch("pipeline.layers.amazon_data.fetch_qa", return_value=[])
@patch("pipeline.layers.amazon_data.fetch_reviews", return_value=[])
@patch(
    "pipeline.orchestrator.fetch_asin_detail",
    return_value={"title": "Test", "bulletPoints": []},
)
@patch("pipeline.orchestrator.fetch_category_top", return_value=[])
@patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip"))
@patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip"))
@patch(
    "pipeline.layers.listing_analyzer.analyze_listing",
    return_value=CompetitorListing(asin="B0TEST123", title="Test"),
)
@patch("pipeline.layers.review_analyzer.analyze_reviews", return_value=[])
@patch("pipeline.layers.qa_analyzer.analyze_qa", return_value=[])
def test_brief_failure_does_not_crash(
    mock_qa_an,
    mock_rev_an,
    mock_list_an,
    mock_promo,
    mock_price,
    mock_cat,
    mock_detail,
    mock_reviews,
    mock_qa,
    mock_brief,
    mock_vision,
):
    from pipeline.orchestrator import step_analyze

    _make_project(801)
    step_analyze(801)


@patch("pipeline.orchestrator.analyze_competitor_listing", return_value={})
@patch("pipeline.layers.brief_generator._call_gemini", return_value='{"slots":[]}')
@patch("pipeline.layers.amazon_data.fetch_qa", side_effect=Exception("qa fail"))
@patch(
    "pipeline.layers.amazon_data.fetch_reviews", side_effect=Exception("review fail")
)
@patch(
    "pipeline.orchestrator.fetch_asin_detail",
    return_value={"title": "Test", "bulletPoints": []},
)
@patch("pipeline.orchestrator.fetch_category_top", return_value=[])
@patch("pipeline.orchestrator.analyze_price", side_effect=Exception("skip"))
@patch("pipeline.orchestrator.analyze_promo", side_effect=Exception("skip"))
@patch(
    "pipeline.layers.listing_analyzer.analyze_listing",
    return_value=CompetitorListing(asin="B0TEST123", title="Test"),
)
def test_brief_with_partial_upstream_failure(
    mock_list_an,
    mock_promo,
    mock_price,
    mock_cat,
    mock_detail,
    mock_reviews,
    mock_qa,
    mock_gemini,
    mock_vision,
):
    from pipeline.orchestrator import step_analyze
    from pipeline.models.image_brief import ImageBrief

    _make_project(802)
    step_analyze(802)
    session = get_session()
    briefs = session.query(ImageBrief).filter(ImageBrief.project_id == 802).all()
    assert len(briefs) >= 1
    session.close()
