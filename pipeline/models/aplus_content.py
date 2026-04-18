from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from pipeline.models.base import Base

_VALID_MODULE_TYPES = (
    "('HERO','BENEFIT','DETAIL','LIFESTYLE','COMPARISON','BRAND_STORY','CROSS_SELL')"
)


class APlusContent(Base):
    __tablename__ = "aplus_contents"

    __table_args__ = (
        CheckConstraint(
            f"module_type IN {_VALID_MODULE_TYPES}",
            name="ck_aplus_module_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    module_type = Column(String(20), nullable=False, default="HERO")
    headline = Column(Text, nullable=True)
    body_text = Column(Text, nullable=True)
    image_refs = Column(Text, nullable=True)
    layout = Column(Text, nullable=True)
    position_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="aplus_contents")
