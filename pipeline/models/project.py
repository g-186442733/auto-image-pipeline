from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from pipeline.models.base import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    asin = Column(String(20), index=True)
    category = Column(String(100))
    category_path = Column(String(500), nullable=True)
    status = Column(String(30), default="draft")
    notes = Column(Text)
    customer_brief = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    live_at = Column(DateTime, nullable=True)
    drl_triggered_at = Column(DateTime, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    # 关联所属产品档案（普通整数，不加 FK 约束避免与 product_profiles.project_id 形成循环依赖）
    product_profile_id = Column(Integer, nullable=True, index=True)

    tenant = relationship("Tenant", lazy="joined")
    aplus_contents = relationship("APlusContent", back_populates="project")
