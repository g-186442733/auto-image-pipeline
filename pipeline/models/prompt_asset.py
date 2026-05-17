from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Float,
    Boolean,
    ForeignKey,
    func,
)
from pipeline.models.base import Base
from pipeline.models.pipeline_run import PipelineRun  # noqa: F401


class PromptAsset(Base):
    __tablename__ = "prompt_assets"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    prompt_text_zh = Column(Text, nullable=True)
    negative_prompt = Column(Text)
    model_name = Column(String(100))
    version = Column(Integer, default=1)
    image_path = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    performance_score = Column(Float, nullable=True)
    is_recommended = Column(Boolean, default=False)
    approved = Column(Boolean, default=False)
    rejected = Column(Boolean, default=False)
    tenant_id = Column(Integer, nullable=True, index=True)
    visual_tags = Column(Text, nullable=True)
    user_edited = Column(Boolean, default=False, server_default="0", nullable=False)
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
    ab_ctr = Column(Float, nullable=True)
    ab_cvr = Column(Float, nullable=True)
    # QA 状态：pending / qa_passed / qa_failed
    status = Column(String(30), nullable=True)
    # 飞轮写回专用字段：slot_type 标识 A+ 模块类型，source 标识数据来源
    slot_type = Column(String(50), nullable=True)
    source = Column(String(50), nullable=True)
