"""Slot plan generator – creates 8 SlotPlan records for a project."""

from __future__ import annotations

from pipeline.constants.tags import SLOT_MAPPING
from pipeline.models.base import get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.slot_plan import SlotPlan
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


def generate_slot_plan(project_id: int) -> list[SlotPlan]:
    """Generate 8 SlotPlan records for *project_id*.

    Raises ``ValueError`` with code ``E_PLANNER_001`` when no
    AmazonBenchmark rows exist for the project.
    """
    session = get_session()
    try:
        bench_count = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == project_id)
            .count()
        )
        if bench_count == 0:
            raise ValueError(
                f"E_PLANNER_001: No AmazonBenchmark rows for project {project_id}"
            )

        session.query(SlotPlan).filter(SlotPlan.project_id == project_id).delete()

        plans: list[SlotPlan] = []
        for slot_index in range(1, 9):
            intent, layout, style, color = _SLOT_DEFAULTS[slot_index]
            plan = SlotPlan(
                project_id=project_id,
                slot_index=slot_index,
                intent_tag=intent,
                layout_tag=layout,
                style_tag=style,
                color_tag=color,
                description=SLOT_MAPPING[slot_index],
            )
            session.add(plan)
            plans.append(plan)

        session.commit()
        for p in plans:
            session.refresh(p)
        session.expunge_all()
        logger.info("Created %d slot plans for project %d", len(plans), project_id)
        return plans
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
