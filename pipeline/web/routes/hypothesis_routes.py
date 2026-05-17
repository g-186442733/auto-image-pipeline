from flask import Blueprint, request, jsonify
from pipeline.models.base import get_session
from pipeline.models.hypothesis import Hypothesis

hypothesis_bp = Blueprint("hypothesis", __name__)


@hypothesis_bp.route("/api/hypotheses", methods=["GET"])
def list_hypotheses():
    db = get_session()
    try:
        rows = db.query(Hypothesis).order_by(Hypothesis.created_at.desc()).all()
        return jsonify(
            [
                {
                    "id": h.id,
                    "category": h.category,
                    "hypothesis_text": h.hypothesis_text,
                    "confidence": h.confidence,
                    "status": h.status,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                    "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                }
                for h in rows
            ]
        )
    finally:
        db.close()


@hypothesis_bp.route("/api/hypotheses", methods=["POST"])
def create_hypothesis():
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    hypothesis_text = (data.get("hypothesis_text") or "").strip()
    if not category or not hypothesis_text:
        return jsonify({"error": "category and hypothesis_text are required"}), 400
    confidence = data.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5

    db = get_session()
    try:
        h = Hypothesis(
            category=category,
            hypothesis_text=hypothesis_text,
            confidence=confidence,
            tenant_id=data.get("tenant_id", 1),
        )
        db.add(h)
        db.commit()
        db.refresh(h)
        return jsonify(
            {
                "id": h.id,
                "category": h.category,
                "hypothesis_text": h.hypothesis_text,
                "confidence": h.confidence,
                "status": h.status,
            }
        ), 201
    finally:
        db.close()


@hypothesis_bp.route("/api/hypotheses/<int:hyp_id>", methods=["PUT"])
def update_hypothesis(hyp_id):
    db = get_session()
    try:
        h = db.query(Hypothesis).filter_by(id=hyp_id).first()
        if h is None:
            return jsonify({"error": "not found"}), 404
        data = request.get_json(silent=True) or {}
        if "hypothesis_text" in data:
            h.hypothesis_text = data["hypothesis_text"]
        if "confidence" in data:
            try:
                h.confidence = float(data["confidence"])
            except (TypeError, ValueError):
                pass
        if "status" in data:
            h.status = data["status"]
        db.commit()
        return jsonify(
            {
                "id": h.id,
                "category": h.category,
                "hypothesis_text": h.hypothesis_text,
                "confidence": h.confidence,
                "status": h.status,
            }
        )
    finally:
        db.close()


@hypothesis_bp.route("/api/hypotheses/<int:hyp_id>", methods=["DELETE"])
def delete_hypothesis(hyp_id):
    db = get_session()
    try:
        h = db.query(Hypothesis).filter_by(id=hyp_id).first()
        if h is None:
            return jsonify({"error": "not found"}), 404
        db.delete(h)
        db.commit()
        return jsonify({"deleted": hyp_id})
    finally:
        db.close()
