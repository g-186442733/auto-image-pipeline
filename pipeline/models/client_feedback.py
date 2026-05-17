from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    func,
)

from pipeline.models.base import Base

VALID_FEEDBACK_TYPES = ("approve", "revise", "reject")


class ClientFeedback(Base):
    __tablename__ = "client_feedbacks"
    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('approve','revise','reject')",
            name="ck_feedback_type",
        ),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    slot_name = Column(String(100), nullable=False)
    feedback_type = Column(String(20), nullable=False)
    feedback_text = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
