"""Tests for data-driven slot planner (reads ImageBrief when available).

New behaviour (post-upgrade):
  generate_slot_plan() always calls _call_llm_for_slot() first;
  falls back to ImageBrief tags only when LLM returns None.
  SlotPlan now carries 8 extra strategy fields:
    visual_focus, key_message, competitor_contrast,
    lighting_tag, angle_tag, dof_tag, background_tag, gen_params
"""

import json
from unittest.mock import patch

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

# Controlled LLM response — all 13 fields present
_MOCK_LLM_RESULT = {
    "intent_tag": "INT_LIFESTYLE",
    "layout_tag": "LAY_RULE3",
    "style_tag": "STY_PLAYFUL",
    "color_tag": "CLR_WARM",
    "description": "mock rationale",
    "gen_params": "--ar 1:1 --stylize 300 --style raw",
    "visual_focus": "product in natural outdoor setting",
    "key_message": "durable for everyday use",
    "competitor_contrast": "warmer tones than competitors",
    "lighting_tag": "自然光",
    "angle_tag": "45度",
    "dof_tag": "浅景深",
    "background_tag": "场景",
}


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_benchmark(session, project_id):
    session.add(
        AmazonBenchmark(
            project_id=project_id,
            competitor_asin="B000TEST01",
            slot_index=1,
        )
    )
    session.commit()


def _seed_briefs(session, project_id):
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


# ── LLM path (primary) ──────────────────────────────────────────────────────

class TestSlotPlannerLLMPath:
    """When LLM succeeds, tags and strategy fields come from LLM result."""

    def test_returns_8_plans(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert len(plans) == 8

    def test_uses_llm_tags(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        for plan in plans:
            assert plan.intent_tag == "INT_LIFESTYLE"
            assert plan.layout_tag == "LAY_RULE3"
            assert plan.style_tag == "STY_PLAYFUL"
            assert plan.color_tag == "CLR_WARM"

    def test_new_strategy_fields_written(self, db_session):
        """LLM result -> all strategy fields persisted on SlotPlan."""
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        for plan in plans:
            assert plan.visual_focus == "product in natural outdoor setting"
            assert plan.key_message == "durable for everyday use"
            assert plan.competitor_contrast == "warmer tones than competitors"
            assert plan.lighting_tag == "自然光"
            assert plan.angle_tag
            assert plan.dof_tag == "浅景深"
            assert plan.background_tag == "场景"
            assert plan.gen_params == "--ar 1:1 --stylize 300 --style raw"

    def test_angle_tags_are_diversified_for_core_5_slot_suite(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)

        angles_by_slot = {plan.slot_index: plan.angle_tag for plan in plans}

        assert angles_by_slot[1] == "front view"
        assert angles_by_slot[2] == "side profile"
        assert angles_by_slot[3] == "front view"
        assert angles_by_slot[4] == "macro close-up"
        assert angles_by_slot[6] == "overhead shot"
        assert len({angles_by_slot[i] for i in (1, 2, 3, 4, 6)}) >= 4

    def test_slot_indices_are_1_to_8(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert sorted(p.slot_index for p in plans) == list(range(1, 9))

    def test_returns_slot_plan_objects(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert all(isinstance(p, SlotPlan) for p in plans)

    def test_plans_have_correct_project_id(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert all(p.project_id == SAMPLE_PROJECT_ID for p in plans)

    def test_replaces_existing_plans(self, db_session):
        """Running twice should not accumulate rows."""
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=_MOCK_LLM_RESULT,
        ):
            generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
            generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        all_plans = (
            db_session.query(SlotPlan)
            .filter(SlotPlan.project_id == SAMPLE_PROJECT_ID)
            .all()
        )
        assert len(all_plans) == 8


# ── Fallback: LLM returns None -> use ImageBrief ────────────────────────────

class TestSlotPlannerBriefFallback:
    """When LLM returns None, tags come from ImageBrief.brief_json."""

    def test_uses_brief_tags_when_llm_fails(self, db_session):
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        _seed_briefs(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=None,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        assert len(plans) == 8
        for plan in plans:
            assert plan.intent_tag == "INT_LIFESTYLE"
            assert plan.layout_tag == "LAY_RULE3"
            assert plan.style_tag == "STY_PLAYFUL"
            assert plan.color_tag == "CLR_WARM"

    def test_new_strategy_fields_are_none_in_brief_fallback(self, db_session):
        """Brief fallback does not populate strategy fields."""
        _seed_benchmark(db_session, SAMPLE_PROJECT_ID)
        _seed_briefs(db_session, SAMPLE_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=None,
        ):
            plans = generate_slot_plan(SAMPLE_PROJECT_ID, session=db_session)
        for plan in plans:
            assert plan.visual_focus is None
            assert plan.key_message is None
            assert plan.lighting_tag is None
            assert plan.angle_tag is None
            assert plan.dof_tag is None
            assert plan.background_tag is None


# ── Fallback: LLM returns None AND no brief -> _SLOT_DEFAULTS ───────────────

class TestSlotPlannerDefaultFallback:
    """When LLM fails and no ImageBrief, use _SLOT_DEFAULTS."""

    def test_fallback_to_defaults(self, db_session):
        _seed_benchmark(db_session, NO_BRIEF_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=None,
        ):
            plans = generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)
        assert len(plans) == 8
        for plan in plans:
            expected = _SLOT_DEFAULTS[plan.slot_index]
            assert plan.intent_tag == expected[0]
            assert plan.layout_tag == expected[1]
            assert plan.style_tag == expected[2]
            assert plan.color_tag == expected[3]

    def test_all_four_dimensions_populated_in_defaults(self, db_session):
        _seed_benchmark(db_session, NO_BRIEF_PROJECT_ID)
        with patch(
            "pipeline.layers.slot_planner._call_llm_for_slot",
            return_value=None,
        ):
            plans = generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)
        for plan in plans:
            assert plan.intent_tag is not None
            assert plan.layout_tag is not None
            assert plan.style_tag is not None
            assert plan.color_tag is not None


# ── Degraded mode: no benchmark ──────────────────────────────────────────────

class TestSlotPlannerDegradedMode:
    def test_returns_7_fallback_plans_without_benchmark(self, db_session):
        result = generate_slot_plan(NO_BRIEF_PROJECT_ID, session=db_session)
        assert len(result) == 7
        assert all(hasattr(p, "slot_index") for p in result)
