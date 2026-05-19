from __future__ import annotations

import json
from typing import Any

PRODUCT_FACT_INTENTS = {
    "INT_HERO",
    "INT_DETAIL",
    "INT_INFOGRAPHIC",
    "INT_COMPARISON",
    "INT_PACKAGING",
}

PRODUCT_FACT_APLUS_MODULES = {
    "HERO",
    "BENEFIT",
    "DETAIL",
    "COMPARISON",
    "CROSS_SELL",
}

FINAL = "final"
CONCEPT_ONLY = "concept_only"
FAILED = "failed"


def is_product_fact_intent(intent_tag: str | None) -> bool:
    return (intent_tag or "").upper() in PRODUCT_FACT_INTENTS


def is_product_fact_aplus_module(module_type: str | None) -> bool:
    return (module_type or "").upper() in PRODUCT_FACT_APLUS_MODULES


def has_generated_composition_reference(reference_paths: list[str] | None) -> bool:
    paths = reference_paths or []
    return any("generated_" in p or "composition_reference" in p for p in paths)


def reference_basis(reference_paths: list[str] | None) -> list[str]:
    basis: list[str] = []
    for path in reference_paths or []:
        if "generated_" in path or "composition_reference" in path:
            label = "generated_composition_reference"
        elif "style" in path:
            label = "real_style_reference"
        else:
            label = "real_product_reference"
        if label not in basis:
            basis.append(label)
    return basis


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def listing_delivery_metadata(
    *,
    passed: bool,
    score: float,
    qa_details: dict[str, Any] | None,
    intent_tag: str | None,
    reference_paths: list[str] | None,
    model_name: str | None = None,
    product_fact_reference_paths: list[str] | None = None,
    layout_reference_paths: list[str] | None = None,
    reference_identity_mode: str = "strict",
    target_angle: str | None = None,
    actual_angle: str | None = None,
    angle_matches_target: bool | None = None,
) -> dict[str, Any]:
    details = qa_details or {}
    product_fact = is_product_fact_intent(intent_tag)
    consistency_score = float(details.get("D", 0) or 0)
    fact_paths = product_fact_reference_paths if product_fact_reference_paths is not None else reference_paths
    layout_paths = layout_reference_paths or []
    uses_generated_ref = has_generated_composition_reference(fact_paths)
    normalized_mode = (reference_identity_mode or "strict").strip().lower().replace("-", "_")
    if normalized_mode in {"reference_inspired", "generic", "shape_only"}:
        normalized_mode = "silhouette"
    if normalized_mode != "silhouette":
        normalized_mode = "strict"
    consistency_threshold = 10 if normalized_mode == "silhouette" else 18
    reasons: list[str] = []

    if not passed or score < 60:
        status = FAILED
        consistency_status = "fail"
        reasons.append("QA did not pass the minimum delivery threshold")
    elif product_fact and consistency_score < consistency_threshold:
        status = CONCEPT_ONLY
        consistency_status = "warning"
        reasons.append("Product consistency score is below the product-fact threshold")
    elif product_fact and uses_generated_ref:
        status = CONCEPT_ONLY
        consistency_status = "warning"
        reasons.append("Product-fact slot used generated composition references; human/product review required")
    elif angle_matches_target is False:
        status = CONCEPT_ONLY
        consistency_status = "warning"
        reasons.append("Angle target mismatch; local regeneration or human review required")
    else:
        status = FINAL
        consistency_status = "pass"
        reasons.append("QA and product consistency checks passed")

    if model_name and "fallback" in model_name.lower():
        status = CONCEPT_ONLY if status == FINAL else status
        consistency_status = "warning" if consistency_status == "pass" else consistency_status
        reasons.append("Fallback model output requires manual confirmation")

    return {
        "delivery_status": status,
        "consistency_status": consistency_status,
        "delivery_reason": "; ".join(reasons),
        "product_fact_required": product_fact,
        "reference_basis": reference_basis(reference_paths),
        "reference_paths": reference_paths or [],
        "product_fact_reference_paths": fact_paths or [],
        "layout_reference_paths": layout_paths,
        "model_used": model_name or "unknown",
        "consistency_score": consistency_score,
        "reference_identity_mode": normalized_mode,
        "consistency_threshold": consistency_threshold if product_fact else None,
        "target_angle": target_angle or None,
        "actual_angle": actual_angle or None,
        "angle_matches_target": angle_matches_target,
    }


def aplus_delivery_metadata(
    *,
    passed: bool,
    score: float,
    breakdown: dict[str, Any] | None,
    module_type: str | None,
    reference_paths: list[str] | None,
) -> dict[str, Any]:
    data = breakdown or {}
    product_fact = is_product_fact_aplus_module(module_type)
    consistency_score = float(data.get("L5_consistency", 0) or 0)
    intent_score_raw = data.get("L4_intent")
    intent_score = float(intent_score_raw) if intent_score_raw is not None else None
    uses_generated_ref = has_generated_composition_reference(reference_paths)
    basis = reference_basis(reference_paths)
    has_real_product_reference = "real_product_reference" in basis
    reasons: list[str] = []

    if not passed or score < 60:
        status = FAILED
        consistency_status = "fail"
        reasons.append("A+ QA did not pass the minimum delivery threshold")
    elif intent_score is not None and intent_score < 15:
        status = FAILED
        consistency_status = "fail"
        reasons.append("A+ module intent score is below the final delivery threshold")
    elif product_fact and not has_real_product_reference:
        status = FAILED
        consistency_status = "fail"
        reasons.append("A+ product-fact module has no real product reference")
    elif product_fact and consistency_score < 8:
        status = CONCEPT_ONLY
        consistency_status = "warning"
        reasons.append("A+ product consistency score is below the product-fact threshold")
    elif product_fact and uses_generated_ref:
        status = CONCEPT_ONLY
        consistency_status = "warning"
        reasons.append("A+ product-fact module used generated composition references")
    else:
        status = FINAL
        consistency_status = "pass"
        reasons.append("A+ QA and consistency checks passed")

    return {
        "delivery_status": status,
        "consistency_status": consistency_status,
        "delivery_reason": "; ".join(reasons),
        "product_fact_required": product_fact,
        "reference_basis": basis,
        "reference_paths": reference_paths or [],
        "consistency_score": consistency_score,
    }


def merge_visual_tags(existing: str | None, metadata: dict[str, Any]) -> str:
    base = _json_loads(existing)
    base.update(metadata)
    return json.dumps(base, ensure_ascii=False)
