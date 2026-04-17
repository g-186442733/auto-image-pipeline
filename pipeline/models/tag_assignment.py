from sqlalchemy import Column, Integer, String, DateTime, func
from pipeline.models.base import Base


class TagAssignment(Base):
    __tablename__ = "tag_assignments"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    tag_code = Column(String(30), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
