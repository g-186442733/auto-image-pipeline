from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile


def build_brand_profile(project_id: int) -> BrandProfile:
    session = get_session()
    try:
        bp = session.query(BrandProfile).filter_by(project_id=project_id).first()
        if bp is None:
            bp = BrandProfile(project_id=project_id)
            session.add(bp)
            session.commit()
            session.refresh(bp)
        session.expunge(bp)
        return bp
    finally:
        session.close()
