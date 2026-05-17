from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    func,
)

from pipeline.models.base import Base


class ConsistencyProfile(Base):
    __tablename__ = "consistency_profiles"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)

    lighting_style = Column(Text, nullable=True)
    color_palette = Column(Text, nullable=True)
    camera_angle = Column(Text, nullable=True)
    element_density = Column(Text, nullable=True)
    text_overlay_style = Column(Text, nullable=True)

    locked = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
