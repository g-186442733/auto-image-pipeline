from __future__ import annotations

import re
from typing import Any


_ALWAYS_RELEVANT_TERMS = (
    "black",
    "main color",
    "primary color",
    "主款",
    "主色",
    "黑色",
)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


_REQUIREMENT_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("高端商务科技风", "premium business technology style"),
    ("克制", "restrained"),
    ("干净", "clean"),
    ("可信赖", "trustworthy"),
    (
        "严格保持真实上传白底图和角度图中的耳机外观、比例、颜色、耳罩形状和 BOSE 标识位置",
        "strictly preserve the headphone appearance, proportions, color, earcup shape, and BOSE logo placement from the uploaded white-background and angle references",
    ),
    (
        "Hero 主图不得展示保护盒、线材、配件全家福",
        "Hero image must not show the carrying case, cables, or a full accessory bundle",
    ),
    (
        "Packaging/In-box 图位才展示保护盒、USB-C 线、音频线、安全说明",
        "Only the Packaging/In-box slot may show the carrying case, USB-C cable, audio cable, and safety guide",
    ),
    (
        "Detail 图位聚焦接口、按钮、耳罩材质",
        "Detail slot should focus on ports, buttons, and ear cushion material",
    ),
    (
        "生成构图参考图只能用于 layout，不得当作真实产品照片",
        "Generated composition references may be used for layout only and must not be treated as real product photos",
    ),
    ("黑色主款", "black main product variant"),
    ("柔软耳罩材质", "soft ear cushion material"),
    ("USB-C接口", "USB-C port"),
    ("USB-C 接口", "USB-C port"),
    ("保护盒和全部配件", "carrying case and complete accessory bundle"),
    ("小时续航信息", "battery life information in hours"),
    ("Hero主图出现保护盒或线材", "carrying case or cables appearing in the Hero image"),
    ("不存在的颜色", "nonexistent color variants"),
    ("虚构配件", "invented accessories"),
    ("儿童场景", "children scenes"),
    ("宠物场景", "pet scenes"),
    ("竞品品牌名", "competitor brand names"),
    ("电竞灯效", "gaming RGB lighting effects"),
    ("保护盒", "carrying case"),
    ("线材", "cables"),
    ("配件", "accessories"),
    ("耳罩", "ear cushions"),
    ("接口", "ports"),
    ("按钮", "buttons"),
    ("主图", "Hero image"),
    ("图位", "image slot"),
)


def _normalize_requirement_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text
    for source, target in _REQUIREMENT_TRANSLATIONS:
        normalized = normalized.replace(source, target)
    normalized = (
        normalized.replace("；", "; ")
        .replace("。", ". ")
        .replace("，", ", ")
        .replace("、", ", ")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _CJK_RE.sub("", normalized)
    normalized = re.sub(r"\s+([,.;:])", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,;.")
    return normalized


_INTENT_RELEVANT_TERMS: dict[str, tuple[str, ...]] = {
    "INT_HERO": _ALWAYS_RELEVANT_TERMS,
    "INT_LIFESTYLE": _ALWAYS_RELEVANT_TERMS
    + (
        "lifestyle",
        "usage",
        "scene",
        "wear",
        "comfort",
        "cushion",
        "earcup",
        "材质",
        "耳罩",
        "佩戴",
        "场景",
        "使用",
        "舒适",
    ),
    "INT_DETAIL": _ALWAYS_RELEVANT_TERMS
    + (
        "detail",
        "texture",
        "material",
        "port",
        "button",
        "usb",
        "type-c",
        "接口",
        "材质",
        "耳罩",
        "按键",
        "细节",
    ),
    "INT_INFOGRAPHIC": _ALWAYS_RELEVANT_TERMS
    + (
        "battery",
        "playtime",
        "hour",
        "hours",
        "feature",
        "spec",
        "usb",
        "type-c",
        "接口",
        "续航",
        "小时",
        "卖点",
        "功能",
        "参数",
    ),
    "INT_COMPARISON": _ALWAYS_RELEVANT_TERMS
    + (
        "compare",
        "comparison",
        "versus",
        "variant",
        "battery",
        "playtime",
        "hour",
        "hours",
        "对比",
        "比较",
        "款式",
        "续航",
        "小时",
    ),
    "INT_PACKAGING": _ALWAYS_RELEVANT_TERMS
    + (
        "package",
        "packaging",
        "box",
        "case",
        "accessory",
        "accessories",
        "cable",
        "manual",
        "usb",
        "type-c",
        "包装",
        "盒",
        "保护盒",
        "配件",
        "线材",
        "说明书",
        "接口",
    ),
}

_RAW_SENTENCE_INTENT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("INT_HERO", ("hero", "main image", "主图", "hero image")),
    ("INT_DETAIL", ("detail", "detail slot", "细节", "detail 图位")),
    ("INT_INFOGRAPHIC", ("infographic", "信息图", "参数图", "卖点图")),
    (
        "INT_PACKAGING",
        ("packaging", "in-box", "package", "包装", "图位才展示", "配件图"),
    ),
)


def _raw_sentence_relevance(item: Any, intent_tag: str | None) -> bool:
    if not intent_tag:
        return True
    text = str(item or "").strip().lower()
    if not text:
        return False
    matched_intents = [
        marker_intent
        for marker_intent, markers in _RAW_SENTENCE_INTENT_MARKERS
        if any(marker.lower() in text for marker in markers)
    ]
    if matched_intents:
        return intent_tag in matched_intents
    return _must_show_relevance(item, intent_tag)


def _must_show_relevance(item: Any, intent_tag: str | None) -> bool:
    if not intent_tag:
        return True
    text = str(item).strip().lower()
    if not text:
        return False
    terms = _INTENT_RELEVANT_TERMS.get(intent_tag, _ALWAYS_RELEVANT_TERMS)
    return any(term.lower() in text for term in terms)


def _split_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).replace("；", "\n").replace(";", "\n")
    text = text.replace("，", "\n") if "\n" not in text else text
    return [
        line.strip().lstrip("-•0123456789.、 ").strip()
        for line in text.splitlines()
        if line.strip()
    ]


def _split_requirement_sentences(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[。；;\n]+", text)
    return [part.strip(" ，,.") for part in parts if part.strip(" ，,.")]


def _as_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "允许", "是"}


def parse_custom_requirements(customer_brief: dict[str, Any] | None) -> dict[str, Any]:
    brief = customer_brief or {}
    existing = brief.get("custom_requirements")
    req: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}

    raw_text = str(
        brief.get("custom_requirements_text") or req.get("raw_text") or ""
    ).strip()
    style = str(
        brief.get("style_direction") or req.get("project_direction") or ""
    ).strip()

    must_show = _split_lines(req.get("must_show")) + _split_lines(
        brief.get("must_show")
    )
    must_not_show = _split_lines(req.get("must_not_show")) + _split_lines(
        brief.get("must_not_show")
    )

    listing_pref = dict(req.get("listing_preferences") or {})
    if brief.get("listing_image_preferences"):
        listing_pref["raw"] = str(brief.get("listing_image_preferences", "")).strip()
        listing_pref["preferred_image_types"] = _split_lines(
            brief.get("listing_image_preferences")
        )

    aplus_pref = dict(req.get("aplus_preferences") or {})
    if brief.get("aplus_module_preferences"):
        aplus_pref["raw"] = str(brief.get("aplus_module_preferences", "")).strip()
        aplus_pref["preferred_modules"] = _split_lines(
            brief.get("aplus_module_preferences")
        )

    policy = dict(req.get("generation_policy") or {})
    policy.setdefault("strict_product_identity", True)
    policy.setdefault(
        "allow_invent_accessories",
        _as_bool(brief.get("allow_invent_accessories"), False),
    )
    policy.setdefault(
        "allow_invent_color_variants",
        _as_bool(brief.get("allow_invent_color_variants"), False),
    )
    policy.setdefault(
        "allow_ai_background_generation",
        _as_bool(brief.get("allow_ai_background_generation"), True),
    )
    policy.setdefault(
        "prefer_real_product_composite",
        _as_bool(brief.get("prefer_real_product_composite"), True),
    )

    return {
        "raw_text": raw_text,
        "project_direction": style,
        "must_show": list(dict.fromkeys(must_show)),
        "must_not_show": list(dict.fromkeys(must_not_show)),
        "listing_preferences": listing_pref,
        "aplus_preferences": aplus_pref,
        "generation_policy": policy,
    }


def build_user_requirement_lock(
    custom_requirements: dict[str, Any] | None, intent_tag: str | None = None
) -> str:
    req = custom_requirements or {}
    parts: list[str] = []
    project_direction = _normalize_requirement_text(req.get("project_direction"))
    if project_direction:
        parts.append(f"Project direction: {project_direction}.")
    raw_items = _split_requirement_sentences(req.get("raw_text"))
    if raw_items:
        relevant_raw = [x for x in raw_items if _raw_sentence_relevance(x, intent_tag)]
        normalized_raw = [_normalize_requirement_text(x) for x in relevant_raw]
        normalized_raw = [x for x in normalized_raw if x]
        if normalized_raw:
            parts.append(
                "User special instructions for this intent slot: "
                + "; ".join(normalized_raw)
                + "."
            )
    must_show = req.get("must_show") or []
    if must_show:
        relevant_must_show = [
            x for x in must_show if _must_show_relevance(x, intent_tag)
        ]
        deferred_must_show = [x for x in must_show if x not in relevant_must_show]
        if relevant_must_show:
            parts.append(
                "Must show in this intent slot: "
                + "; ".join(
                    _normalize_requirement_text(x)
                    for x in relevant_must_show
                    if _normalize_requirement_text(x)
                )
                + "."
            )
        if deferred_must_show:
            parts.append(
                "Deferred to other intent slots: some global must-show requirements "
                "are intentionally excluded from this image because they do not match this slot intent."
            )
    must_not_show = req.get("must_not_show") or []
    if must_not_show:
        normalized_must_not = [_normalize_requirement_text(x) for x in must_not_show]
        normalized_must_not = [x for x in normalized_must_not if x]
        if normalized_must_not:
            parts.append("Must not show: " + "; ".join(normalized_must_not) + ".")
    policy = req.get("generation_policy") or {}
    policy_rules: list[str] = []
    if policy.get("strict_product_identity", True):
        policy_rules.append("strictly preserve product identity")
    if not policy.get("allow_invent_accessories", False):
        policy_rules.append("do not invent accessories")
    if not policy.get("allow_invent_color_variants", False):
        policy_rules.append("do not invent color variants")
    if policy.get("prefer_real_product_composite", True):
        policy_rules.append("prefer real product appearance over creative redrawing")
    if policy_rules:
        parts.append("Generation policy: " + "; ".join(policy_rules) + ".")
    if not parts:
        return ""
    return "USER REQUIREMENTS LOCK:\n" + "\n".join(parts)


def requirements_for_intent(
    custom_requirements: dict[str, Any] | None,
    intent_tag: str | None,
) -> dict[str, Any]:
    req = dict(custom_requirements or {})
    raw_items = _split_requirement_sentences(req.get("raw_text"))
    relevant_raw = [x for x in raw_items if _raw_sentence_relevance(x, intent_tag)]
    req["raw_text"] = "; ".join(relevant_raw)

    must_show = req.get("must_show") or []
    req["must_show"] = [x for x in must_show if _must_show_relevance(x, intent_tag)]

    req["intent_scope"] = intent_tag or ""
    return req
