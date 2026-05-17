from __future__ import annotations

from openai import OpenAI
from sqlalchemy.orm import Session

from pipeline.models.base import get_session
from pipeline.models.feedback_action import FeedbackAction


class RevisionLimitExceeded(Exception):
    """同一项目的修订次数已达上限（max=3）"""


class RevisionLookup:
    MAX_REVISIONS = 3

    def _get_client(self):
        return OpenAI()

    def submit_feedback(
        self, project_id: int, feedback_text: str, prompt_asset_id: int = None
    ) -> FeedbackAction:
        session = get_session()
        try:
            # 检查已有修订次数
            existing_count = (
                session.query(FeedbackAction).filter_by(project_id=project_id).count()
            )
            if existing_count >= self.MAX_REVISIONS:
                raise RevisionLimitExceeded(
                    f"项目 {project_id} 已达到最大修订次数 {self.MAX_REVISIONS}"
                )

            # 调用 LLM 生成修订建议
            client = self._get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful revision assistant. Analyze the feedback and suggest improvements.",
                    },
                    {"role": "user", "content": feedback_text},
                ],
            )
            llm_response = response.choices[0].message.content or ""

            action = FeedbackAction(
                project_id=project_id,
                prompt_asset_id=prompt_asset_id,
                revision_count=existing_count + 1,
                feedback_text=feedback_text,
                llm_response=llm_response,
                status="pending",
            )
            session.add(action)
            session.commit()
            session.refresh(action)
            return action
        finally:
            session.close()

    def get_revisions(self, project_id: int) -> list:
        session = get_session()
        try:
            return session.query(FeedbackAction).filter_by(project_id=project_id).all()
        finally:
            session.close()


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
