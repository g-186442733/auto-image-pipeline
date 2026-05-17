"""客户简报模型 — 存储客户提供的品牌和营销偏好信息。"""

from sqlalchemy import Column, Integer, Text, ForeignKey

from pipeline.models.base import Base


class CustomerBrief(Base):
    __tablename__ = "customer_briefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
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
    # 商品基础属性
    product_dimensions = Column(Text)
    product_weight = Column(Text)
    product_material = Column(Text)
    product_color = Column(Text)
    package_contents = Column(Text)
    product_certifications = Column(Text)
    # Listing 字段
    listing_title = Column(Text)
    listing_keywords = Column(Text)
    listing_bullets = Column(Text)
    # 产品图（白底主图 + 多角度图）
    white_bg_image_path = Column(Text)
    multiangle_image_paths = Column(Text)
    # 扩展参考图（按图片类型区分，减少 AI 生图幻觉）
    packaging_image_path = Column(Text)  # 包装正面图
    inbox_flatlay_image_path = Column(Text)  # 配件全家福/开箱平铺图
    detail_closeup_image_paths = Column(Text)  # 细节特写图（逗号分隔多张）
    scale_ref_image_path = Column(Text)  # 尺寸参照图
    usage_context_image_paths = Column(Text)  # 使用场景图（逗号分隔多张）
    color_variant_image_paths = Column(Text)  # 颜色款式图（逗号分隔多张）

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
        "product_dimensions",
        "product_weight",
        "product_material",
        "product_color",
        "package_contents",
        "product_certifications",
        "listing_title",
        "listing_keywords",
        "listing_bullets",
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
            "product_dimensions": "Product Dimensions",
            "product_weight": "Product Weight",
            "product_material": "Product Material",
            "product_color": "Product Color",
            "package_contents": "Package Contents",
            "product_certifications": "Certifications",
            "listing_title": "Listing Title",
            "listing_keywords": "Listing Keywords",
            "listing_bullets": "Listing Bullets",
        }
        for field in self.INJECTABLE_FIELDS:
            value = getattr(self, field, None)
            if value is not None:
                label = field_labels.get(field, field)
                lines.append(f"{label}: {value}")
        if not lines:
            return ""
        return "\n--- Customer Brief ---\n" + "\n".join(lines)
