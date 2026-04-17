from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ABTest(Base):
    __tablename__ = "ab_tests"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    variant_a_id = Column(Integer, ForeignKey("prompt_assets.id"))
    variant_b_id = Column(Integer, ForeignKey("prompt_assets.id"))
    winner = Column(String(1))
    metric = Column(String(50))
    score_a = Column(Float)
    score_b = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
