from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey, func
from pipeline.models.base import Base


class CompetitorListing(Base):
    __tablename__ = "competitor_listings"

    id = Column(Integer, primary_key=True)
    asin = Column(String(20), nullable=False, index=True)
    title = Column(Text)
    price = Column(Float, nullable=True)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    bullet_points = Column(Text)  # JSON 数组字符串
    description = Column(Text)
    main_image_url = Column(String(512), nullable=True)
    category_rank = Column(Integer, nullable=True)
    selling_points_map = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    tenant_id = Column(Integer, nullable=True, index=True)
