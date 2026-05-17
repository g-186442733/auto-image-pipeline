from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from pipeline.models.base import Base


class TagAssignment(Base):
    __tablename__ = "tag_assignments"

    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "tag_code", name="uq_tag_assignment"
        ),
    )

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    tag_code = Column(String(30), nullable=False)
    tag_layer = Column(String(20), nullable=False, server_default="intent")
    status = Column(String(20), nullable=True, server_default="pending")
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
