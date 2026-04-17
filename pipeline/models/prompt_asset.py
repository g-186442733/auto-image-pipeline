from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class PromptAsset(Base):
    __tablename__ = "prompt_assets"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    negative_prompt = Column(Text)
    model_name = Column(String(100))
    version = Column(Integer, default=1)
    image_path = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
