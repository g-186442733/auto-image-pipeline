from flask import Blueprint, jsonify
from pipeline.models.base import get_session
from pipeline.models.decision_log import DecisionLog

decision_bp = Blueprint("decision", __name__)


@decision_bp.route("/api/projects/<int:project_id>/decisions", methods=["GET"])
def list_decisions(project_id):
    db = get_session()
    try:
        rows = (
            db.query(DecisionLog)
            .filter_by(project_id=project_id)
            .order_by(DecisionLog.created_at.desc())
            .all()
        )
        return jsonify(
            {
                "decisions": [
                    {
                        "id": r.id,
                        "decision_type": r.decision_type,
                        "decision_text": r.decision_text,
                        "rationale": r.rationale,
                        "made_by": r.made_by,
                        "created_at": r.created_at.isoformat()
                        if r.created_at
                        else None,
                    }
                    for r in rows
                ]
            }
        )
    finally:
        db.close()
