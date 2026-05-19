from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile


def get_brand_hierarchy(project_id: int) -> dict[str, Any | None]:
    """返回 prompt 组装需要的品牌层级，兼容旧调用方。"""
    session = get_session()
    try:
        brand = session.query(BrandProfile).filter_by(project_id=project_id).first()
        if brand is not None:
            session.expunge(brand)
        return {"customer": None, "brand": brand, "product": None}
    except SQLAlchemyError:
        return {"customer": None, "brand": None, "product": None}
    finally:
        session.close()



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
