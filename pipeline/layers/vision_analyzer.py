"""Vision analysis layer — supports OpenAI (default) and Gemini Vision providers."""

import base64
import json
import mimetypes
import os
import re
from urllib.parse import urlparse

import httpx
from pipeline.config import config
from pipeline.layers.amazon_data import scrape_listing_images
from pipeline.constants.tags import (
    INTENT_TAGS,
    ROLE_TAGS,
    COLOR_TAGS,
    LAYOUT_TAGS,
    STYLE_TAGS,
    TAG_LOOKUP,
)
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.vision_analyzer")

__all__ = ["analyze_image", "analyze_competitor_listing", "save_tags_to_db"]

# 5 层标签体系的 prompt
_SYSTEM_PROMPT = """You are an expert e-commerce image analyst. Analyze the provided image and return a JSON object with exactly these keys:

- "intent_tags" (array of strings): The intent(s) of the image. Each must be one of:
  INT_HERO, INT_LIFESTYLE, INT_INFOGRAPHIC, INT_COMPARISON, INT_DETAIL, INT_PACKAGING

- "role_tags" (array of strings): All visual roles present in the image. Each must be one of:
  ROLE_BG, ROLE_PRODUCT, ROLE_PROP, ROLE_MODEL, ROLE_TEXT, ROLE_ICON, ROLE_SHADOW

- "color_tags" (array of strings): The dominant color tone(s). Each must be one of:
  CLR_WHITE, CLR_LIGHT, CLR_DARK, CLR_WARM, CLR_COOL, CLR_BRAND

- "layout_tags" (array of strings): The layout style(s). Each must be one of:
  LAY_CENTER, LAY_RULE3, LAY_FLAT, LAY_SPLIT, LAY_GRID

- "style_tags" (array of strings): The visual style(s). Each must be one of:
  STY_MINIMAL, STY_PREMIUM, STY_PLAYFUL, STY_TECH, STY_NATURAL, STY_BOLD

- "composition" (string): A concise description of the image composition and layout.

- "color_palette" (array of strings): The 3-5 dominant hex color codes, e.g. ["#FFFFFF", "#333333"].

- "text_detected" (boolean): true if any visible text is present in the image, false otherwise.

- "quality_score" (number): A competitor image quality score from 0 to 100. Score using FOUR groups:

  GROUP A — Platform Compliance (25 pts):
  Apply the rules below based on the image's detected intent_tags. Use the FIRST matching category:

  If intent_tags contains INT_HERO:
    - Pure white or near-white background (no gradients, shadows, or scene elements): 0-10 pts
    - Product fill rate ≥ 85% of frame (no excessive empty space): 0-8 pts
    - No watermarks, logos, text, or any promotional overlays: 0-7 pts

  If intent_tags contains INT_LIFESTYLE:
    - Scene is natural, contextually believable, and visually coherent (pure white NOT required): 0-10 pts
    - Product is clearly identifiable and prominent within the scene (strict fill rate NOT required): 0-8 pts
    - No unrelated watermarks or logos (incidental scene text such as signage is acceptable): 0-7 pts

  If intent_tags contains INT_INFOGRAPHIC, INT_COMPARISON, or INT_PACKAGING:
    - Background suits the image type (solid color, gradient, or subtle texture are all acceptable): 0-10 pts
    - Product is clearly visible and well-composed (≥85% fill rate NOT required): 0-8 pts
    - No unrelated watermarks or logos; intentional callout text and graphic overlays are allowed: 0-7 pts

  If intent_tags contains INT_DETAIL:
    - Background supports detail visibility (not required to be pure white; neutral or gradient is fine): 0-10 pts
    - The key product detail or feature is the dominant subject of the frame: 0-8 pts
    - No unrelated watermarks or logos (technical labels and callouts are acceptable): 0-7 pts

  If none of the above match, apply INT_HERO rules as the default.

  GROUP B — Technical Quality (15 pts):
    - Sharpness and focus clarity: 0-6 pts
    - Exposure and color accuracy (no overexposure/muddy tones): 0-5 pts
    - Apparent resolution (not pixelated or compressed): 0-4 pts

  GROUP E — Commercial Quality (15 pts):
    - Scene is contextually appropriate and believable: 0-7 pts
    - Image clearly matches a product listing intent (Hero/Lifestyle/Infographic): 0-8 pts

  GROUP F — COSMO Signal Value (45 pts):
    F1 Intent Clarity (15 pts): The image's purpose (Hero showcase / Lifestyle in-use / Infographic features) is immediately obvious without reading text.
    F2 Scene & Audience Signal (15 pts): The image shows WHO uses the product, WHERE, or WHEN — visible use-context, setting, or target demographic cues.
    F3 Feature / Attribute Communication (10 pts): Functional capabilities or key properties are conveyed visually; if Infographic, key benefit text is legible and prominent.
    F4 Slot Diversity Value (5 pts): The image covers a visual angle or use-case NOT already represented by a standard hero shot — deduct up to 5 pts if this image is near-duplicate of a plain white-background hero.

  Sum all groups. Return only the final integer total (0–100). Do NOT return sub-scores.

- "lighting" (string): Light source type. One of: 柔光棚, 单侧强光, 顶光, 自然光, 环形灯

- "shot_type" (string): Shot distance. One of: 远景, 中景, 近景, 特写, 微距

- "angle" (string): Camera angle. One of: 正面, 3/4角, 侧面, 俯拍, 仰拍

- "dof" (string): Depth of field. One of: 全清, 轻虚化, 重虚化

- "background_material" (string): Background type. One of: 纯白, 纯黑, 渐变, 大理石, 木纹, 场景化

- "subject_material" (string): Main subject material. One of: 金属, 玻璃, 磨砂, 皮革, 布料, 塑料, 其他

- "shadow_intensity" (string): Shadow strength. One of: 无, 轻, 中, 强

- "saturation" (string): Color saturation. One of: 低, 正常, 高

- "color_temp" (string): Color temperature. One of: 暖调, 中性, 冷调

- "mj_prompt" (string): Write a concise Midjourney prompt in English for this image (max 80 words).

Respond ONLY with valid JSON. No markdown, no explanation, no code blocks."""

# 5 层标签字段名及对应层名
TAG_LAYER_FIELDS = {
    "intent_tags": "INTENT",
    "role_tags": "ROLE",
    "color_tags": "COLOR",
    "layout_tags": "LAYOUT",
    "style_tags": "STYLE",
}

_DEFAULT_RESULT = {
    "intent_tags": [],
    "role_tags": [],
    "color_tags": [],
    "layout_tags": [],
    "style_tags": [],
    "composition": "",
    "color_palette": [],
    "text_detected": False,
    "quality_score": None,  # None 表示"未分析"，0 表示"质量极差"，两者语义不同
    "lighting": "",
    "shot_type": "",
    "angle": "",
    "dof": "",
    "background_material": "",
    "subject_material": "",
    "shadow_intensity": "",
    "saturation": "",
    "color_temp": "",
    "mj_prompt": "",
}


def _local_image_path(image_ref: str) -> str | None:
    """Return a filesystem path when image_ref points to a local file."""
    parsed = urlparse(image_ref)
    if parsed.scheme == "file":
        path = parsed.path
    elif parsed.scheme in ("http", "https", "data"):
        return None
    else:
        path = image_ref
    return path if path and os.path.isfile(path) else None


def _local_image_data_url(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{encoded}"


def analyze_image(image_url: str, *, image_id: int | None = None) -> dict:
    """分析图片，返回 5 层标签 + 元信息。可选传 image_id 自动写入 tag_assignment 表。

    image_url may be an HTTP(S) URL, file:// URL, or local filesystem path.
    """
    if config.vision_provider == "gemini":
        result = _analyze_image_gemini(image_url)
    else:
        result = _analyze_image_openai(image_url)

    if image_id is not None:
        save_tags_to_db(image_id, result)

    return result


def save_tags_to_db(image_id: int, analysis: dict, entity_type: str = "image") -> int:
    """将 5 层标签写入 tag_assignment 表，返回写入条数。"""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from pipeline.models.base import get_session
    from pipeline.models.tag_assignment import TagAssignment

    session = get_session()
    count = 0
    try:
        for field, layer in TAG_LAYER_FIELDS.items():
            tags = analysis.get(field, [])
            if not isinstance(tags, list):
                tags = [tags] if tags else []
            for tag_code in tags:
                if not isinstance(tag_code, str):
                    continue
                stmt = sqlite_insert(TagAssignment).values(
                    entity_type=entity_type,
                    entity_id=image_id,
                    tag_code=tag_code,
                    tag_layer=layer,
                )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["entity_type", "entity_id", "tag_code"]
                )
                session.execute(stmt)
                count += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return count


def _normalize_result(result: dict) -> dict:
    """将 LLM 返回的 raw dict 规范化为 5 层标签格式，兼容旧版 intent_tag 字段。"""
    final = dict(_DEFAULT_RESULT)
    for k in _DEFAULT_RESULT:
        if k in result:
            final[k] = result[k]
    if "intent_tag" in result and not final.get("intent_tags"):
        val = result["intent_tag"]
        final["intent_tags"] = [val] if isinstance(val, str) else val
    for field in TAG_LAYER_FIELDS:
        if not isinstance(final[field], list):
            final[field] = [final[field]] if final[field] else []
    # 向后兼容：保留 intent_tag 字段供下游模块使用
    if final["intent_tags"]:
        final["intent_tag"] = final["intent_tags"][0]
    else:
        final["intent_tag"] = "INT_HERO"
    return final


def _analyze_image_gemini(image_url: str) -> dict:
    import tempfile, urllib.request
    from pipeline.adapters.gemini_vision_adapter import GeminiVisionAdapter

    adapter = GeminiVisionAdapter()
    local_path = _local_image_path(image_url)
    if local_path is not None:
        tmp_path = local_path
    else:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(image_url, tmp_path)
    raw = adapter.analyze(tmp_path, _SYSTEM_PROMPT)
    analysis_text = raw.get("analysis", "")
    try:
        cleaned = analysis_text.strip()
        m = re.match(r"^```(?:json)?\s*\n?(.*?)```\s*$", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "Gemini vision JSON parse failed; raw response head: %s",
            analysis_text[:300],
        )
        return dict(_DEFAULT_RESULT)
    return _normalize_result(result)


def _analyze_image_openai(image_url: str) -> dict:
    if not config.openai_api_key:
        raise ValueError("E_VISION_001: openai_api_key is empty or not configured.")

    proxy = config.http_proxy or None
    local_path = _local_image_path(image_url)
    image_payload_url = image_url

    if local_path is not None:
        image_payload_url = _local_image_data_url(local_path)
    else:
        try:
            head_resp = httpx.head(
                image_url, follow_redirects=True, timeout=10, proxy=proxy
            )
            if head_resp.status_code >= 400:
                raise ValueError(
                    f"E_VISION_002: Image URL inaccessible (HTTP {head_resp.status_code}): {image_url}"
                )
        except httpx.RequestError as exc:
            raise ValueError(
                f"E_VISION_002: Image URL inaccessible — network error: {exc}"
            ) from exc

    model = config.openai_model or "gpt-4o"
    endpoint = f"{config.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_payload_url, "detail": "high"},
                    }
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0,
    }

    logger.debug("Calling Vision API for image: %s", image_url)
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = httpx.post(
                endpoint, headers=headers, json=payload, timeout=60, proxy=proxy
            )
            response.raise_for_status()
            last_exc = None
            break
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"E_VISION_003: API call failed (HTTP {exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "Vision API attempt %d/3 failed for %s: %s", attempt, image_url, exc
            )
            if attempt < 3:
                import time

                time.sleep(2**attempt)
    if last_exc is not None:
        raise ValueError(
            f"E_VISION_003: API call failed — network error: {last_exc}"
        ) from last_exc

    try:
        data = response.json()
        finish_reason = data["choices"][0].get("finish_reason", "")
        if finish_reason == "length":
            logger.warning(
                "Vision API response truncated (finish_reason=length) for %s — increase max_tokens or simplify prompt.",
                image_url,
            )
        raw_content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"E_VISION_003: Unexpected API response structure: {exc}"
        ) from exc

    try:
        cleaned = raw_content
        # Try to extract JSON from markdown code block (re.search instead of re.match
        # so we handle leading whitespace/text before the fence)
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        else:
            # Fallback: extract raw JSON object
            m2 = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m2:
                cleaned = m2.group(0).strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse Vision API JSON response for %s; returning default dict. Raw: %s",
            image_url,
            raw_content[:500],
        )
        return dict(_DEFAULT_RESULT)

    return _normalize_result(result)


def analyze_competitor_listing(asin: str) -> list[dict]:
    """Analyze all images of a competitor listing.
    Internally calls scrape_listing_images (from amazon_data) + analyze_image for each.
    Returns list of dicts (same format as analyze_image).
    """
    logger.info("Fetching listing images for ASIN: %s", asin)
    image_slots = scrape_listing_images(asin)

    results = []
    for _img_slot, url in image_slots:
        try:
            result = analyze_image(url)
            results.append(result)
        except Exception as exc:
            logger.warning("Skipping image %s for ASIN %s — error: %s", url, asin, exc)
            continue

    logger.info(
        "Analyzed %d/%d images for ASIN %s", len(results), len(image_slots), asin
    )
    return results
