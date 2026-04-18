import json
import os
from typing import Optional

from pipeline.utils.logger import setup_logger
from pipeline.models.competitor_listing import CompetitorListing

logger = setup_logger("aip.listing_analyzer")

_GEMINI_MODEL = "gemini-2.0-flash"

_SELLING_POINTS_PROMPT = (
    "You are an Amazon listing analyst. Given the product title and metadata below, "
    "extract 3-5 key selling points as a JSON object where keys are short snake_case "
    "labels and values are one-sentence descriptions.\n\n"
    "Product: {title}\nMetadata: {metadata}\n\n"
    "Return ONLY valid JSON, no markdown fences."
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


def analyze_listing(asin: str, keepa_data: Optional[dict]) -> CompetitorListing:
    title: Optional[str] = None
    bullet_points: Optional[str] = None
    selling_points_map = "{}"

    if keepa_data:
        title = keepa_data.get("title")
        bullet_points = json.dumps(
            {k: v for k, v in keepa_data.items() if k != "title"}
        )

    if title:
        metadata_str = bullet_points or "{}"
        prompt = _SELLING_POINTS_PROMPT.format(title=title, metadata=metadata_str)
        selling_points_map = _call_gemini(prompt)

    return CompetitorListing(
        asin=asin,
        title=title,
        bullet_points=bullet_points,
        selling_points_map=selling_points_map,
    )
