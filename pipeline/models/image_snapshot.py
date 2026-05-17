from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func

from pipeline.models.base import Base


class ImageSnapshot(Base):
    __tablename__ = "image_snapshots"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    asin = Column(String(20), nullable=False)
    image_url = Column(String(500), nullable=False)
    image_hash = Column(String(64), nullable=False)
    captured_at = Column(DateTime, server_default=func.now())
    slot_position = Column(Integer, nullable=False)
    tenant_id = Column(Integer, nullable=True, index=True)
