import logging

from pipeline.models.base import get_session
from pipeline.models.consistency_profile import ConsistencyProfile

logger = logging.getLogger("aip.consistency_system")

STYLE_VARIABLES = [
    "lighting_style",
    "color_palette",
    "camera_angle",
    "element_density",
    "text_overlay_style",
]


def create_consistency_profile(project_id: int) -> ConsistencyProfile:
    session = get_session()
    try:
        cp = ConsistencyProfile(project_id=project_id, locked=False)
        session.add(cp)
        session.commit()
        session.refresh(cp)
        session.expunge(cp)
        return cp
    finally:
        session.close()


def get_consistency_profile(project_id: int) -> ConsistencyProfile:
    session = get_session()
    try:
        cp = session.query(ConsistencyProfile).filter_by(project_id=project_id).first()
        if cp is None:
            cp = ConsistencyProfile(project_id=project_id, locked=False)
            session.add(cp)
            session.commit()
            session.refresh(cp)
        session.expunge(cp)
        return cp
    finally:
        session.close()


def update_consistency_profile(project_id: int, **kwargs) -> ConsistencyProfile:
    session = get_session()
    try:
        cp = session.query(ConsistencyProfile).filter_by(project_id=project_id).first()
        if cp is None:
            raise ValueError(f"No consistency profile for project {project_id}")
        if cp.locked:
            raise ValueError("Profile is locked — cannot update")
        for key, value in kwargs.items():
            if key in STYLE_VARIABLES:
                setattr(cp, key, value)
        session.commit()
        session.refresh(cp)
        session.expunge(cp)
        return cp
    finally:
        session.close()


def lock_consistency_profile(project_id: int) -> ConsistencyProfile:
    session = get_session()
    try:
        cp = session.query(ConsistencyProfile).filter_by(project_id=project_id).first()
        if cp is None:
            raise ValueError(f"No consistency profile for project {project_id}")
        cp.locked = True
        session.commit()
        session.refresh(cp)
        session.expunge(cp)
        return cp
    finally:
        session.close()


def validate_consistency(project_id: int):
    cp = get_consistency_profile(project_id)
    missing = [v for v in STYLE_VARIABLES if not getattr(cp, v, None)]
    return (len(missing) == 0, missing)


_CATEGORY_PRIORS: dict[str, dict[str, str]] = {
    "electronics": {
        "lighting_style": "studio hard",
        "color_palette": "neutral cool",
        "camera_angle": "eye level",
        "element_density": "minimal",
        "text_overlay_style": "none",
    },
    "beauty": {
        "lighting_style": "soft diffused",
        "color_palette": "warm pastel",
        "camera_angle": "45-degree",
        "element_density": "minimal",
        "text_overlay_style": "none",
    },
    "apparel": {
        "lighting_style": "natural window",
        "color_palette": "neutral",
        "camera_angle": "eye level",
        "element_density": "minimal",
        "text_overlay_style": "none",
    },
    "home": {
        "lighting_style": "warm ambient",
        "color_palette": "warm earth tones",
        "camera_angle": "45-degree",
        "element_density": "medium",
        "text_overlay_style": "none",
    },
    "food": {
        "lighting_style": "natural overhead",
        "color_palette": "vibrant warm",
        "camera_angle": "overhead",
        "element_density": "medium",
        "text_overlay_style": "none",
    },
}

_GLOBAL_DEFAULTS: dict[str, str] = {
    "lighting_style": "soft diffused",
    "color_palette": "neutral",
    "camera_angle": "eye level",
    "element_density": "minimal",
    "text_overlay_style": "none",
}


def warm_start_consistency_profile(
    project_id: int, category: str | None = None
) -> list[str]:
    """仅填充空字段，不覆盖已有值。返回实际被填充的字段名列表。"""
    session = get_session()
    try:
        cp = session.query(ConsistencyProfile).filter_by(project_id=project_id).first()
        if cp is None:
            cp = ConsistencyProfile(project_id=project_id, locked=False)
            session.add(cp)

        if cp.locked:
            logger.warning(
                "project_id=%d consistency_profile 已锁定，跳过冷启动填充", project_id
            )
            return []

        category_key = (category or "").lower().split("/")[0].strip()
        priors = _CATEGORY_PRIORS.get(category_key, _GLOBAL_DEFAULTS)
        source = category_key if category_key in _CATEGORY_PRIORS else "global_defaults"

        filled: list[str] = []
        for field in STYLE_VARIABLES:
            if not getattr(cp, field, None):
                setattr(cp, field, priors[field])
                filled.append(field)

        if filled:
            session.commit()
            logger.info(
                "project_id=%d 冷启动填充 consistency_profile，来源=%s，字段=%s",
                project_id,
                source,
                filled,
            )
        return filled
    finally:
        session.close()


def check_gate4(project_id: int) -> dict:
    """Gate 4：consistency_profile 的5个风格字段全部非空才允许投递。

    任一字段为空 → 返回 {"passed": False, "missing": [字段名列表]}
    全部非空     → 返回 {"passed": True,  "missing": []}
    """
    passed, missing = validate_consistency(project_id)
    return {"passed": passed, "missing": missing}
