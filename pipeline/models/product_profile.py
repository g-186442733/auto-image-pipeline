from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func

from pipeline.models.base import Base


class ProductProfile(Base):
    """产品档案 — 挂在 Project 下，关联所属品牌"""

    __tablename__ = "product_profiles"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    brand_profile_id = Column(
        Integer, ForeignKey("brand_profile_cards.id"), nullable=True
    )
    product_name = Column(String(255), nullable=True)
    product_category = Column(String(255), nullable=True)
    price_point = Column(String(100), nullable=True)
    key_features = Column(Text, nullable=True)
    visual_notes = Column(Text, nullable=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
