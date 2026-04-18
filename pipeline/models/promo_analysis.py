from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class PromoAnalysis(Base):
    __tablename__ = "promo_analysis"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    asin = Column(String(20), nullable=False, index=True)
    promo_frequency = Column(Float)
    avg_discount_pct = Column(Float)
    last_promo_date = Column(String(20))
    promo_pattern = Column(String(30))
    created_at = Column(DateTime, server_default=func.now())
