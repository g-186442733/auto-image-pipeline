"""三层标签体系 — Intent / Role / Scene 标签分配."""

from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.models.base import get_session
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.tag_assignment import TagAssignment
from pipeline.utils.logger import setup_logger

__all__ = ["INTENT_CODES", "ROLE_CODES", "assign_tags", "get_scene_tags"]

logger = setup_logger(__name__)

INTENT_NAMES = (
    "HERO",
    "LIFESTYLE",
    "INFOGRAPHIC",
    "COMPARISON",
    "SOCIAL_PROOF",
    "DETAIL",
)
INTENT_CODES = tuple(f"INT_{i:02d}" for i in range(1, 7))
INTENT_MAP = dict(zip(INTENT_CODES, INTENT_NAMES))

ROLE_NAMES = (
    "ATTENTION",
    "DESIRE",
    "TRUST",
    "INFORM",
    "DIFFERENTIATE",
    "CONVERT",
    "RETAIN",
)
ROLE_CODES = tuple(f"ROLE_{i:02d}" for i in range(1, 8))
ROLE_MAP = dict(zip(ROLE_CODES, ROLE_NAMES))

_SLOT_INTENT = {
    1: "INT_01",  # HERO
    2: "INT_02",  # LIFESTYLE
    3: "INT_03",  # INFOGRAPHIC
    4: "INT_06",  # DETAIL
    5: "INT_04",  # COMPARISON
    6: "INT_05",  # SOCIAL_PROOF
    7: "INT_02",  # LIFESTYLE
    8: "INT_01",  # HERO
}

_SLOT_ROLE = {
    1: "ROLE_01",  # ATTENTION
    2: "ROLE_02",  # DESIRE
    3: "ROLE_04",  # INFORM
    4: "ROLE_04",  # INFORM
    5: "ROLE_05",  # DIFFERENTIATE
    6: "ROLE_03",  # TRUST
    7: "ROLE_06",  # CONVERT
    8: "ROLE_07",  # RETAIN
}


def assign_tags(
    project_id: int,
    slot_plan_id: int,
    *,
    session: Optional[Session] = None,
) -> list[TagAssignment]:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        slots = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.slot_index)
            .all()
        )
        if not slots:
            return []

        result: list[TagAssignment] = []
        for slot in slots:
            idx = slot.slot_index
            intent_code = _SLOT_INTENT.get(
                idx, INTENT_CODES[(idx - 1) % len(INTENT_CODES)]
            )
            role_code = _SLOT_ROLE.get(idx, ROLE_CODES[(idx - 1) % len(ROLE_CODES)])

            for tag_code, layer in ((intent_code, "intent"), (role_code, "role")):
                existing = (
                    session.query(TagAssignment)
                    .filter_by(entity_type="slot", entity_id=slot.id, tag_code=tag_code)
                    .first()
                )
                if existing:
                    result.append(existing)
                    continue

                ta = TagAssignment(
                    entity_type="slot",
                    entity_id=slot.id,
                    tag_code=tag_code,
                    tag_layer=layer,
                )
                session.add(ta)
                session.flush()
                session.refresh(ta)
                result.append(ta)

        session.commit()
        for ta in result:
            session.refresh(ta)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _call_llm_for_scenes(project_id: int) -> list[str]:
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return []
    try:
        import google.generativeai as genai
    except ImportError:
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = (
        f"For an Amazon product listing (project {project_id}), "
        "suggest 3-5 scene tags for product photography. "
        "Return a JSON array of strings, each prefixed with 'SCENE_'. "
        'Example: ["SCENE_OUTDOOR", "SCENE_KITCHEN"]. '
        "Return ONLY valid JSON, no markdown fences."
    )
    try:
        resp = model.generate_content(prompt)
        tags = json.loads(resp.text)
        if isinstance(tags, list):
            return [t for t in tags if isinstance(t, str) and t.startswith("SCENE_")]
    except Exception:
        logger.warning("Scene tag generation failed", exc_info=True)
    return []


def get_scene_tags(
    project_id: int,
    *,
    session: Optional[Session] = None,
) -> list[TagAssignment]:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        slots = session.query(SlotPlan).filter(SlotPlan.project_id == project_id).all()
        if not slots:
            return []

        scene_codes = _call_llm_for_scenes(project_id)
        if not scene_codes:
            return []

        result: list[TagAssignment] = []
        for code in scene_codes:
            existing = (
                session.query(TagAssignment)
                .filter_by(entity_type="project", entity_id=project_id, tag_code=code)
                .first()
            )
            if existing:
                result.append(existing)
                continue

            ta = TagAssignment(
                entity_type="project",
                entity_id=project_id,
                tag_code=code,
                tag_layer="scene",
            )
            session.add(ta)
            session.flush()
            session.refresh(ta)
            result.append(ta)

        session.commit()
        for ta in result:
            session.refresh(ta)
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
