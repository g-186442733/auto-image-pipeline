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
    },
    {
        "module_type": "BENEFIT",
        "headline": "核心优势",
        "body": "突出产品独特功能与价值",
        "layout": "text_left_image_right",
    },
    {
        "module_type": "DETAIL",
        "headline": "细节展示",
        "body": "呈现产品工艺与材质细节",
        "layout": "image_left_text_right",
    },
    {
        "module_type": "LIFESTYLE",
        "headline": "使用场景",
        "body": "展示产品在真实场景中的使用效果",
        "layout": "full_width",
    },
    {
        "module_type": "COMPARISON",
        "headline": "对比优势",
        "body": "与同类产品的核心指标对比",
        "layout": "comparison_table",
    },
    {
        "module_type": "BRAND_STORY",
        "headline": "品牌故事",
        "body": "讲述品牌理念与发展历程",
        "layout": "text_left_image_right",
    },
    {
        "module_type": "CROSS_SELL",
        "headline": "搭配推荐",
        "body": "推荐相关配件与套装组合",
        "layout": "grid_3col",
    },
]

_APLUS_PROMPT = (
    "You are an Amazon A+ Content strategist. Generate a 7-module A+ storyboard "
    "for the product listing.\n\n"
    "Required module types (exactly 7, in this order): "
    "HERO, BENEFIT, DETAIL, LIFESTYLE, COMPARISON, BRAND_STORY, CROSS_SELL.\n\n"
    "For each module, provide:\n"
    "- module_type: one of the 7 types above\n"
    "- headline: max 30 characters, compelling title\n"
    "- body: max 150 characters, descriptive text\n"
    "- layout: layout suggestion (full_width / text_left_image_right / "
    "image_left_text_right / comparison_table / grid_3col)\n\n"
    "Product context:\n"
    "Project ID: {project_id}\n\n"
    "Return ONLY valid JSON with a 'modules' array containing exactly 7 objects. "
    "No markdown fences."
)


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
    prompt = _APLUS_PROMPT.format(project_id=project_id)

    modules_data = _DEFAULT_MODULES
    try:
        raw = _call_gemini(prompt)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "modules" in parsed:
            candidate = parsed["modules"]
            if isinstance(candidate, list) and len(candidate) == 7:
                modules_data = candidate
    except Exception:
        pass

    records: list[APlusContent] = []
    for i, mod in enumerate(modules_data):
        module_type = mod.get("module_type", _MODULE_TYPES[i])
        if module_type not in _MODULE_TYPES:
            module_type = _MODULE_TYPES[i]

        headline = (mod.get("headline") or "")[:30]
        body_text = (mod.get("body") or "")[:150]

        record = APlusContent(
            project_id=project_id,
            module_type=module_type,
            headline=headline,
            body_text=body_text,
            layout=mod.get("layout"),
            position_index=i,
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
