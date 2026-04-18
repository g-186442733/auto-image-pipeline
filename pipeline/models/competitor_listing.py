from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class CompetitorListing(Base):
    __tablename__ = "competitor_listings"

    id = Column(Integer, primary_key=True)
    asin = Column(String(20), nullable=False, index=True)
    title = Column(Text)
    bullet_points = Column(Text)
    description = Column(Text)
    selling_points_map = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
