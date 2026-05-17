import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.pipeline_run import PipelineRun
from pipeline.utils.logger import setup_logger

project_api_bp = Blueprint("project_api", __name__)
logger = setup_logger("aip.project_routes")


def _run_asin_fetch(project_id: int, asin: str, trigger_source: str):
    """后台线程：抓取 ASIN 数据并更新 pipeline_run 记录。"""
    from pipeline.layers.amazon_data import fetch_asin_detail

    session = get_session()
    try:
        run = PipelineRun(
            project_id=project_id,
            status="running",
            auto_triggered=True,
            trigger_source=trigger_source,
        )
        session.add(run)
        session.commit()
        run_id = run.id

        try:
            fetch_asin_detail(asin)
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:1000]
                session.commit()
            logger.error("ASIN fetch failed for project %d: %s", project_id, exc)
    except Exception as exc:
        logger.error(
            "Failed to create pipeline_run for project %d: %s", project_id, exc
        )
    finally:
        session.close()


@project_api_bp.route("/api/projects", methods=["POST"])
def api_create_project():
    from pipeline.layers.input_layer import create_project

    data = request.get_json(silent=True) or {}
    brief = {
        "name": data.get("name", ""),
        "asin": data.get("asin", ""),
        "category": data.get("category", ""),
        "notes": data.get("notes", ""),
    }
    if not brief["name"]:
        return jsonify({"error": "name is required"}), 400

    try:
        project = create_project(brief)
        db = get_session()
        try:
            p = db.query(Project).filter_by(id=project.id).first()
            if p:
                p.tenant_id = request.form.get("tenant_id", 1)
                db.commit()
        finally:
            db.close()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    asin = brief.get("asin", "").strip()
    if asin:
        t = threading.Thread(
            target=_run_asin_fetch,
            args=(project.id, asin, "project_create"),
            daemon=True,
        )
        t.start()

    return jsonify({"id": project.id, "name": project.name}), 201
