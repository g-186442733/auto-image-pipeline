from __future__ import annotations

import json
from typing import Any

from pipeline.layers.custom_requirement_parser import parse_custom_requirements
from pipeline.layers.reference_asset_normalizer import normalize_reference_assets


def load_customer_brief(project) -> dict[str, Any]:
    try:
        return json.loads(project.customer_brief or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def enrich_customer_brief(brief: dict[str, Any]) -> dict[str, Any]:
    out = dict(brief)
    out["reference_assets"] = normalize_reference_assets(out)
    out["custom_requirements"] = parse_custom_requirements(out)
    return out


def save_enriched_customer_brief(project, session) -> dict[str, Any]:
    brief = enrich_customer_brief(load_customer_brief(project))
    project.customer_brief = json.dumps(brief, ensure_ascii=False)
    session.add(project)
    session.commit()
    return brief
