from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from pipeline.models.base import Base
from pipeline.models.pipeline_run import PipelineRun  # noqa: F401 — 确保 pipeline_runs 表先创建


class SlotPlan(Base):
    __tablename__ = "slot_plans"
    # 唯一约束：同一 project + slot_index + pipeline_run 只能有一条；保留多 run 版本历史
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "slot_index",
            "pipeline_run_id",
            name="uq_slot_plan_project_slot_run",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    intent_tag = Column(String(30))
    layout_tag = Column(String(30))
    style_tag = Column(String(30))
    color_tag = Column(String(30))
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
