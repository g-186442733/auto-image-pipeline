from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class QAEntry(Base):
    __tablename__ = "qa_entries"

    id = Column(Integer, primary_key=True)
    asin = Column(String(20), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    frequency = Column(Integer, default=1)
    category = Column(String(100))
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
