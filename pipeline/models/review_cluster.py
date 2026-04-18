from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class ReviewCluster(Base):
    __tablename__ = "review_clusters"

    id = Column(Integer, primary_key=True)
    asin = Column(String(20), nullable=False, index=True)
    cluster_label = Column(String(100))
    sentiment = Column(String(20))
    count = Column(Integer, default=0)
    representative_reviews = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
