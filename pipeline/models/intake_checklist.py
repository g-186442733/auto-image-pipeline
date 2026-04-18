from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class IntakeChecklist(Base):
    __tablename__ = "intake_checklists"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    product_photos = Column(Text)
    brand_guide = Column(Text)
    competitor_asins = Column(Text)
    platform_requirements = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
