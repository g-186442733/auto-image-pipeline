from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ReferencePack(Base):
    __tablename__ = "reference_packs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    product_truth = Column(Text, nullable=True)
    brand_rules = Column(Text, nullable=True)
    winning_examples = Column(Text, nullable=True)
    competitor_baseline = Column(Text, nullable=True)
    negative_cases = Column(Text, nullable=True)
    angle_matrix = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
