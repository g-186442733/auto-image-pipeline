import json
import logging
import os
from typing import List

from pipeline.models.image_brief import ImageBrief
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.qa_entry import QAEntry

log = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.0-flash"

_DEFAULT_BRIEF = json.dumps(
    {
        "slots": [
            {
                "slot_index": 0,
                "concept": "Main product hero image",
                "copy_overlay": "",
                "visual_style": "standard",
            }
        ]
    }
)

_BRIEF_PROMPT = (
    "You are an Amazon listing image strategist. Given the competitor listing data, "
    "review clusters, and Q&A entries below, generate an image brief with slots for "
    "the product listing images.\n\n"
    "Competitor Listing:\n"
    "Title: {title}\n"
    "Bullet Points: {bullets}\n"
    "Selling Points: {selling_points}\n\n"
    "Review Clusters:\n{clusters_text}\n\n"
    "Customer Q&A:\n{qa_text}\n\n"
    "Return a JSON object with a 'slots' array. Each slot has: slot_index (int), "
    "concept (image concept description), copy_overlay (text overlay suggestion), "
    "visual_style (lifestyle/detail/infographic/comparison).\n\n"
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


def generate_brief(
    project_id: int,
    competitor_listing: CompetitorListing,
    review_clusters: List[ReviewCluster],
    qa_entries: List[QAEntry],
    session=None,
) -> list[ImageBrief]:
    clusters_text = "\n".join(
        f"- {c.cluster_label} ({c.sentiment}, {c.count} reviews)"
        for c in review_clusters
    )
    qa_text = "\n".join(f"- Q: {q.question} A: {q.answer}" for q in qa_entries)

    knowledge_text = ""
    if session is not None:
        try:
            from pipeline.layers.knowledge_base import search_entries

            kb_entries = search_entries(session, "", category="prompt_pattern", limit=5)
            if kb_entries:
                knowledge_text = "\n\nKnowledge Base Insights:\n" + "\n".join(
                    f"- {e.title}: {e.content}" for e in kb_entries
                )
        except Exception:
            pass

    prompt = (
        _BRIEF_PROMPT.format(
            title=competitor_listing.title or "",
            bullets=competitor_listing.bullet_points or "",
            selling_points=competitor_listing.selling_points_map or "",
            clusters_text=clusters_text,
            qa_text=qa_text,
        )
        + knowledge_text
    )

    brief_json = _DEFAULT_BRIEF
    try:
        raw = _call_gemini(prompt)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "slots" in parsed:
            brief_json = raw
    except Exception:
        pass

    parsed_slots: list = []
    try:
        data = json.loads(brief_json)
        parsed_slots = data.get("slots", [])
    except Exception:
        pass

    if not parsed_slots:
        log.warning("generate_brief: 0 slots returned for project %s", project_id)
        return []

    briefs: list[ImageBrief] = []
    for i, slot_data in enumerate(parsed_slots):
        b = ImageBrief(
            project_id=project_id,
            slot_index=i,
            brief_json=json.dumps(slot_data),
            source_analysis_ids=json.dumps([]),
        )
        briefs.append(b)

    if session is not None:
        for b in briefs:
            session.add(b)
        session.commit()

    return briefs
