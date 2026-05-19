from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime, UTC

from pipeline.models.base import Base

_VALID_MODULE_TYPES = (
    "('HERO','BENEFIT','DETAIL','LIFESTYLE','COMPARISON','BRAND_STORY','CROSS_SELL')"
)


class APlusContent(Base):
    __tablename__ = "aplus_contents"

    __table_args__ = (
        CheckConstraint(
            f"module_type IN {_VALID_MODULE_TYPES}",
            name="ck_aplus_module_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    module_type = Column(String(20), nullable=False, default="HERO")
    headline = Column(Text, nullable=True)
    body_text = Column(Text, nullable=True)
    image_refs = Column(Text, nullable=True)
    layout = Column(Text, nullable=True)
    position_index = Column(Integer, default=0)
    # 推荐配图的 slot 序号（0-based），None 表示通用模块无需绑定 slot 图
    slot_index = Column(Integer, nullable=True)
    # A+ 专属宽幅图：生成结果路径、实际 prompt、尺寸规格（如 "1792x1024"）
    image_path = Column(String(500), nullable=True)
    image_prompt = Column(Text, nullable=True)
    image_size = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    tenant_id = Column(Integer, nullable=True, index=True)

    # QA 自动评分（0-100）
    qa_score = Column(Float, nullable=True)
    # 是否通过 QA 阈值（≥70）
    qa_passed = Column(Boolean, default=False)
    # QA 失败原因（JSON 字符串）
    qa_issues = Column(Text, nullable=True)
    # 已重试次数
    retry_count = Column(Integer, default=0)
    # 人工确认通过
    approved = Column(Boolean, default=False)
    # 人工拒绝
    rejected = Column(Boolean, default=False)
    # 确认时间
    approved_at = Column(DateTime, nullable=True)
    # 人工编辑的自定义 prompt（优先于 _build_image_prompt 自动生成）
    custom_prompt = Column(Text, nullable=True)
    # 用户上传的参考图路径（逗号分隔，最多 2 张）
    reference_image_paths = Column(Text, nullable=True)

    project = relationship("Project", back_populates="aplus_contents")
