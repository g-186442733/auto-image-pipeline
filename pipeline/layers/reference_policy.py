from __future__ import annotations

from typing import Any

from pipeline.layers.reference_asset_normalizer import existing_paths

INTENT_REFERENCE_POLICY: dict[str, dict[str, list[str]]] = {
    "INT_HERO": {
        "refs": ["front_view", "white_bg"],
        "qa_focus": ["silhouette", "color", "logo", "proportions"],
        "fact_refs": ["front_view", "white_bg"],
    },
    "INT_LIFESTYLE": {
        "refs": ["usage_context", "side_view"],
        "qa_focus": ["product_identity", "scale", "allowed_scene"],
        "fact_refs": ["usage_context", "side_view", "white_bg"],
    },
    "INT_DETAIL": {
        "refs": ["macro_crop"],
        "qa_focus": ["material", "ports_buttons", "craftsmanship"],
        "fact_refs": ["macro_view", "detail_closeup"],
    },
    "INT_INFOGRAPHIC": {
        "refs": [
            "front_diagram_canvas",
            "front_orthographic",
            "front_view",
            "white_bg",
        ],
        "qa_focus": ["scale", "feature_accuracy", "text_readability"],
        "fact_refs": ["macro_view", "front_view", "white_bg"],
    },
    "INT_COMPARISON": {
        "refs": ["color_variant", "white_bg", "multiangle"],
        "qa_focus": ["true_variants_only", "no_invented_colors"],
        "fact_refs": ["color_variant", "white_bg", "multiangle"],
    },
    "INT_PACKAGING": {
        "refs": ["packaging", "detail_closeup", "inbox_flatlay", "white_bg"],
        "qa_focus": ["packaging_accuracy", "accessory_count", "label_accuracy"],
        "fact_refs": ["packaging", "detail_closeup", "white_bg"],
    },
}

_DEFAULT_KEYS = ["white_bg", "multiangle"]


def reference_keys_for_intent(
    intent_tag: str | None, *, product_fact_only: bool = False
) -> list[str]:
    policy = INTENT_REFERENCE_POLICY.get(intent_tag or "", {})
    key = "fact_refs" if product_fact_only else "refs"
    return list(policy.get(key, policy.get("refs", _DEFAULT_KEYS)))


def qa_focus_for_intent(intent_tag: str | None) -> list[str]:
    return list(INTENT_REFERENCE_POLICY.get(intent_tag or "", {}).get("qa_focus", []))


def select_reference_paths(
    reference_assets: dict[str, list[str]],
    intent_tag: str | None,
    *,
    fallback: bool = True,
    limit: int | None = 8,
    product_fact_only: bool = False,
) -> list[str]:
    candidates: list[str] = []
    for key in reference_keys_for_intent(
        intent_tag, product_fact_only=product_fact_only
    ):
        candidates.extend(reference_assets.get(key, []))
    paths = existing_paths(candidates, limit=limit)
    if paths or not fallback:
        return paths
    fallback_candidates = (
        reference_assets.get("front_view", [])
        + reference_assets.get("white_bg", [])
        + reference_assets.get("multiangle", [])
    )
    return existing_paths(fallback_candidates, limit=limit)


def build_intent_reference_rule(
    intent_tag: str | None, reference_assets: dict[str, list[str]]
) -> str:
    keys = reference_keys_for_intent(intent_tag)
    available = [key for key in keys if reference_assets.get(key)]
    focus = qa_focus_for_intent(intent_tag)
    if not available and not focus:
        return ""
    parts = ["INTENT-SPECIFIC REFERENCE RULES:"]
    if available:
        parts.append(
            "Use these reference types as source of truth: "
            + ", ".join(available)
            + "."
        )
    if focus:
        parts.append("Consistency focus: " + ", ".join(focus) + ".")
    if intent_tag == "INT_PACKAGING":
        parts.append(
            "Use generated composition references only for layout guidance, never as product or accessory facts."
        )
        parts.append(
            "Do not invent packaging claims, labels, accessories, or included items not visible in real references."
        )
    elif intent_tag == "INT_COMPARISON":
        parts.append(
            "Only show color variants or styles proven by uploaded variant references."
        )
    elif intent_tag == "INT_DETAIL":
        parts.append(
            "Match the exact visible texture, seam, port, button, logo, or craftsmanship detail."
        )
    return "\n".join(parts)
