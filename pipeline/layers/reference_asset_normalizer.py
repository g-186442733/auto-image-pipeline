from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

REFERENCE_ASSET_KEYS = (
    "white_bg",
    "multiangle",
    "packaging",
    "inbox_flatlay",
    "detail_closeup",
    "scale_ref",
    "usage_context",
    "color_variant",
    "front_view",
    "side_view",
    "macro_view",
    "front_orthographic",
    "front_diagram_canvas",
    "macro_crop",
)

_LEGACY_FIELD_MAP: dict[str, tuple[str, bool]] = {
    "white_bg": ("white_bg_image_path", False),
    "multiangle": ("multiangle_image_paths", True),
    "packaging": ("packaging_image_path", False),
    "inbox_flatlay": ("inbox_flatlay_image_path", False),
    "detail_closeup": ("detail_closeup_image_paths", True),
    "scale_ref": ("scale_ref_image_path", False),
    "usage_context": ("usage_context_image_paths", True),
    "color_variant": ("color_variant_image_paths", True),
    "front_view": ("front_view_image_paths", True),
    "side_view": ("side_view_image_paths", True),
    "macro_view": ("macro_view_image_paths", True),
    "front_orthographic": ("front_orthographic_image_paths", True),
    "front_diagram_canvas": ("front_diagram_canvas_image_paths", True),
    "macro_crop": ("macro_crop_image_paths", True),
}


def _split_paths(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def normalize_reference_assets(
    customer_brief: dict[str, Any] | None,
) -> dict[str, list[str]]:
    brief = customer_brief or {}
    normalized: dict[str, list[str]] = {key: [] for key in REFERENCE_ASSET_KEYS}

    existing = brief.get("reference_assets")
    if isinstance(existing, dict):
        for key in REFERENCE_ASSET_KEYS:
            normalized[key] = _dedupe(_split_paths(existing.get(key)))

    for key, (legacy_key, _multi) in _LEGACY_FIELD_MAP.items():
        legacy_paths = _split_paths(brief.get(legacy_key))
        if legacy_paths:
            normalized[key] = _dedupe(normalized[key] + legacy_paths)

    if not normalized["front_view"]:
        normalized["front_view"] = _dedupe(normalized["white_bg"][:1])
    if not normalized["side_view"]:
        normalized["side_view"] = _dedupe(normalized["usage_context"][:1])
    if not normalized["macro_view"]:
        normalized["macro_view"] = _dedupe(normalized["detail_closeup"][:1])
    if not normalized["front_orthographic"]:
        normalized["front_orthographic"] = _dedupe(normalized["front_view"][:1])
    if not normalized["front_diagram_canvas"]:
        normalized["front_diagram_canvas"] = _dedupe(
            normalized["front_orthographic"][:1]
        )
    if not normalized["macro_crop"]:
        normalized["macro_crop"] = _dedupe(normalized["macro_view"][:1])

    return normalized


def flatten_reference_assets(reference_assets: dict[str, list[str]]) -> list[str]:
    paths: list[str] = []
    for key in REFERENCE_ASSET_KEYS:
        paths.extend(reference_assets.get(key, []))
    return _dedupe(paths)


def existing_paths(paths: list[str], *, limit: int | None = None) -> list[str]:
    out = [p for p in paths if p and Path(p).is_file()]
    return out[:limit] if limit is not None else out


def legacy_fields_from_assets(reference_assets: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, (legacy_key, multi) in _LEGACY_FIELD_MAP.items():
        paths = reference_assets.get(key, [])
        out[legacy_key] = ",".join(paths) if multi else (paths[0] if paths else "")
    return out
