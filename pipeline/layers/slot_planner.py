"""Slot plan generator – creates 8 SlotPlan records for a project."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.constants.tags import SLOT_MAPPING
from pipeline.models.base import get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.image_brief import ImageBrief
from pipeline.models.slot_plan import SlotPlan
from pipeline.layers.tag_system import assign_tags
from pipeline.utils.logger import setup_logger

__all__ = ["generate_slot_plan"]

logger = setup_logger(__name__)

_SLOT_DEFAULTS: dict[int, tuple[str, str, str, str]] = {
    1: ("INT_HERO", "LAY_CENTER", "STY_MINIMAL", "CLR_WHITE"),
    2: ("INT_LIFESTYLE", "LAY_RULE3", "STY_NATURAL", "CLR_LIGHT"),
    3: ("INT_INFOGRAPHIC", "LAY_SPLIT", "STY_TECH", "CLR_LIGHT"),
    4: ("INT_DETAIL", "LAY_CENTER", "STY_PREMIUM", "CLR_DARK"),
    5: ("INT_COMPARISON", "LAY_SPLIT", "STY_BOLD", "CLR_WHITE"),
    6: ("INT_PACKAGING", "LAY_FLAT", "STY_MINIMAL", "CLR_WHITE"),
    7: ("INT_LIFESTYLE", "LAY_RULE3", "STY_PLAYFUL", "CLR_WARM"),
    8: ("INT_HERO", "LAY_CENTER", "STY_BOLD", "CLR_BRAND"),
}


def _tags_from_brief(brief: ImageBrief) -> tuple[str, str, str, str] | None:
    try:
        data = json.loads(brief.brief_json)
        tags = data.get("target_tags", {})
        intent = tags.get("intent_tag")
        layout = tags.get("layout_tag")
        style = tags.get("style_tag")
        color = tags.get("color_tag")
        if all((intent, layout, style, color)):
            return (intent, layout, style, color)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return None


def generate_slot_plan(
    project_id: int, session: Optional[Session] = None
) -> list[SlotPlan]:
    """Generate 8 SlotPlan records for *project_id*.

    When *session* is ``None`` a new session is created via ``get_session()``.
    If ``ImageBrief`` rows exist for the project, slot tags are derived from
    ``brief_json["target_tags"]``; otherwise ``_SLOT_DEFAULTS`` is used.

    Raises ``ValueError`` with code ``E_PLANNER_001`` when no
    AmazonBenchmark rows exist for the project.
    """
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        bench_count = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == project_id)
            .count()
        )
        if bench_count == 0:
            logger.warning(
                "E_PLANNER_001: No AmazonBenchmark rows for project %d — returning empty slot plan",
                project_id,
            )
            return []

        briefs: dict[int, ImageBrief] = {
            b.slot_index: b
            for b in session.query(ImageBrief)
            .filter(ImageBrief.project_id == project_id)
            .all()
        }

        session.query(SlotPlan).filter(SlotPlan.project_id == project_id).delete()

        knowledge_hints: list[str] = []
        try:
            from pipeline.layers.knowledge_base import get_popular_entries

            popular = get_popular_entries(session, category="style_rule", limit=5)
            knowledge_hints = [e.content for e in popular if e.content]
        except Exception:
            pass

        plans: list[SlotPlan] = []
        for slot_index in range(1, 9):
            brief = briefs.get(slot_index)
            brief_tags = _tags_from_brief(brief) if brief else None
            intent, layout, style, color = brief_tags or _SLOT_DEFAULTS[slot_index]

            hint_suffix = ""
            if knowledge_hints:
                hint_suffix = " | KB: " + "; ".join(knowledge_hints[:3])

            plan = SlotPlan(
                project_id=project_id,
                slot_index=slot_index,
                intent_tag=intent,
                layout_tag=layout,
                style_tag=style,
                color_tag=color,
                description=SLOT_MAPPING[slot_index] + hint_suffix,
            )
            session.add(plan)
            plans.append(plan)

        session.commit()
        for p in plans:
            session.refresh(p)
        session.expunge_all()

        try:
            assign_tags(project_id, project_id, session=session)
        except Exception:
            logger.warning(
                "Tag assignment failed for project %d", project_id, exc_info=True
            )

        logger.info("Created %d slot plans for project %d", len(plans), project_id)
        return plans
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
