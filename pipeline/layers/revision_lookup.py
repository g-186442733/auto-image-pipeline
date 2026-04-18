from __future__ import annotations

from sqlalchemy.orm import Session

REVISION_TABLE: dict[str, dict[str, str]] = {
    "背景": {
        "action": "replace_background",
        "suggestion": "更换或调整产品背景图/场景",
    },
    "颜色": {
        "action": "adjust_color",
        "suggestion": "调整图片整体配色或产品颜色呈现",
    },
    "文字": {
        "action": "edit_text",
        "suggestion": "修改图片上的文案/字体/排版",
    },
    "尺寸": {
        "action": "resize",
        "suggestion": "调整图片尺寸或产品在画面中的比例",
    },
    "角度": {
        "action": "change_angle",
        "suggestion": "更换产品拍摄/渲染角度",
    },
    "模糊": {
        "action": "sharpen",
        "suggestion": "提升图片清晰度/锐度",
    },
    "logo": {
        "action": "update_logo",
        "suggestion": "修改或重新放置品牌 Logo",
    },
    "排版": {
        "action": "adjust_layout",
        "suggestion": "调整元素布局/排版结构",
    },
}


_FALLBACK = {"action": "manual_review", "suggestion": "需人工审核反馈内容"}


def lookup_revision_action(feedback_text: str) -> dict[str, str]:
    if not feedback_text:
        return dict(_FALLBACK)

    text_lower = feedback_text.lower()
    for keyword, entry in REVISION_TABLE.items():
        if keyword in text_lower:
            return entry

    return dict(_FALLBACK)


def auto_apply_revision(
    session: Session,
    project_id: int,
    slot_name: str,
    feedback_text: str,
) -> dict:
    result = lookup_revision_action(feedback_text)

    matched_keyword: str | None = None
    if result["action"] != "manual_review" and feedback_text:
        text_lower = feedback_text.lower()
        for kw in REVISION_TABLE:
            if kw in text_lower:
                matched_keyword = kw
                break

    return {
        "slot_name": slot_name,
        "action": result["action"],
        "suggestion": result["suggestion"],
        "keyword_matched": matched_keyword,
    }
