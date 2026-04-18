import os
import secrets
import threading
import traceback
from datetime import timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_file,
    session,
    jsonify,
)

from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.benchmark import AmazonBenchmark

# Global run status tracker: {project_id: {"state": "idle"|"running"|"done"|"error", "message": str}}
_run_status: dict[int, dict] = {}


def _run_pipeline_thread(project_id: int):
    """Run all pipeline steps in a background thread."""
    from pipeline.orchestrator import (
        step_analyze,
        step_plan,
        step_generate,
        step_qa,
        step_report,
    )

    try:
        _run_status[project_id] = {"state": "running", "message": "正在分析竞品..."}
        step_analyze(project_id)

        _run_status[project_id] = {"state": "running", "message": "正在生成图位规划..."}
        step_plan(project_id)

        _run_status[project_id] = {"state": "running", "message": "正在生成图片..."}
        step_generate(project_id, adapter_name="gpt_image")

        _run_status[project_id] = {"state": "running", "message": "正在质检..."}
        step_qa(project_id)

        _run_status[project_id] = {"state": "running", "message": "正在生成报告..."}
        step_report(project_id)

        _run_status[project_id] = {"state": "done", "message": "流水线完成"}
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"失败: {exc}\n{traceback.format_exc()}",
        }


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)

    @app.before_request
    def _make_session_permanent():
        session.permanent = True

    create_all()

    @app.route("/")
    def index():
        session = get_session()
        try:
            projects = session.query(Project).order_by(Project.updated_at.desc()).all()
            return render_template("index.html", projects=projects)
        finally:
            session.close()

    @app.route("/project/<int:project_id>")
    def project_detail(project_id):
        session = get_session()
        try:
            project = session.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            slots = (
                session.query(SlotPlan)
                .filter_by(project_id=project_id)
                .order_by(SlotPlan.slot_index)
                .all()
            )
            prompts = (
                session.query(PromptAsset)
                .filter_by(project_id=project_id)
                .order_by(PromptAsset.slot_index, PromptAsset.version.desc())
                .all()
            )
            benchmarks = (
                session.query(AmazonBenchmark).filter_by(project_id=project_id).all()
            )
            return render_template(
                "project_detail.html",
                project=project,
                slots=slots,
                prompts=prompts,
                benchmarks=benchmarks,
            )
        finally:
            session.close()

    @app.route("/project/new", methods=["GET"])
    def project_new():
        return render_template("project_new.html")

    @app.route("/project/new", methods=["POST"])
    def project_create():
        from pipeline.layers.input_layer import create_project

        brief = {
            "name": request.form["name"],
            "asin": request.form.get("asin", ""),
            "category": request.form.get("category", ""),
            "notes": request.form.get("notes", ""),
        }
        try:
            project = create_project(brief)
        except ValueError as exc:
            return str(exc), 400
        return redirect(url_for("project_detail", project_id=project.id))

    @app.route("/prompts")
    def prompts_list():
        session = get_session()
        try:
            prompts = (
                session.query(PromptAsset).order_by(PromptAsset.created_at.desc()).all()
            )
            return render_template("prompts.html", prompts=prompts)
        finally:
            session.close()

    @app.route("/benchmarks")
    def benchmarks_list():
        session = get_session()
        try:
            benchmarks = (
                session.query(AmazonBenchmark)
                .order_by(AmazonBenchmark.created_at.desc())
                .all()
            )
            return render_template("benchmarks.html", benchmarks=benchmarks)
        finally:
            session.close()

    @app.route("/image/<path:path>")
    def serve_image(path):
        # Allow serving from project root (covers output/, data/images/, etc.)
        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        abs_path = os.path.abspath(os.path.join(project_root, path))
        if not abs_path.startswith(project_root + os.sep):
            return "Forbidden", 403
        if not os.path.isfile(abs_path):
            return "Image not found", 404
        return send_file(abs_path)

    @app.route("/project/<int:project_id>/run", methods=["POST"])
    def project_run(project_id):
        status = _run_status.get(project_id, {})
        if status.get("state") == "running":
            return jsonify({"error": "Pipeline already running"}), 409
        _run_status[project_id] = {"state": "running", "message": "启动中..."}
        t = threading.Thread(
            target=_run_pipeline_thread, args=(project_id,), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": "启动中..."})

    @app.route("/project/<int:project_id>/status")
    def project_status(project_id):
        status = _run_status.get(project_id, {"state": "idle", "message": ""})
        return jsonify(status)

    return app
