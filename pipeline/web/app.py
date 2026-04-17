import os
import secrets
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, send_file, session

from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.benchmark import AmazonBenchmark


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
        from pipeline.config import config as cfg

        allowed_dir = os.path.abspath(cfg.image_output_dir)
        abs_path = os.path.abspath(os.path.join(allowed_dir, path))
        if not abs_path.startswith(allowed_dir + os.sep):
            return "Forbidden", 403
        if not os.path.isfile(abs_path):
            return "Image not found", 404
        return send_file(abs_path)

    return app
