from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func

from pipeline.models.base import Base


class BrandProfile(Base):
    __tablename__ = "brand_profile_cards"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)

    brand_tone = Column(Text, nullable=True)
    color_system = Column(Text, nullable=True)
    font_preference = Column(Text, nullable=True)
    photo_style = Column(Text, nullable=True)
    model_type = Column(Text, nullable=True)
    scene_preference = Column(Text, nullable=True)
    composition_preference = Column(Text, nullable=True)
    material_texture = Column(Text, nullable=True)
    competitor_positioning = Column(Text, nullable=True)
    brand_story = Column(Text, nullable=True)
    guidelines = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
