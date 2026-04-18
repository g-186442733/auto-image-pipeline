from pipeline.models.base import get_session
from pipeline.models.consistency_profile import ConsistencyProfile

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
