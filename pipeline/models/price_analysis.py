from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, func
from pipeline.models.base import Base


class PriceAnalysis(Base):
    __tablename__ = "price_analyses"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    asin = Column(String(20), nullable=False, index=True)
    price_current = Column(Float)
    price_avg_30d = Column(Float)
    price_min_30d = Column(Float)
    price_max_30d = Column(Float)
    price_position = Column(String(20))
    competitor_prices = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
