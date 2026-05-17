from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, func

from pipeline.models.base import Base


class BrandProfile(Base):
    __tablename__ = "brand_profile_cards"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=True)
    customer_profile_id = Column(
        Integer, ForeignKey("customer_profiles.id"), nullable=True
    )
    tenant_id = Column(Integer, nullable=True, index=True)

    # ── FROZEN 字段：人工维护，飞轮禁止写入 ──────────────────────────────────
    brand_tone = Column(Text, nullable=True)
    color_system = Column(Text, nullable=True)
    font_preference = Column(Text, nullable=True)
    guidelines = Column(Text, nullable=True)
    brand_story = Column(Text, nullable=True)
    messaging_pillars = Column(Text, nullable=True)
    competitor_positioning = Column(Text, nullable=True)

    # ── ELASTIC 字段：飞轮可在 bounds 内自动更新 ─────────────────────────────
    photo_style = Column(Text, nullable=True)
    model_type = Column(Text, nullable=True)
    scene_preference = Column(Text, nullable=True)
    composition_preference = Column(Text, nullable=True)
    material_texture = Column(Text, nullable=True)

    # ── 飞轮写入字段：纯机器生成，人工不干预 ────────────────────────────────
    ab_conclusions = Column(Text, nullable=True)
    flywheel_score = Column(Float, nullable=True)
    last_flywheel_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
