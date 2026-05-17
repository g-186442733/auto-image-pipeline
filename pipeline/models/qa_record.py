from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from pipeline.models.base import Base


class QARecord(Base):
    __tablename__ = "qa_records"

    id = Column(Integer, primary_key=True)
    prompt_asset_id = Column(Integer, ForeignKey("prompt_assets.id"), nullable=False)
    check_type = Column(String(50), nullable=False)
    passed = Column(Integer, default=0)
    score = Column(Float)
    details = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
