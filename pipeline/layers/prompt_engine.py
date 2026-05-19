"""Prompt assembly engine — combines PromptAsset templates with variables."""

from __future__ import annotations

from jinja2 import Environment, BaseLoader, TemplateSyntaxError

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.constants.tags import SLOT_MAPPING, TAG_LOOKUP
from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.customer_brief import CustomerBrief
from pipeline.models.product_profile import ProductProfile
from pipeline.layers.brand_profiler import get_brand_hierarchy
from pipeline.models.image_brief import ImageBrief
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.slot_plan import SlotPlan
try:
    from pipeline.models.flywheel_example import FlywheelExample
except ModuleNotFoundError:
    FlywheelExample = None
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.prompt_engine")

__all__ = ["assemble_prompt", "build_prompt", "generate_slot_prompts"]

# 允许文字出现的 intent_tag 集合（信息图/对比图/包装图）
_TEXT_ALLOWED_INTENTS = {"INT_INFOGRAPHIC", "INT_COMPARISON", "INT_PACKAGING"}

_MARKETPLACE_LANGUAGE_POLICY = (
    "MARKETPLACE LANGUAGE POLICY: Amazon US. "
    "All visible text, if this intent allows text, must be English only. "
    "Never render Chinese characters, CJK characters, non-English labels, or translated Chinese text in the image. "
    "Chinese user requirements are internal product facts only; translate them into concise English labels before rendering."
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_PROMPT_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("高端商务科技风", "premium business technology style"),
    ("克制", "restrained"),
    ("干净", "clean"),
    ("可信赖", "trustworthy"),
    ("严格保持真实上传白底图和角度图中的耳机外观、比例、颜色、耳罩形状和 BOSE 标识位置", "strictly preserve the headphone appearance, proportions, color, earcup shape, and BOSE logo placement from uploaded references"),
    ("Hero 主图不得展示保护盒、线材、配件全家福", "Hero image must not show carrying case, cables, or accessory bundle"),
    ("Packaging/In-box 图位才展示保护盒、USB-C 线、音频线、安全说明", "Only the Packaging/In-box slot may show carrying case, USB-C cable, audio cable, and safety guide"),
    ("Detail 图位聚焦接口、按钮、耳罩材质", "Detail slot focuses on ports, buttons, and ear cushion material"),
    ("生成构图参考图只能用于 layout，不得当作真实产品照片", "Generated composition references are for layout only, not product fact photos"),
    ("小时续航信息", "battery life information in hours"),
    ("续航", "battery life"),
    ("黑色主款", "black main product variant"),
    ("柔软耳罩材质", "soft ear cushion material"),
    ("USB-C接口", "USB-C port"),
    ("USB-C 接口", "USB-C port"),
    ("保护盒和全部配件", "carrying case and complete accessory bundle"),
    ("Hero主图出现保护盒或线材", "carrying case or cables appearing in the Hero image"),
    ("不存在的颜色", "nonexistent color variants"),
    ("虚构配件", "invented accessories"),
    ("儿童场景", "children scenes"),
    ("宠物场景", "pet scenes"),
    ("竞品品牌名", "competitor brand names"),
    ("电竞灯效", "gaming RGB lighting effects"),
    ("保护盒", "carrying case"),
    ("线材", "cables"),
    ("配件", "accessories"),
    ("耳罩", "ear cushions"),
    ("接口", "ports"),
    ("按钮", "buttons"),
    ("主图", "Hero image"),
    ("图位", "image slot"),
)

_INTENT_NEGATIVE_CONSTRAINTS: dict[str, str] = {
    "INT_HERO": "no accessories, no case, no cables, product only, no packaging bundle unless this slot is explicitly planned as a bundle hero",
    "INT_LIFESTYLE": "no flat-lay accessory bundle, no static packaging spread, show the product in actual use",
    "INT_DETAIL": "no full accessory spread, no packaging bundle, focus on one product material, port, button, seam, or craftsmanship detail",
    "INT_COMPARISON": "no packaging bundle, no accessory spread unless the comparison explicitly concerns package contents",
}

_INTENT_COMPOSITION_LOCKS: dict[str, str] = {
    "INT_LIFESTYLE": (
        "ANGLE-SPECIFIC COMPOSITION LOCK: lifestyle use scene only; show the headphones being worn "
        "by a visible person in a real indoor environment, with head/shoulders and room context in frame; "
        "use a true side-profile or over-shoulder 70-90 degree wearing view; never output a product-only image, "
        "never use a pure white studio product background, and never use an isolated 3/4 product render."
    ),
    "INT_INFOGRAPHIC": (
        "ANGLE-SPECIFIC COMPOSITION LOCK: orthographic front-facing product diagram only; "
        "use a flat front elevation or clean exploded-callout composition; never use a 3/4 camera, "
        "diagonal perspective, lifestyle view, or medium product glamor shot."
    ),
    "INT_DETAIL": (
        "ANGLE-SPECIFIC COMPOSITION LOCK: true macro close-up only; show a tight partial crop of one earcup, "
        "port edge, button cluster, seam, hinge, or cushion texture; never show the full headphone, "
        "never use a medium shot, and never use a 3/4 product view."
    ),
}


def _intent_negative_constraints(intent_tag: str | None) -> str:
    return _INTENT_NEGATIVE_CONSTRAINTS.get(intent_tag or "", "")


def _text_constraint(intent_tag: str | None) -> str:
    """根据 intent_tag 返回对应的文字约束句。

    - INT_INFOGRAPHIC / INT_COMPARISON / INT_PACKAGING：允许文字，要求拼写正确
    - 其他（主图/场景图/细节图）：严格禁止文字、水印、标注
    """
    if intent_tag and intent_tag in _TEXT_ALLOWED_INTENTS:
        return (
            "VISIBLE TEXT RULE: Any visible words, labels, callouts, numbers, or badges must be "
            "English only, correctly spelled, and mobile-readable. Do not copy Chinese source text "
            "from user requirements. Translate concepts such as battery life, USB-C port, comfort, "
            "and premium build into short English callouts."
        )
    return "Do not include any text, letters, numbers, words, labels, or watermarks in the image."



def _translate_known_cjk_terms(prompt: str) -> str:
    translated = prompt or ""
    for source, target in _CJK_PROMPT_TRANSLATIONS:
        translated = translated.replace(source, target)
    return translated



def _normalize_prompt_punctuation(prompt: str) -> str:
    normalized = (
        (prompt or "")
        .replace("；", "; ")
        .replace("。", ". ")
        .replace("，", ", ")
        .replace("、", ", ")
    )
    normalized = re.sub(r"\s+([,.;:])", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()



def _sanitize_cjk_for_image_prompt(prompt: str) -> str:
    """Remove CJK leakage from system-generated image prompts."""
    sanitized = _normalize_prompt_punctuation(_translate_known_cjk_terms(prompt))
    sanitized = _CJK_RE.sub("", sanitized)
    return _normalize_prompt_punctuation(sanitized)



def _intent_composition_lock(intent_tag: str | None) -> str:
    return _INTENT_COMPOSITION_LOCKS.get(intent_tag or "", "")


REQUIRED_VARIABLE_KEYS = frozenset(
    ["composition", "subject", "environment", "camera", "tone", "constraints"]
)

_jinja_env = Environment(loader=BaseLoader())


def _tag_text(code: str | None) -> str:
    if not code:
        return ""
    tag = TAG_LOOKUP.get(code)
    if tag is None:
        return code
    return f"{tag.name_en}, {tag.description}"


def assemble_prompt(
    prompt_asset_id: int,
    variables: dict[str, str],
    *,
    reference_pack: dict | None = None,
    brand_profile: BrandProfile | None = None,
    session: Optional[Session] = None,
) -> str:
    missing = sorted(REQUIRED_VARIABLE_KEYS - set(variables))
    if missing:
        raise ValueError(f"E_ENGINE_001: Missing prompt variables: {', '.join(missing)}")

    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        asset = session.get(PromptAsset, prompt_asset_id)
        if asset is None:
            raise ValueError(f"E_PROMPT_003: PromptAsset id={prompt_asset_id} not found")
        try:
            template = _jinja_env.from_string(asset.prompt_text)
            rendered = template.render(**variables)
        except TemplateSyntaxError as exc:
            raise ValueError(f"E_ENGINE_003: Invalid prompt template: {exc}") from exc

        parts = [rendered]
        if reference_pack:
            parts.append(
                "REFERENCE PACK:\n"
                + json.dumps(reference_pack, ensure_ascii=False, separators=(",", ":"))
            )
        if brand_profile:
            brand_bits = []
            for key in ("brand_tone", "color_system", "guidelines"):
                value = getattr(brand_profile, key, None)
                if value:
                    brand_bits.append(f"{key}: {value}")
            if brand_bits:
                parts.append("BRAND PROFILE:\n" + "\n".join(brand_bits))
        if asset.negative_prompt:
            parts.append(f"--no {asset.negative_prompt.strip()}")
        return "\n".join(parts)
    finally:
        if owns_session:
            session.close()


def build_prompt(
    project_id: int, slot_index: int, session: Optional[Session] = None
) -> str:
    """[备用路径，生产流程不调用此函数，入口为 generate_slot_prompts()]"""
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        brief = (
            session.query(ImageBrief)
            .filter(
                ImageBrief.project_id == project_id,
                ImageBrief.slot_index == slot_index,
            )
            .first()
        )
        if brief is None:
            raise ValueError(
                f"E_BUILD_001: No ImageBrief for project {project_id} slot {slot_index}"
            )

        try:
            brief_data = json.loads(brief.brief_json)
        except (json.JSONDecodeError, TypeError):
            brief_data = {}

        tags = brief_data.get("target_tags", {})
        concept = brief_data.get("concept", "")

        hierarchy = get_brand_hierarchy(project_id)
        brand = hierarchy.get("brand")
        customer = hierarchy.get("customer")
        product = hierarchy.get("product")

        competitor = (
            session.query(CompetitorListing)
            .filter(CompetitorListing.project_id == project_id)
            .first()
        )

        parts: list[str] = []

        slot_desc = SLOT_MAPPING.get(slot_index, f"Slot {slot_index}")
        parts.append(f"Slot {slot_index}: {slot_desc}")

        if concept:
            parts.append(f"Concept: {concept}")
        if tags:
            parts.append(
                f"Style: {_tag_text(tags.get('intent_tag'))} {_tag_text(tags.get('layout_tag'))} "
                f"{_tag_text(tags.get('style_tag'))} {_tag_text(tags.get('color_tag'))}"
            )

        if competitor:
            comp_parts = []
            if competitor.title:
                comp_parts.append(f"Competitor: {competitor.title}")
            if competitor.price is not None:
                comp_parts.append(f"${competitor.price:.2f}")
            if competitor.rating is not None:
                comp_parts.append(f"{competitor.rating:.1f}★")
            if competitor.category_rank is not None:
                comp_parts.append(f"BSR #{competitor.category_rank}")
            _hint = _comp_positioning_hint(
                competitor.price, competitor.rating, competitor.category_rank
            )
            if _hint:
                comp_parts.append(_hint)
            if comp_parts:
                parts.append(" | ".join(comp_parts))

        if brand:
            brand_parts = []
            if brand.brand_tone:
                brand_parts.append(f"Brand tone: {brand.brand_tone}")
            if brand.color_system:
                brand_parts.append(f"Brand colors: {brand.color_system}")
            if brand.guidelines:
                brand_parts.append(brand.guidelines)
            if brand_parts:
                parts.append(" ".join(brand_parts))

        if customer and customer.industry:
            parts.append(f"Industry: {customer.industry}")

        if product:
            prod_parts = []
            if product.product_name:
                prod_parts.append(f"Product: {product.product_name}")
            if product.product_category:
                prod_parts.append(f"Category: {product.product_category}")
            if product.visual_notes:
                prod_parts.append(product.visual_notes)
            if prod_parts:
                parts.append(" ".join(prod_parts))

        _intent_tag = tags.get("intent_tag")
        parts.append(_text_constraint(_intent_tag))

        return "\n".join(parts)
    finally:
        if owns_session:
            session.close()


# ──────────────────────────────────────────────────────────
# ELASTIC 字段默认值：BrandProfile 尚未积累数据时的 fallback
# ──────────────────────────────────────────────────────────
def _comp_positioning_hint(
    price: float | None,
    rating: float | None,
    category_rank: int | None,
) -> str:
    if price is None and rating is None:
        return ""

    high_price = price is not None and price >= 30.0
    high_rating = rating is not None and rating >= 4.5
    top_bsr = category_rank is not None and category_rank <= 1000

    parts: list[str] = []

    if high_price and high_rating:
        parts.append("competitor is a top-rated premium product")
        if top_bsr:
            parts.append("beat it with superior visual storytelling and brand depth")
        else:
            parts.append("match premium quality, differentiate on visual uniqueness")
    elif high_price and not high_rating:
        parts.append("competitor is expensive but poorly rated")
        parts.append("seize opportunity: elevate lifestyle appeal and visual clarity")
    elif not high_price and high_rating:
        parts.append("competitor is popular budget choice")
        parts.append("differentiate with aspirational look, avoid cheap aesthetic")
    else:
        parts.append("competitor is low-price low-rating")
        parts.append("elevate with premium visual treatment to stand apart")

    if price is not None:
        parts.append(f"competitor price ${price:.2f}")
    if rating is not None:
        parts.append(f"rating {rating:.1f}/5")
    if category_rank is not None:
        parts.append(f"BSR #{category_rank}")

    return ", ".join(parts)


_ELASTIC_DEFAULTS: dict[str, str] = {
    "photo_style": "studio commercial photography",
    "model_type": "no model",
    "scene_preference": "neutral seamless backdrop",
    "composition_preference": "centered composition",
    "material_texture": "clean smooth surface",
}


def _resolve_elastic(bp: BrandProfile | None) -> dict[str, str]:
    out = dict(_ELASTIC_DEFAULTS)
    if bp is None:
        return out
    for key in _ELASTIC_DEFAULTS:
        val = getattr(bp, key, None)
        if val:
            out[key] = val
    return out


# ──────────────────────────────────────────────────────────
# intent_tag → 专业灯光方案
# ──────────────────────────────────────────────────────────
_INTENT_LIGHTING: dict[str, str] = {
    "INT_HERO": (
        "key light 45° overhead softbox, fill light ratio 1:3, zero background shadow"
    ),
    "INT_LIFESTYLE": (
        "neutral studio daylight 5200K, soft diffused window-light feel without "
        "golden-hour warmth, environment-integrated lighting"
    ),
    "INT_DETAIL": (
        "ring light or twin softbox, hard raking light to reveal surface texture, "
        "macro studio setup"
    ),
    "INT_INFOGRAPHIC": (
        "flat even studio lighting, no directional shadows, consistent exposure across frame"
    ),
    "INT_COMPARISON": ("matched bilateral lighting, identical exposure on both halves"),
    "INT_PACKAGING": (
        "soft diffused box light, subtle drop shadow, packaging label fully visible"
    ),
}


def _lighting_for_intent(intent_tag: str | None, lighting_tag: str | None) -> str:
    parts: list[str] = []
    if intent_tag and intent_tag in _INTENT_LIGHTING:
        parts.append(_INTENT_LIGHTING[intent_tag])
    if lighting_tag:
        parts.append(lighting_tag)
    return ", ".join(parts) if parts else (lighting_tag or "")


# ──────────────────────────────────────────────────────────
# intent_tag → 镜头语言
# ──────────────────────────────────────────────────────────
_INTENT_CAMERA: dict[str, str] = {
    "INT_HERO": (
        "85mm lens, f/8, ISO 100, product centered, 10-15 degree frontal angle, "
        "top 60% safe zone, bottom 20% safe zone"
    ),
    "INT_LIFESTYLE": "35mm lens, f/2.8, ISO 200, environmental context visible, 70-90 degree side-profile wearing angle",
    "INT_DETAIL": "macro 1:1, 100mm lens, f/11, ISO 100, extreme sharpness, bottom-side detail crop angle",
    "INT_INFOGRAPHIC": "50mm lens, f/8, ISO 100, symmetrical framing, orthographic front-facing 0-degree camera",
    "INT_COMPARISON": "50mm lens, f/8, centered split-screen composition",
    "INT_PACKAGING": "50mm lens, f/8, ISO 100, top-down 90-degree flat-lay accessory view",
}


def _camera_for_intent(
    intent_tag: str | None,
    dof_tag: str | None,
    shot_type: str | None,
) -> str:
    parts: list[str] = []
    if intent_tag and intent_tag in _INTENT_CAMERA:
        parts.append(_INTENT_CAMERA[intent_tag])
    if dof_tag:
        parts.append(dof_tag)
    if shot_type:
        parts.append(shot_type)
    return ", ".join(parts) if parts else " ".join(filter(None, [dof_tag, shot_type]))


def _cosmo_subject(
    intent_tag: str | None,
    base_subject: str,
    target_audience: str,
    product_usp: str,
) -> str:
    """Cosmo F2：向 subject 槽注入目标受众和核心卖点语义。"""
    parts: list[str] = []
    if base_subject:
        parts.append(base_subject)
    if intent_tag in ("INT_HERO", "INT_LIFESTYLE", "INT_DETAIL"):
        if target_audience:
            parts.append(f"designed for {target_audience}")
        if product_usp:
            parts.append(f"showcasing {product_usp}")
    return ", ".join(p for p in parts if p)


def _split_bullets(text: str) -> list[str]:
    import re

    for sep in (r"\n", r"[•·]", r"[,，]", r"[;；]"):
        parts = [p.strip() for p in re.split(sep, text) if p.strip()]
        if len(parts) >= 2:
            return parts
    return [text.strip()] if text.strip() else []


def _cosmo_tone(
    base_tone: str,
    listing_bullets: str,
) -> str:
    """Cosmo F3：将 listing bullets 前两条注入 tone 槽。色彩系统由 _style_anchor() 统一注入。"""
    parts: list[str] = []
    if base_tone:
        parts.append(base_tone)
    if listing_bullets:
        bullets = _split_bullets(listing_bullets)[:2]
        if bullets:
            parts.append("conveying: " + "; ".join(bullets))
    return ", ".join(p for p in parts if p)


def _style_anchor(
    brand_tone: str | None,
    color_system: str | None,
    photo_style: str,
) -> str:
    parts: list[str] = [f"consistent visual style: {photo_style}"]
    if brand_tone:
        parts.append(f"brand aesthetic: {brand_tone}")
    if color_system:
        parts.append(f"color grading: {color_system}")
    return ", ".join(parts)


# ──────────────────────────────────────────────────────────
# intent_tag → QA 对齐约束（直接对应 qa_gate.py 评分维度）
# ──────────────────────────────────────────────────────────
_QA_CONSTRAINTS: dict[str, list[str]] = {
    "INT_HERO": [
        "pure white background #FFFFFF",
        "product occupies at least 85% of frame",
        "no visible text labels or watermarks",
        "hyperrealistic material texture",
    ],
    "INT_LIFESTYLE": [
        "natural real-world scene, no pure white background",
        "product shown in context of actual use",
        "human subjects match target audience demographics",
    ],
    "INT_INFOGRAPHIC": [
        "all text legible at minimum 60px rendered height",
        "correct spelling on all visible labels",
        "high contrast text on background",
    ],
    "INT_DETAIL": [
        "extreme surface detail visible",
        "no motion blur",
        "product fills at least 70% of frame",
    ],
    "INT_COMPARISON": [
        "split-screen layout with clear visual divider",
        "matched exposure and white balance on both halves",
    ],
    "INT_PACKAGING": [
        "packaging label fully legible",
        "three-quarter or front-facing view",
        "neutral background without distraction",
    ],
}


def _slot_label(slot_index: int) -> str:
    desc = SLOT_MAPPING.get(slot_index, "")
    return desc.split("—")[0].strip() if "—" in desc else f"SLOT{slot_index}"


def generate_slot_prompts(
    project_id: int, slot_indices: list[int] | None = None
) -> dict[str, str]:
    """Generate prompts for every slot in a project's SlotPlan.

    Returns dict mapping slot label (MAIN/ALT1/...) to assembled prompt.

    Raises:
        ValueError E_ENGINE_002 — project has no SlotPlan records
    """
    with get_session() as session:
        plans = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.slot_index)
            .all()
        )

        if slot_indices is not None:
            plans = [p for p in plans if p.slot_index in slot_indices]

        if not plans:
            raise ValueError(
                f"E_ENGINE_002: project {project_id} has no SlotPlan "
                "(run slot_planner first)"
            )

        # 查询品牌档案：project_id → ProductProfile.brand_profile_id → BrandProfile
        _bp: BrandProfile | None = None
        try:
            _pp = (
                session.query(ProductProfile)
                .filter(ProductProfile.project_id == project_id)
                .first()
            )
            if _pp and _pp.brand_profile_id:
                _bp = (
                    session.query(BrandProfile)
                    .filter(BrandProfile.id == _pp.brand_profile_id)
                    .first()
                )
        except Exception:
            logger.warning(
                "Failed to load BrandProfile for project %s", project_id, exc_info=True
            )

        _cb: CustomerBrief | None = None
        try:
            _cb = (
                session.query(CustomerBrief)
                .filter(CustomerBrief.project_id == project_id)
                .first()
            )
        except Exception:
            logger.warning(
                "Failed to load CustomerBrief for project %s", project_id, exc_info=True
            )

        _target_audience: str = (_cb.target_audience or "") if _cb else ""
        _product_usp: str = (_cb.product_usp or "") if _cb else ""
        _listing_bullets: str = (_cb.listing_bullets or "") if _cb else ""
        _product_category: str = (
            (getattr(_pp, "product_category", None) or "") if _pp else ""
        )

        _elastic = _resolve_elastic(_bp)
        _anchor = _style_anchor(
            getattr(_bp, "brand_tone", None) if _bp else None,
            getattr(_bp, "color_system", None) if _bp else None,
            _elastic["photo_style"],
        )
        _used_compositions: list[str] = []

        # 预收集已生成槽位的视觉标签，供 F4 真实避重和动态色彩锚定使用
        _used_visual_tags: set[tuple[str, str, str]] = set()
        _generated_color_temps: list[str] = []
        for _pre in plans:
            _g_angle = getattr(_pre, "generated_angle", None) or ""
            _g_shot = getattr(_pre, "generated_shot_type", None) or ""
            _g_lighting = getattr(_pre, "generated_lighting", None) or ""
            _g_ct = getattr(_pre, "generated_color_temp", None) or ""
            if _g_angle or _g_shot or _g_lighting:
                _used_visual_tags.add((_g_angle, _g_shot, _g_lighting))
            if _g_ct:
                _generated_color_temps.append(_g_ct)
        _dominant_color_temp: str = ""
        if _generated_color_temps:
            from collections import Counter as _Counter

            _dominant_color_temp = _Counter(_generated_color_temps).most_common(1)[0][0]

        _project = None
        _reference_assets: dict[str, list[str]] = {}
        _custom_requirements: dict = {}
        _product_anchor: dict = {}
        try:
            from pipeline.layers.custom_requirement_parser import parse_custom_requirements
            from pipeline.layers.product_visual_anchor import ensure_product_visual_anchor
            from pipeline.layers.project_constraints import enrich_customer_brief, load_customer_brief
            from pipeline.layers.reference_asset_normalizer import normalize_reference_assets

            _project = session.get(__import__("pipeline.models.project", fromlist=["Project"]).Project, project_id)
            if _project is not None:
                _brief_data = enrich_customer_brief(load_customer_brief(_project))
                _reference_assets = normalize_reference_assets(_brief_data)
                _custom_requirements = parse_custom_requirements(_brief_data)
                _product_anchor = ensure_product_visual_anchor(
                    _project, session, _reference_assets
                )
        except Exception:
            logger.warning(
                "Failed to load product constraints for project %s", project_id, exc_info=True
            )

        _comp: CompetitorListing | None = None
        try:
            _comp = (
                session.query(CompetitorListing)
                .filter(CompetitorListing.project_id == project_id)
                .first()
            )
        except Exception:
            logger.warning(
                "Failed to load CompetitorListing for project %s",
                project_id,
                exc_info=True,
            )
        _comp_bullets = (_comp.bullet_points or "")[:200] if _comp else ""
        _comp_hint = (
            _comp_positioning_hint(_comp.price, _comp.rating, _comp.category_rank)
            if _comp
            else ""
        )

        result: dict[str, str] = {}
        for plan in plans:
            asset = (
                session.query(PromptAsset)
                .filter(
                    PromptAsset.project_id == project_id,
                    PromptAsset.slot_index == plan.slot_index,
                )
                .order_by(PromptAsset.version.desc())
                .first()
            )

            if asset is None:
                logger.warning(
                    "No PromptAsset for project %s slot %s, skipping",
                    project_id,
                    plan.slot_index,
                )
                continue

            if asset.user_edited:
                result[_slot_label(plan.slot_index)] = asset.prompt_text
                continue

            variables = {
                # composition_preference 从 ELASTIC 字段补充构图偏好
                "composition": " ".join(
                    filter(
                        None,
                        [
                            _tag_text(plan.layout_tag),
                            plan.angle_tag,
                            _elastic["composition_preference"],
                        ],
                    )
                ),
                "subject": _cosmo_subject(
                    plan.intent_tag,
                    base_subject=" ".join(
                        filter(
                            None,
                            [
                                plan.visual_focus or plan.description,
                                getattr(plan, "subject_material", None),
                                _elastic["model_type"],
                            ],
                        )
                    ),
                    target_audience=_target_audience,
                    product_usp=_product_usp,
                ),
                # 专业灯光方案按 intent 分支注入；scene_preference 为 ELASTIC 飞轮字段
                "environment": (
                    _lighting_for_intent(plan.intent_tag, plan.lighting_tag)
                    + (f", {plan.background_tag}" if plan.background_tag else "")
                    + (
                        f", {_elastic['scene_preference']}"
                        if _elastic["scene_preference"]
                        else ""
                    )
                ),
                # 镜头语言按 intent 分支注入
                "camera": _camera_for_intent(
                    plan.intent_tag,
                    plan.dof_tag,
                    getattr(plan, "shot_type", None),
                ),
                "tone": _cosmo_tone(
                    base_tone=" ".join(
                        filter(
                            None,
                            [
                                _tag_text(plan.style_tag)[:80],
                                (plan.key_message or "")[:150],
                                (getattr(plan, "overlay_text", None) or "")[:60],
                            ],
                        )
                    ),
                    listing_bullets=_listing_bullets,
                ),
                # material_texture 从 ELASTIC 字段注入；各子字段独立限长
                "constraints": " ".join(
                    filter(
                        None,
                        [
                            _tag_text(plan.color_tag)[:80],
                            (plan.competitor_contrast or "")[:120],
                            _comp_hint,
                            _comp_bullets,
                            _elastic["material_texture"],
                        ],
                    )
                ),
            }

            if _dominant_color_temp and not getattr(plan, "generated_color_temp", None):
                _ct_map = {
                    "暖调": "maintain warm color temperature consistent with the series",
                    "中性": "maintain neutral color temperature consistent with the series",
                    "冷调": "maintain cool color temperature consistent with the series",
                }
                _ct_hint = _ct_map.get(_dominant_color_temp, "")
                if _ct_hint:
                    variables["constraints"] = " ".join(
                        filter(None, [variables["constraints"], _ct_hint])
                    )

            _v_ordered = [
                variables["subject"],
                variables["composition"],
                variables["environment"],
                variables["camera"],
                variables["tone"],
                variables["constraints"],
            ]

            _comparison = getattr(plan, "comparison_structure", None)
            if plan.intent_tag == "INT_COMPARISON" and _comparison:
                _v_ordered.append(f"split-screen layout: {_comparison}")

            _prompt_core = ", ".join(p for p in _v_ordered if p and p.strip())

            _constraint_blocks: list[str] = []
            try:
                from pipeline.layers.custom_requirement_parser import build_user_requirement_lock
                from pipeline.layers.product_visual_anchor import build_product_identity_lock
                from pipeline.layers.reference_policy import build_intent_reference_rule

                _constraint_blocks.append(
                    build_product_identity_lock(_product_anchor, plan.intent_tag)
                )
                _constraint_blocks.append(
                    build_user_requirement_lock(_custom_requirements, plan.intent_tag)
                )
                _constraint_blocks.append(
                    build_intent_reference_rule(plan.intent_tag, _reference_assets)
                )
                _constraint_blocks.append(_MARKETPLACE_LANGUAGE_POLICY)
            except Exception:
                logger.warning(
                    "Failed to build constraint locks for project %s slot %s",
                    project_id,
                    plan.slot_index,
                    exc_info=True,
                )

            _prompt_core = "\n\n".join(
                [block for block in _constraint_blocks if block]
                + [_prompt_core, _anchor]
            )

            _qa = _QA_CONSTRAINTS.get(plan.intent_tag or "", [])
            if _qa:
                _prompt_core += "\n" + ", ".join(_qa)

            # F4 真实避重：基于已生成视觉标签（angle/shot_type/lighting）的组合
            _angle_key = getattr(plan, "generated_angle", None) or (
                plan.angle_tag or ""
            )
            _shot_key = getattr(plan, "generated_shot_type", None) or (
                getattr(plan, "shot_type", None) or ""
            )
            _lighting_key = getattr(plan, "generated_lighting", None) or (
                plan.lighting_tag or ""
            )
            _tag_combo = (_angle_key, _shot_key, _lighting_key)
            if any(_tag_combo) and _tag_combo in _used_visual_tags:
                _prompt_core += ", avoid repeating the same angle, shot type, and lighting as previous shots"
            else:
                if any(_tag_combo):
                    _used_visual_tags.add(_tag_combo)
                _comp_pref = variables["composition"]
                if _comp_pref and _comp_pref not in _used_compositions:
                    _used_compositions.append(_comp_pref)

            _neg_parts = []
            _intent_neg = _intent_negative_constraints(plan.intent_tag)
            if _intent_neg:
                _neg_parts.append(_intent_neg)
            _slot_neg = getattr(plan, "negative_prompt", None)
            if _slot_neg:
                _neg_parts.append(_slot_neg.strip())
            if asset.negative_prompt:
                _neg_parts.append(asset.negative_prompt.strip())
            if _neg_parts:
                _prompt_core += f"\n--no {', '.join(_neg_parts)}"

            _constraint_blocks = [
                _intent_composition_lock(plan.intent_tag),
                _intent_negative_constraints(plan.intent_tag),
                _MARKETPLACE_LANGUAGE_POLICY,
            ]
            _prompt_core = "\n".join(block for block in _constraint_blocks if block) + "\n" + _prompt_core
            _prompt_core += f"\n{_text_constraint(plan.intent_tag)}"
            _prompt_core = _sanitize_cjk_for_image_prompt(_prompt_core)

            _custom = getattr(plan, "custom_prompt", None)
            if _custom and _custom.strip():
                _prompt_core += f"\n{_custom.strip()}"

            _slot_type = _slot_label(plan.slot_index)
            try:
                _fw_rows = (
                    session.query(FlywheelExample.prompt_text)
                    .filter(
                        FlywheelExample.slot_type == _slot_type,
                        FlywheelExample.combined_score >= 4.0,
                        *(
                            [FlywheelExample.product_category == _product_category]
                            if _product_category
                            else []
                        ),
                    )
                    .order_by(FlywheelExample.combined_score.desc())
                    .limit(3)
                    .all()
                )
                _fw_shots = [r[0] for r in _fw_rows if r[0]]
            except Exception:
                logger.warning(
                    "Failed to fetch FlywheelExamples for project %s slot %s",
                    project_id,
                    plan.slot_index,
                    exc_info=True,
                )
                _fw_shots = []

            if _fw_shots:
                _prompt_core += "\n\nHigh-performing reference prompts:\n" + "\n".join(
                    f"- {ex}" for ex in _fw_shots
                )

            label = _slot_label(plan.slot_index)
            try:
                prompt_text = _prompt_core
                if plan.gen_params:
                    from pipeline.config import config as _cfg

                    _model = (_cfg.image_model or "").lower()
                    if any(kw in _model for kw in ("midjourney", "mj-", "/mj")):
                        prompt_text = prompt_text + " " + plan.gen_params
                    else:
                        _p = plan.gen_params
                        _natural: list[str] = []
                        import re as _re

                        _ar = _re.search(r"--ar\s+([\d:]+)", _p)
                        if _ar:
                            _natural.append(f"aspect ratio {_ar.group(1)}")
                        if "--style raw" in _p:
                            _natural.append(
                                "raw photographic style, no artistic filter"
                            )
                        _st = _re.search(r"--stylize\s+(\d+)", _p)
                        if _st:
                            _v = int(_st.group(1))
                            if _v >= 600:
                                _natural.append("highly stylized")
                            elif _v >= 300:
                                _natural.append("moderately stylized")
                        if _natural:
                            prompt_text = prompt_text + ", " + ", ".join(_natural)
                result[label] = prompt_text

                # 把本次实际注入的 ELASTIC 字段值写入 visual_tags，供飞轮归因读取
                _vtags: dict[str, str] = {k: v for k, v in _elastic.items() if v}
                _cached_slot_index = plan.slot_index
                try:
                    asset.visual_tags = json.dumps(_vtags, ensure_ascii=False)
                    session.add(asset)
                    session.commit()
                except Exception as _vt_exc:
                    session.rollback()
                    logger.warning(
                        "visual_tags 写入失败 project=%s slot=%s: %s",
                        project_id,
                        _cached_slot_index,
                        _vt_exc,
                    )

            except ValueError as exc:
                logger.warning("Skipping slot %s: %s", plan.slot_index, exc)

        return result
