import json
import os
import re
from typing import Optional

from pipeline.utils.logger import setup_logger
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.base import get_session

logger = setup_logger("aip.listing_analyzer")

_SELLING_POINTS_PROMPT = (
    "You are an Amazon listing analyst. Given the product title and metadata below, "
    "extract 3-5 key selling points as a JSON object where keys are short snake_case "
    "labels and values are one-sentence descriptions.\n\n"
    "Product: {title}\nMetadata: {metadata}\n\n"
    "Return ONLY valid JSON, no markdown fences."
)


def _call_gemini(prompt: str) -> str:
    import httpx
    from pipeline.config import config

    api_key = config.api_key
    if not api_key:
        return "{}"

    endpoint = f"{config.api_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.vision_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0,
    }

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return "{}"


def analyze_listing(asin: str, keepa_data: Optional[dict]) -> CompetitorListing:
    title: Optional[str] = None
    bullet_points: Optional[str] = None
    selling_points_map = "{}"

    price = None
    rating = None
    review_count = None
    main_image_url = None
    category_rank = None
    description = None

    if keepa_data:
        title = keepa_data.get("title")
        price = keepa_data.get("price")
        rating = keepa_data.get("rating")
        review_count = keepa_data.get("review_count") or keepa_data.get("reviewCount")
        main_image_url = keepa_data.get("main_image_url")
        category_rank = keepa_data.get("category_rank") or keepa_data.get("bsr_rank")
        description = keepa_data.get("description")

        raw_bullets = keepa_data.get("bullet_points") or keepa_data.get("features")
        if isinstance(raw_bullets, list):
            bullet_points = json.dumps(raw_bullets, ensure_ascii=False)
        elif raw_bullets:
            bullet_points = str(raw_bullets)
        else:
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
        price=price,
        rating=rating,
        review_count=review_count,
        bullet_points=bullet_points,
        description=description,
        main_image_url=main_image_url,
        category_rank=category_rank,
        selling_points_map=selling_points_map,
    )


class ListingAnalyzer:
    """Amazon listing 结构化分析器。"""

    @staticmethod
    def parse_bullets(listing_text: str) -> list:
        """将 listing 文本解析为 [{"text", "keyword", "position"}] 结构化列表。"""
        if not listing_text or not listing_text.strip():
            return []

        try:
            parsed = json.loads(listing_text)
            if isinstance(parsed, list):
                lines = [str(item).strip() for item in parsed]
            else:
                lines = listing_text.strip().split("\n")
        except (json.JSONDecodeError, TypeError):
            lines = listing_text.strip().split("\n")

        results = []
        position = 0
        for line in lines:
            text = line.strip().lstrip("•-*").strip()
            if not text:
                continue
            position += 1
            keyword = ListingAnalyzer._extract_keyword(text)
            results.append({"text": text, "keyword": keyword, "position": position})
        return results

    @staticmethod
    def _extract_keyword(text: str) -> str:
        for sep in [":", "：", ",", "，", " - ", "—"]:
            if sep in text:
                kw = text.split(sep, 1)[0].strip()
                if kw:
                    return kw
        words = text.split()
        return " ".join(words[:3])

    def analyze(self, competitor_listing_id: int) -> dict:
        session = get_session()
        try:
            listing = session.get(CompetitorListing, competitor_listing_id)
            if not listing:
                return {"error": "listing_not_found", "id": competitor_listing_id}

            bullets = []
            if listing.bullet_points:
                bullets = self.parse_bullets(listing.bullet_points)
            title_bullets = []
            if listing.title:
                title_bullets = self.parse_bullets(listing.title)

            return {
                "id": listing.id,
                "asin": listing.asin,
                "title": listing.title,
                "bullets": bullets,
                "title_analysis": title_bullets,
                "bullet_count": len(bullets),
            }
        finally:
            session.close()

    def update_brand_from_listing(
        self, brand_profile_id: int, listing_analysis: dict
    ) -> bool:
        if not hasattr(BrandProfile, "messaging_pillars"):
            return False

        session = get_session()
        try:
            bp = session.get(BrandProfile, brand_profile_id)
            if not bp:
                return False

            keywords = [
                b["keyword"]
                for b in listing_analysis.get("bullets", [])
                if b.get("keyword")
            ]
            if not keywords:
                return False

            bp.messaging_pillars = json.dumps(keywords, ensure_ascii=False)
            session.commit()
            return True
        finally:
            session.close()
