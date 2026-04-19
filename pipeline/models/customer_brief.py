"""客户简报模型 — 存储客户提供的品牌和营销偏好信息。"""

from sqlalchemy import Column, Integer, Text, ForeignKey

from pipeline.models.base import Base


class CustomerBrief(Base):
    __tablename__ = "customer_briefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    brand_voice = Column(Text)
    target_audience = Column(Text)
    product_usp = Column(Text)
    visual_preferences = Column(Text)
    competitor_refs = Column(Text)
    campaign_goal = Column(Text)
    budget_range = Column(Text)
    timeline = Column(Text)
    special_instructions = Column(Text)
    reference_images = Column(Text)

    # 所有可注入 LLM prompt 的字段名
    INJECTABLE_FIELDS = [
        "brand_voice",
        "target_audience",
        "product_usp",
        "visual_preferences",
        "competitor_refs",
        "campaign_goal",
        "budget_range",
        "timeline",
        "special_instructions",
        "reference_images",
    ]

    def to_prompt_section(self) -> str:
        """将非 NULL 字段格式化为 LLM prompt 注入段落。"""
        lines = []
        field_labels = {
            "brand_voice": "Brand Voice",
            "target_audience": "Target Audience",
            "product_usp": "Product USP",
            "visual_preferences": "Visual Preferences",
            "competitor_refs": "Competitor References",
            "campaign_goal": "Campaign Goal",
            "budget_range": "Budget Range",
            "timeline": "Timeline",
            "special_instructions": "Special Instructions",
            "reference_images": "Reference Images",
        }
        for field in self.INJECTABLE_FIELDS:
            value = getattr(self, field, None)
            if value is not None:
                label = field_labels.get(field, field)
                lines.append(f"{label}: {value}")
        if not lines:
            return ""
        return "\n--- Customer Brief ---\n" + "\n".join(lines)
