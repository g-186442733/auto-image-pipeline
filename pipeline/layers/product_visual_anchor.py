from __future__ import annotations

import json
from typing import Any

from pipeline.layers.reference_asset_normalizer import existing_paths, flatten_reference_assets

_ANCHOR_PROMPT = """
Analyze the uploaded product reference image for product identity locking in AI image generation.
Return concise JSON with keys:
category, primary_colors, material, shape, logo_position, must_preserve, fine_details, packaging_notes, scale_notes, variants.
Focus on facts visible in the image. Do not guess invisible features.
""".strip()


def _empty_anchor() -> dict[str, Any]:
    return {
        "identity": {},
        "details": {},
        "packaging": {},
        "scale": {},
        "variants": {},
        "summary": "",
    }


def _parse_analysis(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"summary": text.strip()}
    return data if isinstance(data, dict) else {"summary": text.strip()}


def extract_product_visual_anchor(reference_assets: dict[str, list[str]], *, max_images: int = 8) -> dict[str, Any]:
    paths = existing_paths(flatten_reference_assets(reference_assets), limit=max_images)
    if not paths:
        return _empty_anchor()

    try:
        from pipeline.adapters.gemini_vision_adapter import GeminiVisionAdapter

        adapter = GeminiVisionAdapter()
    except Exception:
        return _empty_anchor()

    analyses: list[dict[str, Any]] = []
    for path in paths:
        try:
            raw = adapter.analyze(path, _ANCHOR_PROMPT)
            text = raw.get("analysis", "") if isinstance(raw, dict) else str(raw)
            if text.strip():
                parsed = _parse_analysis(text)
                parsed["source_path"] = path
                analyses.append(parsed)
        except Exception:
            continue

    if not analyses:
        return _empty_anchor()

    identity: dict[str, Any] = {}
    details: dict[str, Any] = {"sources": analyses}
    packaging: dict[str, Any] = {}
    scale: dict[str, Any] = {}
    variants: dict[str, Any] = {}
    summary_parts: list[str] = []

    for item in analyses:
        for key in ("category", "primary_colors", "material", "shape", "logo_position", "must_preserve"):
            value = item.get(key)
            if value and key not in identity:
                identity[key] = value
        if item.get("fine_details"):
            details.setdefault("fine_details", []).append(item["fine_details"])
        if item.get("packaging_notes"):
            packaging.setdefault("notes", []).append(item["packaging_notes"])
        if item.get("scale_notes"):
            scale.setdefault("notes", []).append(item["scale_notes"])
        if item.get("variants"):
            variants.setdefault("items", []).append(item["variants"])
        if item.get("summary"):
            summary_parts.append(str(item["summary"]))

    return {
        "identity": identity,
        "details": details,
        "packaging": packaging,
        "scale": scale,
        "variants": variants,
        "summary": "; ".join(summary_parts),
    }


def ensure_product_visual_anchor(project, session, reference_assets: dict[str, list[str]]) -> dict[str, Any]:
    try:
        brief = json.loads(project.customer_brief or "{}")
    except (TypeError, json.JSONDecodeError):
        brief = {}

    existing = brief.get("product_visual_anchor")
    if isinstance(existing, dict) and existing:
        return existing

    anchor = extract_product_visual_anchor(reference_assets)
    brief["product_visual_anchor"] = anchor
    project.customer_brief = json.dumps(brief, ensure_ascii=False)
    session.add(project)
    session.commit()
    return anchor


def build_product_identity_lock(anchor: dict[str, Any] | None, intent_tag: str | None = None) -> str:
    anchor = anchor or {}
    identity = anchor.get("identity") if isinstance(anchor.get("identity"), dict) else {}
    details = anchor.get("details") if isinstance(anchor.get("details"), dict) else {}
    packaging = anchor.get("packaging") if isinstance(anchor.get("packaging"), dict) else {}
    scale = anchor.get("scale") if isinstance(anchor.get("scale"), dict) else {}
    variants = anchor.get("variants") if isinstance(anchor.get("variants"), dict) else {}

    parts = [
        "PRODUCT IDENTITY LOCK:",
        "Uploaded product references are the source of truth.",
        "Preserve exact product silhouette, color, material, logo placement, ports/buttons, proportions, packaging/accessory count where applicable.",
    ]
    for label, key in (
        ("Category", "category"),
        ("Primary colors", "primary_colors"),
        ("Material", "material"),
        ("Shape", "shape"),
        ("Logo placement", "logo_position"),
        ("Must preserve", "must_preserve"),
    ):
        value = identity.get(key)
        if value:
            parts.append(f"{label}: {value}.")
    if details.get("fine_details") and intent_tag == "INT_DETAIL":
        parts.append(f"Fine detail references: {details['fine_details']}.")
    if packaging and intent_tag == "INT_PACKAGING":
        parts.append(f"Packaging/accessory references: {packaging}.")
    if scale and intent_tag in {"INT_INFOGRAPHIC", "INT_LIFESTYLE"}:
        parts.append(f"Scale references: {scale}.")
    if variants and intent_tag == "INT_COMPARISON":
        parts.append(f"True variant references: {variants}.")
    if anchor.get("summary"):
        parts.append(f"Reference summary: {anchor['summary']}.")
    parts.append("Do not invent new parts, colors, accessories, labels, packaging claims, or structural elements.")
    return "\n".join(parts)
