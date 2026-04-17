from sqlalchemy import Column, Integer, String, Text, DateTime, func
from pipeline.models.base import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    asin = Column(String(20), index=True)
    category = Column(String(100))
    status = Column(String(30), default="draft")
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
