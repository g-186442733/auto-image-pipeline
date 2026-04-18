from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func

from pipeline.models.base import Base

VALID_CATEGORIES = ("prompt_pattern", "qa_lesson", "style_rule", "client_preference")


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    source_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    category = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    tags = Column(String(500), default="")
    created_at = Column(DateTime, server_default=func.now())
    usage_count = Column(Integer, default=0)
