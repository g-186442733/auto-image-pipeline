from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ImageSlot(Base):
    __tablename__ = "image_slots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    image_path = Column(String(500))
    qa_status = Column(String(50), default="pending")
    prompt_text = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
