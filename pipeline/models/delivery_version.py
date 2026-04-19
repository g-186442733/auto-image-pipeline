from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    func,
)

from pipeline.models.base import Base


class DeliveryVersion(Base):
    __tablename__ = "delivery_versions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    trigger = Column(String(20), nullable=False, default="initial")
    change_summary = Column(Text, default="")
    file_manifest = Column(Text, default="[]")
    auto_delivered = Column(Boolean, default=False)
    client_signed_at = Column(DateTime, nullable=True)
