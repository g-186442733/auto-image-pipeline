from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ImageBrief(Base):
    __tablename__ = "image_briefs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    brief_json = Column(Text)
    source_analysis_ids = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
