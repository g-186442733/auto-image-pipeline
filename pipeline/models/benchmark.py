from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from pipeline.models.base import Base


class AmazonBenchmark(Base):
    __tablename__ = "amazon_benchmarks"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    competitor_asin = Column(String(20), nullable=False)
    slot_index = Column(Integer)
    image_url = Column(String(1000))
    analysis = Column(Text)
    score = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
