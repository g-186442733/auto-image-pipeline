from sqlalchemy import Column, Integer, String, Text, DateTime, func

from pipeline.models.base import Base


class CustomerProfile(Base):
    """客户档案 — 公司/客户级，一个租户可有多个客户"""

    __tablename__ = "customer_profiles"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    industry = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
