from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ABTestResult(Base):
    __tablename__ = "ab_test_results"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    variant = Column(Text, nullable=False)
    score = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
