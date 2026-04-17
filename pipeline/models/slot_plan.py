from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class SlotPlan(Base):
    __tablename__ = "slot_plans"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    intent_tag = Column(String(30))
    layout_tag = Column(String(30))
    style_tag = Column(String(30))
    color_tag = Column(String(30))
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
