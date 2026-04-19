from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from pipeline.models.base import Base


class TrendForecast(Base):
    __tablename__ = "trend_forecasts"

    id = Column(Integer, primary_key=True)
    asin = Column(String(20), nullable=False)
    category = Column(String(100))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    predicted_trend = Column(
        String(20), nullable=False
    )  # "rising"|"stable"|"declining"
    confidence = Column(Float, nullable=False, default=0.0)
    data_points = Column(Text)  # JSON string
    created_at = Column(DateTime, server_default=func.now())
