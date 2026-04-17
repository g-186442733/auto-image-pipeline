"""Vision analysis layer using GPT-4o Vision API."""

import json
import httpx
from pipeline.config import config
from pipeline.layers.amazon_data import scrape_listing_images
from pipeline.constants.tags import INTENT_TAGS, ROLE_TAGS, TAG_LOOKUP
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.vision_analyzer")

__all__ = ["analyze_image", "analyze_competitor_listing"]

_SYSTEM_PROMPT = """You are an expert e-commerce image analyst. Analyze the provided image and return a JSON object with exactly these keys:

- "intent_tag" (string): The primary intent of the image. Must be one of:
  INT_HERO, INT_LIFESTYLE, INT_INFOGRAPHIC, INT_COMPARISON, INT_DETAIL, INT_PACKAGING

- "role_tags" (array of strings): All visual roles present in the image. Each must be one of:
  ROLE_BG, ROLE_PRODUCT, ROLE_PROP, ROLE_MODEL, ROLE_TEXT, ROLE_ICON, ROLE_SHADOW

- "composition" (string): A concise description of the image composition and layout.

- "color_palette" (array of strings): The 3-5 dominant hex color codes, e.g. ["#FFFFFF", "#333333"].

- "text_detected" (boolean): true if any visible text is present in the image, false otherwise.

- "quality_score" (number): An overall image quality score from 0 to 100, considering sharpness,
  lighting, composition, and e-commerce suitability.

Respond ONLY with valid JSON. No markdown, no explanation, no code blocks."""

_DEFAULT_RESULT = {
    "intent_tag": "INT_HERO",
    "role_tags": [],
    "composition": "",
    "color_palette": [],
    "text_detected": False,
    "quality_score": 0,
}


def analyze_image(image_url: str) -> dict:
    """Analyze single image with GPT-4o Vision.
    Returns dict with keys:
        - intent_tag (str): e.g. "INT_HERO"
        - role_tags (list[str]): e.g. ["ROLE_PRODUCT", "ROLE_BG"]
        - composition (str): composition description
        - color_palette (list[str]): hex colors e.g. ["#FFFFFF", "#333333"]
        - text_detected (bool)
        - quality_score (float): 0-100
    Raises ValueError("E_VISION_001: ...") if openai_api_key is empty.
    Raises ValueError("E_VISION_002: ...") if image URL inaccessible.
    Raises ValueError("E_VISION_003: ...") if API call fails.
    """
    if not config.openai_api_key:
        raise ValueError("E_VISION_001: openai_api_key is empty or not configured.")

    try:
        head_resp = httpx.head(image_url, follow_redirects=True, timeout=10)
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
                        "image_url": {"url": image_url, "detail": "high"},
                    }
                ],
            },
        ],
        "max_tokens": 512,
        "temperature": 0,
    }

    logger.debug("Calling Vision API for image: %s", image_url)
    try:
        response = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"E_VISION_003: API call failed (HTTP {exc.response.status_code}): {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise ValueError(
            f"E_VISION_003: API call failed — network error: {exc}"
        ) from exc

    try:
        data = response.json()
        raw_content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"E_VISION_003: Unexpected API response structure: {exc}"
        ) from exc

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse Vision API JSON response for %s; returning default dict. Raw: %s",
            image_url,
            raw_content[:200],
        )
        return dict(_DEFAULT_RESULT)

    final = dict(_DEFAULT_RESULT)
    final.update({k: result[k] for k in _DEFAULT_RESULT if k in result})
    return final


def analyze_competitor_listing(asin: str) -> list[dict]:
    """Analyze all images of a competitor listing.
    Internally calls scrape_listing_images (from amazon_data) + analyze_image for each.
    Returns list of dicts (same format as analyze_image).
    """
    logger.info("Fetching listing images for ASIN: %s", asin)
    image_urls = scrape_listing_images(asin)

    results = []
    for url in image_urls:
        try:
            result = analyze_image(url)
            results.append(result)
        except Exception as exc:
            logger.warning("Skipping image %s for ASIN %s — error: %s", url, asin, exc)
            continue

    logger.info(
        "Analyzed %d/%d images for ASIN %s", len(results), len(image_urls), asin
    )
    return results
