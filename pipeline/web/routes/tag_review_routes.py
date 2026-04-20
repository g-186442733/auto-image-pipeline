from flask import Blueprint, request, jsonify, render_template
from pipeline.models.base import get_session
from pipeline.models.tag_assignment import TagAssignment

tag_review_bp = Blueprint("tag_review", __name__)


@tag_review_bp.route("/tag-review", methods=["GET"])
def tag_review_list():
    db = get_session()
    try:
        assignments = (
            db.query(TagAssignment)
            .filter(TagAssignment.status == "pending")
            .order_by(TagAssignment.created_at.desc())
            .all()
        )
        return render_template("tag_review.html", assignments=assignments)
    finally:
        db.close()


@tag_review_bp.route("/tag-review/<int:assignment_id>/approve", methods=["POST"])
def tag_review_approve(assignment_id):
    db = get_session()
    try:
        ta = db.query(TagAssignment).filter_by(id=assignment_id).first()
        if ta is None:
            return jsonify({"error": "not found"}), 404
        ta.status = "approved"
        db.commit()
        return jsonify({"id": ta.id, "status": ta.status})
    finally:
        db.close()


@tag_review_bp.route("/tag-review/<int:assignment_id>/reject", methods=["POST"])
def tag_review_reject(assignment_id):
    db = get_session()
    try:
        ta = db.query(TagAssignment).filter_by(id=assignment_id).first()
        if ta is None:
            return jsonify({"error": "not found"}), 404
        ta.status = "rejected"
        db.commit()
        return jsonify({"id": ta.id, "status": ta.status})
    finally:
        db.close()


@tag_review_bp.route("/tag-review/<int:assignment_id>/edit", methods=["POST"])
def tag_review_edit(assignment_id):
    db = get_session()
    try:
        ta = db.query(TagAssignment).filter_by(id=assignment_id).first()
        if ta is None:
            return jsonify({"error": "not found"}), 404
        data = request.get_json(silent=True) or {}
        if "tag_code" in data:
            ta.tag_code = data["tag_code"]
        if "tag_layer" in data:
            ta.tag_layer = data["tag_layer"]
        db.commit()
        return jsonify(
            {
                "id": ta.id,
                "entity_type": ta.entity_type,
                "entity_id": ta.entity_id,
                "tag_code": ta.tag_code,
                "tag_layer": ta.tag_layer,
                "status": ta.status,
            }
        )
    finally:
        db.close()
