import json
import logging
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.image_brief import ImageBrief
from pipeline.models.qa_entry import QAEntry
from pipeline.models.review_cluster import ReviewCluster

_THREE_SLOT_JSON = json.dumps(
    {
        "slots": [
            {
                "slot_index": 0,
                "concept": "Hero shot",
                "copy_overlay": "A",
                "visual_style": "lifestyle",
            },
            {
                "slot_index": 1,
                "concept": "Detail view",
                "copy_overlay": "B",
                "visual_style": "detail",
            },
            {
                "slot_index": 2,
                "concept": "Infographic",
                "copy_overlay": "C",
                "visual_style": "infographic",
            },
        ]
    }
)

_ZERO_SLOT_JSON = json.dumps({"slots": []})


def _listing():
    return CompetitorListing(
        asin="B000TEST01",
        title="Test Product",
        bullet_points="bullet",
        description="desc",
        selling_points_map="{}",
        project_id=1,
    )


def _clusters():
    return []


def _qa():
    return []


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestMultiSlot:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_three_slots_inserts_three_rows(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = _THREE_SLOT_JSON
        result = generate_brief(1, _listing(), _clusters(), _qa(), session=db_session)

        assert len(result) == 3
        assert [b.slot_index for b in result] == [0, 1, 2]
        assert all(b.project_id == 1 for b in result)

        db_briefs = db_session.query(ImageBrief).order_by(ImageBrief.slot_index).all()
        assert len(db_briefs) == 3

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_three_slots_each_brief_has_slot_json(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = _THREE_SLOT_JSON
        result = generate_brief(1, _listing(), _clusters(), _qa(), session=db_session)

        concepts = [json.loads(b.brief_json)["concept"] for b in result]
        assert concepts == ["Hero shot", "Detail view", "Infographic"]

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_three_slots_source_analysis_ids_empty_list(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = _THREE_SLOT_JSON
        result = generate_brief(1, _listing(), _clusters(), _qa(), session=db_session)

        for b in result:
            assert json.loads(b.source_analysis_ids) == []

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_zero_slots_returns_empty_list(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = _ZERO_SLOT_JSON
        result = generate_brief(1, _listing(), _clusters(), _qa(), session=db_session)

        assert result == []
        assert db_session.query(ImageBrief).count() == 0

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_zero_slots_emits_warning(self, mock_gemini, db_session, caplog):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = _ZERO_SLOT_JSON
        with caplog.at_level(logging.WARNING, logger="pipeline.layers.brief_generator"):
            generate_brief(1, _listing(), _clusters(), _qa(), session=db_session)

        assert any("0 slots" in r.message for r in caplog.records)
