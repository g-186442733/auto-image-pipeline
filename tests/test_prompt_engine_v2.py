"""Tests for build_prompt() — data-driven prompt assembly from DB."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.image_brief import ImageBrief
from pipeline.models.brand import BrandProfile
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.slot_plan import SlotPlan
from pipeline.layers.prompt_engine import build_prompt

PROJECT_ID = 77
SLOT_INDEX = 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_brief(session, project_id=PROJECT_ID, slot_index=SLOT_INDEX, brief_data=None):
    if brief_data is None:
        brief_data = {
            "target_tags": {
                "intent_tag": "INT_HERO",
                "layout_tag": "LAY_CENTER",
                "style_tag": "STY_MINIMAL",
                "color_tag": "CLR_WHITE",
            },
            "concept": "Hero shot on white background",
        }
    session.add(
        ImageBrief(
            project_id=project_id,
            slot_index=slot_index,
            brief_json=json.dumps(brief_data),
        )
    )
    session.commit()


def _seed_brand(session, project_id=PROJECT_ID):
    session.add(
        BrandProfile(
            project_id=project_id,
            brand_name="TestBrand",
            tone="professional",
            color_palette="#FF0000, #00FF00",
            guidelines="Always use brand watermark.",
        )
    )
    session.commit()


def _seed_competitor(session, project_id=PROJECT_ID):
    session.add(
        CompetitorListing(
            project_id=project_id,
            asin="B000TEST99",
            title="Competitor Widget Pro",
            bullet_points="Durable; Lightweight; Affordable",
            selling_points_map="quality, price",
        )
    )
    session.commit()


class TestBuildPromptBasic:
    """build_prompt returns a prompt string using DB data."""

    def test_returns_string_with_brief_data(self, db_session):
        _seed_brief(db_session)
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_brief_concept(self, db_session):
        _seed_brief(db_session)
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)
        assert "Hero shot" in result or "INT_HERO" in result

    def test_includes_brand_when_present(self, db_session):
        _seed_brief(db_session)
        _seed_brand(db_session)
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)
        assert "professional" in result or "brand" in result.lower()

    def test_includes_competitor_when_present(self, db_session):
        _seed_brief(db_session)
        _seed_competitor(db_session)
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)
        assert "Competitor Widget Pro" in result or "competitor" in result.lower()


class TestBuildPromptEdgeCases:
    """Edge cases and error handling."""

    def test_raises_without_brief(self, db_session):
        with pytest.raises(ValueError, match="E_BUILD_001"):
            build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)

    def test_handles_malformed_brief_json(self, db_session):
        """Malformed brief_json should not crash — fallback to empty dict."""
        session = db_session
        session.add(
            ImageBrief(
                project_id=PROJECT_ID,
                slot_index=SLOT_INDEX,
                brief_json="NOT VALID JSON {{{",
            )
        )
        session.commit()
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=session)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_works_without_brand_or_competitor(self, db_session):
        """Should work with only ImageBrief, no brand or competitor."""
        _seed_brief(db_session)
        result = build_prompt(PROJECT_ID, SLOT_INDEX, session=db_session)
        assert isinstance(result, str)
        assert len(result) > 0
