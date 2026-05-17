from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base
from pipeline.models.pipeline_run import PipelineRun  # noqa: F401 — 确保 pipeline_runs 表先创建


class ImageBrief(Base):
    __tablename__ = "image_briefs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    brief_json = Column(Text)
    source_analysis_ids = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
