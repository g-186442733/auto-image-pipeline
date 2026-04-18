from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func

from pipeline.models.base import Base


class ASINRanking(Base):
    __tablename__ = "asin_rankings"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    asin = Column(String(20), nullable=False)
    keyword = Column(String(200), nullable=False)
    rank_position = Column(Integer, nullable=False)
    category_name = Column(String(100), default="")
    tracked_at = Column(DateTime, server_default=func.now())
