from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    brand_name = Column(String(200), nullable=False)
    color_palette = Column(Text)
    font_family = Column(String(200))
    tone = Column(String(100))
    logo_path = Column(String(500))
    guidelines = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
