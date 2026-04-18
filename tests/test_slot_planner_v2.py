"""Tests for data-driven slot planner (reads ImageBrief when available)."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.image_brief import ImageBrief
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.layers.slot_planner import generate_slot_plan, _SLOT_DEFAULTS


SAMPLE_PROJECT_ID = 42
NO_BRIEF_PROJECT_ID = 999


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_benchmark(session, project_id):
    """Insert a minimal AmazonBenchmark row so the planner doesn't raise E_PLANNER_001."""
    session.add(
        AmazonBenchmark(
            project_id=project_id,
            competitor_asin="B000TEST01",
            slot_index=1,
        )
    )
    session.commit()


def _seed_briefs(session, project_id):
    """Insert 8 ImageBrief rows with target_tags in brief_json."""
    for i in range(1, 9):
        brief_data = {
            "target_tags": {
                "intent_tag": "INT_LIFESTYLE",
                "layout_tag": "LAY_RULE3",
                "style_tag": "STY_PLAYFUL",
                "color_tag": "CLR_WARM",
            },
            "concept": f"Brief concept for slot {i}",
        }
        session.add(
            ImageBrief(
                project_id=project_id,
                slot_index=i,
                brief_json=json.dumps(brief_data),
            )
        )
    session.commit()


class TestSlotPlannerWithBrief:
    """When ImageBrief rows exist, slot tags should come from brief data."""

    def test_uses_brief_tags_when_available(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        _seed_briefs(db_session, SAMPLE_PROJECT_ID)

        plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)

        assert len(plans) == 8
        for plan in plans:
            assert plan.intent_tag == "INT_LIFESTYLE"
            assert plan.layout_tag == "LAY_RULE3"
            assert plan.style_tag == "STY_PLAYFUL"
            assert plan.color_tag == "CLR_WARM"

    def test_returns_slot_plan_objects(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        _seed_briefs(db_session, SAMPLE_PROJECT_ID)

        plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert all(isinstance(p, SlotPlan) for p in plans)

    def test_plans_have_correct_project_id(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        _seed_briefs(db_session, SAMPLE_PROJECT_ID)

        plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert all(p.project_id == SAMPLE_PROJECT_ID for p in plans)


class TestSlotPlannerFallback:
    """When no ImageBrief rows exist, should fallback to _SLOT_DEFAULTS."""

    def test_fallback_to_defaults_without_brief(self, db_session):
        _seed_benchmark(db_session, NO_BRIEF_PROJECT_ID)

        plans = generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)

        assert len(plans) == 8
        for plan in plans:
            expected = _SLOT_DEFAULTS[plan.slot_index]
            assert plan.intent_tag == expected[0]
            assert plan.layout_tag == expected[1]
            assert plan.style_tag == expected[2]
            assert plan.color_tag == expected[3]

    def test_fallback_returns_8_plans(self, db_session):
        _seed_benchmark(db_session, NO_BRIEF_PROJECT_ID)

        plans = generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)
        assert len(plans) == 8
        assert [p.slot_index for p in plans] == list(range(1, 9))


class TestSlotPlannerValidation:
    """Edge cases and error handling."""

    def test_raises_without_benchmark(self, db_session):
        with pytest.raises(ValueError, match="E_PLANNER_001"):
            generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)

    def test_replaces_existing_plans(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)

        generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        all_plans = (
            db_session.query(SlotPlan)
            .filter(SlotPlan.project_id == SAMPLE_PROJECT_ID)
            .all()
        )
        assert len(all_plans) == 8
