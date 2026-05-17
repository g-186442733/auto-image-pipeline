from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from pipeline.models.base import Base


class AmazonBenchmark(Base):
    __tablename__ = "amazon_benchmarks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "competitor_asin",
            "image_url",
            "pipeline_run_id",
            name="uq_benchmark_project_asin_image_run",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
    competitor_asin = Column(String(20), nullable=False)
    slot_index = Column(Integer)
    image_slot = Column(Integer, nullable=True)
    image_url = Column(String(1000))
    analysis = Column(Text)
    score = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
