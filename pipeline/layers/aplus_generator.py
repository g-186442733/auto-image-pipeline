import json
import logging
import os

from pipeline.models.aplus_content import APlusContent

log = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.0-flash"

_MODULE_TYPES = [
    "HERO",
    "BENEFIT",
    "DETAIL",
    "LIFESTYLE",
    "COMPARISON",
    "BRAND_STORY",
    "CROSS_SELL",
]

_DEFAULT_MODULES = [
    {
        "module_type": "HERO",
        "headline": "产品主图",
        "body": "展示产品核心卖点",
        "layout": "full_width",
        "slot_index": None,
    },
    {
        "module_type": "BENEFIT",
        "headline": "核心优势",
        "body": "突出产品独特功能与价值",
        "layout": "text_left_image_right",
        "slot_index": None,
    },
    {
        "module_type": "DETAIL",
        "headline": "细节展示",
        "body": "呈现产品工艺与材质细节",
        "layout": "image_left_text_right",
        "slot_index": None,
    },
    {
        "module_type": "LIFESTYLE",
        "headline": "使用场景",
        "body": "展示产品在真实场景中的使用效果",
        "layout": "full_width",
        "slot_index": None,
    },
    {
        "module_type": "COMPARISON",
        "headline": "对比优势",
        "body": "与同类产品的核心指标对比",
        "layout": "comparison_table",
        "slot_index": None,
    },
    {
        "module_type": "BRAND_STORY",
        "headline": "品牌故事",
        "body": "讲述品牌理念与发展历程",
        "layout": "text_left_image_right",
        "slot_index": None,
    },
    {
        "module_type": "CROSS_SELL",
        "headline": "搭配推荐",
        "body": "推荐相关配件与套装组合",
        "layout": "grid_3col",
        "slot_index": None,
    },
]

_APLUS_PROMPT_TMPL = """\
You are an Amazon A+ Content strategist. Generate a 7-module A+ storyboard.

Plan modules dynamically based on uploaded references, product facts, and user requirements.
Use these module types as candidates, not mandatory fixed output:
HERO, BENEFIT, DETAIL, LIFESTYLE, COMPARISON, BRAND_STORY, CROSS_SELL.

For each module, provide:
- module_type: one of the 7 types above
- headline: max 30 characters, compelling title
- body: max 150 characters, descriptive text
- layout: full_width | text_left_image_right | image_left_text_right | comparison_table | grid_3col
- slot_index: integer (0-based) of the most suitable product shot from the Slot List below, or null if no slot fits

=== Listing Information ===
Title: {listing_title}
Bullets: {listing_bullets}
Keywords: {listing_keywords}
USP: {product_usp}

=== Brand Profile ===
Brand Tone: {brand_tone}
Color System: {color_system}
Guidelines: {guidelines}

=== Competitor Reference ===
{competitor_summary}

=== Slot List (available product shots) ===
{slot_summary}

=== User Requirements ===
{user_requirements}

Return ONLY valid JSON with a 'modules' array containing 3 to 7 objects. No markdown fences.
Do not create modules that require missing references unless user explicitly allows inference.
"""


def _build_context(project_id: int, session) -> dict:
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.models.product_profile import ProductProfile
    from pipeline.models.competitor_listing import CompetitorListing
    from pipeline.models.slot_plan import SlotPlan
    from pipeline.models.project import Project

    ctx: dict = {
        "listing_title": "",
        "listing_bullets": "",
        "listing_keywords": "",
        "product_usp": "",
        "brand_tone": "",
        "color_system": "",
        "guidelines": "",
        "competitor_summary": "暂无竞品信息",
        "slot_summary": "暂无 Slot 信息",
        "user_requirements": "未填写",
    }

    proj = session.query(Project).filter_by(id=project_id).first()
    if proj is None:
        return ctx

    # 读取产品简报（从 project.customer_brief JSON 字段读取，customer_briefs 表从未写入）
    if proj.customer_brief:
        try:
            brief_data = json.loads(proj.customer_brief)
            ctx["listing_title"] = brief_data.get("listing_title") or ""
            ctx["listing_bullets"] = brief_data.get("listing_bullets") or ""
            ctx["listing_keywords"] = brief_data.get("listing_keywords") or ""
            ctx["product_usp"] = brief_data.get("product_usp") or ""
            from pipeline.layers.custom_requirement_parser import (
                build_user_requirement_lock,
                parse_custom_requirements,
            )

            custom_requirements = parse_custom_requirements(brief_data)
            ctx["user_requirements"] = (
                build_user_requirement_lock(custom_requirements) or "未填写"
            )
        except (json.JSONDecodeError, TypeError):
            pass

    # 读取品牌档案（通过 ProductProfile 关联）
    if proj.product_profile_id:
        try:
            pp = (
                session.query(ProductProfile)
                .filter_by(id=proj.product_profile_id)
                .first()
            )
            if pp and pp.brand_profile_id:
                bp = (
                    session.query(BrandProfile)
                    .filter_by(id=pp.brand_profile_id)
                    .first()
                )
                if bp:
                    ctx["brand_tone"] = bp.brand_tone or ""
                    ctx["color_system"] = bp.color_system or ""
                    ctx["guidelines"] = bp.guidelines or ""
        except Exception:
            log.warning("aplus_generator: 读取 BrandProfile 失败", exc_info=True)

    # 读取竞品摘要（取前 3 条）
    competitors = (
        session.query(CompetitorListing).filter_by(project_id=project_id).limit(3).all()
    )
    if competitors:
        lines = []
        for c in competitors:
            bullets_preview = ""
            if c.bullet_points:
                try:
                    parsed = json.loads(c.bullet_points)
                    if isinstance(parsed, list):
                        bullets_preview = " | ".join(parsed[:2]) if parsed else ""
                    elif isinstance(parsed, dict):
                        bullets_preview = " | ".join(list(parsed.values())[:2])
                    else:
                        bullets_preview = str(parsed)[:100]
                except (json.JSONDecodeError, TypeError, KeyError):
                    bullets_preview = str(c.bullet_points)[:100]
            lines.append(f"- {c.title or c.asin}: {bullets_preview}")
        ctx["competitor_summary"] = "\n".join(lines)

    # 读取 Slot 计划（让 LLM 知道有哪些 slot 可引用）
    slots = (
        session.query(SlotPlan)
        .filter_by(project_id=project_id)
        .order_by(SlotPlan.slot_index)
        .all()
    )
    if slots:
        lines = []
        for s in slots:
            label = s.title or f"Slot {s.slot_index}"
            intent = s.intent_tag or ""
            key_msg = s.key_message or s.description or ""
            lines.append(f"[{s.slot_index}] {label} — {intent} {key_msg}".strip())
        ctx["slot_summary"] = "\n".join(lines)

    return ctx


def _call_gemini(prompt: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return "{}"
    try:
        import google.generativeai as genai
    except ImportError:
        return "{}"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(_GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text


def generate_aplus_storyboard(
    project_id: int,
    session=None,
) -> list[APlusContent]:
    ctx = _build_context(project_id, session) if session else {}
    prompt = _APLUS_PROMPT_TMPL.format(
        listing_title=ctx.get("listing_title") or "(未填写)",
        listing_bullets=ctx.get("listing_bullets") or "(未填写)",
        listing_keywords=ctx.get("listing_keywords") or "(未填写)",
        product_usp=ctx.get("product_usp") or "(未填写)",
        brand_tone=ctx.get("brand_tone") or "(未填写)",
        color_system=ctx.get("color_system") or "(未填写)",
        guidelines=ctx.get("guidelines") or "(未填写)",
        competitor_summary=ctx.get("competitor_summary") or "暂无竞品信息",
        slot_summary=ctx.get("slot_summary") or "暂无 Slot 信息",
        user_requirements=ctx.get("user_requirements") or "未填写",
    )

    raw = _call_gemini(prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict) and "modules" in parsed:
        candidate = parsed["modules"]
        if isinstance(candidate, list) and 3 <= len(candidate) <= 7:
            modules_data = candidate
        else:
            log.warning(
                "generate_aplus_storyboard: unexpected modules structure for project %s, using default",
                project_id,
            )
            modules_data = _DEFAULT_MODULES
    else:
        log.warning(
            "generate_aplus_storyboard: Gemini returned no modules for project %s, using default",
            project_id,
        )
        modules_data = _DEFAULT_MODULES

    records: list[APlusContent] = []
    for i, mod in enumerate(modules_data):
        module_type = mod.get("module_type", _MODULE_TYPES[i])
        if module_type not in _MODULE_TYPES:
            module_type = _MODULE_TYPES[i]

        headline = (mod.get("headline") or "")[:30]
        body_text = (mod.get("body") or "")[:150]

        raw_slot = mod.get("slot_index")
        slot_index = int(raw_slot) if isinstance(raw_slot, (int, float)) else None

        record = APlusContent(
            project_id=project_id,
            module_type=module_type,
            headline=headline,
            body_text=body_text,
            layout=mod.get("layout"),
            position_index=i,
            slot_index=slot_index,
        )
        records.append(record)

    if session is not None:
        session.query(APlusContent).filter(
            APlusContent.project_id == project_id,
        ).delete()
        for r in records:
            session.add(r)
        session.commit()

    return records
