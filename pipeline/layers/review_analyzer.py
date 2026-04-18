import json
import os
import re
from typing import List

from pipeline.models.review_cluster import ReviewCluster


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that Gemini sometimes adds."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)```\s*$", text, re.DOTALL)
    return m.group(1).strip() if m else text


_GEMINI_MODEL = "gemini-2.0-flash"

_REVIEW_CLUSTER_PROMPT = (
    "You are an Amazon review analyst. Given the following customer reviews for "
    "ASIN {asin}, cluster them by theme/topic. Return a JSON array where each element "
    "has: cluster_label (short label), sentiment (positive/negative/mixed), "
    "count (number of reviews in cluster), representative_reviews (list of 1-3 "
    "verbatim review excerpts).\n\n"
    "Reviews:\n{reviews_text}\n\n"
    "Return ONLY valid JSON array, no markdown fences."
)


def _call_gemini(prompt: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return "[]"
    try:
        import google.generativeai as genai
    except ImportError:
        return "[]"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(_GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text


def analyze_reviews(asin: str, reviews: List[dict]) -> List[ReviewCluster]:
    if not reviews:
        return []

    reviews_text = "\n".join(
        f"- [{r.get('rating', '?')}/5] {r.get('text', '')}" for r in reviews
    )
    prompt = _REVIEW_CLUSTER_PROMPT.format(asin=asin, reviews_text=reviews_text)
    raw = _call_gemini(prompt)
    raw = _strip_markdown_fences(raw)

    try:
        clusters = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(clusters, list):
        return []

    result = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        result.append(
            ReviewCluster(
                asin=asin,
                cluster_label=c.get("cluster_label", "unknown"),
                sentiment=c.get("sentiment", "mixed"),
                count=c.get("count", 0),
                representative_reviews=json.dumps(c.get("representative_reviews", [])),
            )
        )
    return result
