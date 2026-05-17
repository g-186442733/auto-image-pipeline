from __future__ import annotations

from sqlalchemy.orm import Session

from pipeline.models.client_feedback import ClientFeedback, VALID_FEEDBACK_TYPES

_STATUS_MAP = {
    "approve": "done",
    "revise": "needs_revision",
    "reject": "rejected",
}


def submit_feedback(
    session: Session,
    project_id: int,
    slot_name: str,
    feedback_type: str,
    text: str,
) -> ClientFeedback:
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise ValueError(
            f"Invalid feedback_type '{feedback_type}'. Must be one of {VALID_FEEDBACK_TYPES}"
        )
    fb = ClientFeedback(
        project_id=project_id,
        slot_name=slot_name,
        feedback_type=feedback_type,
        feedback_text=text,
    )
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return fb


def get_feedback_summary(session: Session, project_id: int) -> dict:
    feedbacks = (
        session.query(ClientFeedback)
        .filter_by(project_id=project_id)
        .order_by(ClientFeedback.created_at.asc())
        .all()
    )
    summary: dict[str, dict] = {}
    for fb in feedbacks:
        summary[fb.slot_name] = {
            "latest_type": fb.feedback_type,
            "latest_text": fb.feedback_text or "",
            "count": summary.get(fb.slot_name, {}).get("count", 0) + 1,
        }
    return summary


def apply_feedback(session: Session, project_id: int) -> dict[str, str]:
    summary = get_feedback_summary(session, project_id)
    result = {}
    for slot_name, info in summary.items():
        result[slot_name] = _STATUS_MAP.get(info["latest_type"], "unknown")
    if any(v == "needs_revision" for v in result.values()):
        from pipeline.layers.version_manager import create_version
        from pipeline.layers.revision_lookup import auto_apply_revision
        from pipeline.models.project import Project

        for slot_name, info in summary.items():
            if info["latest_type"] == "revise":
                auto_apply_revision(
                    session, project_id, slot_name, info.get("latest_text", "")
                )
        _proj = session.get(Project, project_id)
        _tenant_id = getattr(_proj, "tenant_id", None) if _proj else None
        create_version(
            session,
            project_id,
            "revision",
            "revision after feedback",
            tenant_id=_tenant_id,
        )
    return result
