"""PipelineRun model — 记录每次流水线执行的状态和元数据。"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from pipeline.models.base import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending")
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    auto_triggered = Column(Boolean, default=False)
    trigger_source = Column(String(128), nullable=True)
