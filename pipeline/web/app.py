import json
import os

from pipeline.config import config as _app_config
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
from werkzeug.utils import secure_filename

from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.aplus_content import APlusContent
from pipeline.models.consistency_profile import ConsistencyProfile
from pipeline.models.client_feedback import ClientFeedback
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.asin_ranking import ASINRanking
from pipeline.models.image_snapshot import ImageSnapshot
from pipeline.models.knowledge_entry import KnowledgeEntry

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

    @app.route("/api/projects/<int:project_id>/upload", methods=["POST"])
    def upload_file(project_id):
        ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
        MAX_SIZE = 10 * 1024 * 1024

        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({"error": f"File type '{ext}' not allowed"}), 400

        file_data = file.read()
        if len(file_data) > MAX_SIZE:
            return jsonify({"error": "File exceeds 10MB limit"}), 413
        file.seek(0)

        upload_dir = os.path.join("uploads", str(project_id))
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)

        return jsonify({"path": filepath})

    CUSTOMER_INPUT_REQUIRED = [
        "product_name",
        "asin",
        "product_category",
        "key_selling_points",
        "target_age",
        "target_gender",
        "lifestyle",
        "purchase_motivation",
        "competitor_asins",
        "differentiation",
        "primary_color",
        "style_keywords",
        "budget_level",
        "deadline",
    ]

    CUSTOMER_INPUT_ALL = CUSTOMER_INPUT_REQUIRED + [
        "reference_urls",
        "brand_history",
        "founding_idea",
        "usp_core",
        "usp_proof",
        "pain_points",
        "usage_scenario",
        "lifestyle_image",
        "season_relevance",
        "holiday_promo",
    ]

    @app.route("/input/new", methods=["GET"])
    def customer_input_new():
        return render_template("customer_input.html", step_data={}, project_id=None)

    @app.route("/input/new", methods=["POST"])
    def customer_input_create():
        data = {k: request.form.get(k, "").strip() for k in CUSTOMER_INPUT_ALL}
        missing = [f for f in CUSTOMER_INPUT_REQUIRED if not data.get(f)]
        if missing:
            return f"Missing required fields: {', '.join(missing)}", 400

        db = get_session()
        try:
            project = Project(
                name=data["product_name"],
                asin=data.get("asin", ""),
                category=data.get("product_category", ""),
                status="draft",
                customer_brief=json.dumps(data, ensure_ascii=False),
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            return redirect(url_for("project_detail", project_id=project.id))
        finally:
            db.close()

    @app.route("/input/<int:project_id>/edit", methods=["GET"])
    def customer_input_edit(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            step_data = {}
            if project.customer_brief:
                step_data = json.loads(project.customer_brief)
            return render_template(
                "customer_input.html", step_data=step_data, project_id=project_id
            )
        finally:
            db.close()

    @app.route("/input/<int:project_id>/edit", methods=["POST"])
    def customer_input_update(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            data = {k: request.form.get(k, "").strip() for k in CUSTOMER_INPUT_ALL}
            missing = [f for f in CUSTOMER_INPUT_REQUIRED if not data.get(f)]
            if missing:
                return f"Missing required fields: {', '.join(missing)}", 400
            project.name = data["product_name"]
            project.asin = data.get("asin", "")
            project.category = data.get("product_category", "")
            project.customer_brief = json.dumps(data, ensure_ascii=False)
            db.commit()
            return redirect(url_for("project_detail", project_id=project.id))
        finally:
            db.close()

    UPLOAD_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "svg"}
    UPLOAD_MAX_SIZE = 10 * 1024 * 1024

    def _assets_dir(project_id: int) -> str:
        base = getattr(app, "_aip_output_dir", None) or _app_config.output_dir
        return os.path.join(base, str(project_id), "assets")

    @app.route("/upload/<int:project_id>")
    def upload_page(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            assets_path = _assets_dir(project_id)
            files = (
                sorted(os.listdir(assets_path)) if os.path.isdir(assets_path) else []
            )
            return render_template("upload.html", project=project, files=files)
        finally:
            db.close()

    @app.route("/upload/<int:project_id>", methods=["POST"])
    def upload_asset(project_id):
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in UPLOAD_ALLOWED_EXT:
            return jsonify({"error": f"File type '{ext}' not allowed"}), 400

        file_data = file.read()
        if len(file_data) > UPLOAD_MAX_SIZE:
            return jsonify({"error": "File exceeds 10MB limit"}), 413

        assets_path = _assets_dir(project_id)
        os.makedirs(assets_path, exist_ok=True)
        filename = secure_filename(file.filename)
        with open(os.path.join(assets_path, filename), "wb") as f:
            f.write(file_data)

        if request.headers.get("Accept", "").startswith("application/json"):
            return jsonify(
                {"path": os.path.join(assets_path, filename), "filename": filename}
            )
        return redirect(url_for("upload_page", project_id=project_id))

    @app.route("/upload/<int:project_id>/delete", methods=["POST"])
    def delete_asset(project_id):
        filename = request.form.get("filename", "")
        if not filename:
            return jsonify({"error": "No filename"}), 400

        filename = secure_filename(filename)
        filepath = os.path.join(_assets_dir(project_id), filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404

        os.remove(filepath)
        if request.headers.get("Accept", "").startswith("application/json"):
            return jsonify({"deleted": filename})
        return redirect(url_for("upload_page", project_id=project_id))

    # ---- Brand Profile routes ----

    _BP_DIMENSIONS = [
        ("brand_tone", "品牌调性", "🎨"),
        ("color_system", "色彩体系", "🌈"),
        ("font_preference", "字体偏好", "🔤"),
        ("photo_style", "拍摄风格", "📷"),
        ("model_type", "模特类型", "🧑"),
        ("scene_preference", "场景偏好", "🏞️"),
        ("composition_preference", "构图偏好", "📐"),
        ("material_texture", "材质质感", "🧶"),
        ("competitor_positioning", "竞品定位", "🎯"),
        ("brand_story", "品牌故事", "📖"),
    ]

    def _build_dimensions(bp):
        return [
            {"key": key, "label": label, "icon": icon, "value": getattr(bp, key, None)}
            for key, label, icon in _BP_DIMENSIONS
        ]

    @app.route("/brand-profile/<int:project_id>", methods=["GET"])
    def brand_profile_view(project_id):
        db = get_session()
        try:
            from pipeline.layers.brand_profiler import build_brand_profile

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            bp = build_brand_profile(project_id)
            editing = request.args.get("edit") == "1"
            return render_template(
                "brand_profile.html",
                project=project,
                editing=editing,
                dimensions=_build_dimensions(bp),
            )
        finally:
            db.close()

    @app.route("/brand-profile/<int:project_id>", methods=["POST"])
    def brand_profile_update(project_id):
        db = get_session()
        try:
            from pipeline.layers.brand_profiler import build_brand_profile

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            bp = build_brand_profile(project_id)
            from pipeline.models.brand_profile import BrandProfile as BP

            bp_obj = db.query(BP).filter_by(project_id=project_id).first()
            if bp_obj is None:
                bp_obj = BP(project_id=project_id)
                db.add(bp_obj)
            for key, _, _ in _BP_DIMENSIONS:
                val = request.form.get(key, "").strip() or None
                setattr(bp_obj, key, val)
            db.commit()
            return redirect(url_for("brand_profile_view", project_id=project_id))
        finally:
            db.close()

    @app.route("/project/<int:project_id>/aplus")
    def project_aplus(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            modules = (
                db.query(APlusContent)
                .filter_by(project_id=project_id)
                .order_by(APlusContent.position_index)
                .all()
            )
            return render_template("aplus.html", project=project, modules=modules)
        finally:
            db.close()

    @app.route("/project/<int:project_id>/reference-pack")
    def project_reference_pack(project_id):
        from pipeline.layers.reference_pack import get_reference_pack
        import json as _json

        rp = get_reference_pack(project_id)
        if rp is None:
            return jsonify({"error": "Reference pack not found"}), 404
        return jsonify(
            {
                "project_id": rp.project_id,
                "product_truth": _json.loads(rp.product_truth or "{}"),
                "brand_rules": _json.loads(rp.brand_rules or "{}"),
                "winning_examples": _json.loads(rp.winning_examples or "[]"),
                "competitor_baseline": _json.loads(rp.competitor_baseline or "[]"),
                "negative_cases": _json.loads(rp.negative_cases or "[]"),
                "angle_matrix": _json.loads(rp.angle_matrix or "{}"),
            }
        )

    _CONSISTENCY_VARS = [
        ("lighting_style", "💡", "光线风格", "如: soft diffused, studio, natural"),
        ("color_palette", "🎨", "色彩系统", "如: warm earth tones, neutral, vibrant"),
        ("camera_angle", "📐", "拍摄角度", "如: eye level, 45-degree, overhead"),
        ("element_density", "📦", "元素密度", "如: minimal, medium, dense"),
        ("text_overlay_style", "🔤", "文字叠层风格", "如: minimal, bold, none"),
    ]

    @app.route("/project/<int:project_id>/consistency", methods=["GET"])
    def consistency_view(project_id):
        db = get_session()
        try:
            from pipeline.layers.consistency_system import (
                get_consistency_profile,
                validate_consistency,
            )

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            profile = get_consistency_profile(project_id)
            valid, missing = validate_consistency(project_id)
            variables = [
                {
                    "key": k,
                    "icon": icon,
                    "label": label,
                    "placeholder": ph,
                    "value": getattr(profile, k, None),
                }
                for k, icon, label, ph in _CONSISTENCY_VARS
            ]
            return render_template(
                "consistency.html",
                project=project,
                profile=profile,
                variables=variables,
                valid=valid,
                missing=missing,
            )
        finally:
            db.close()

    @app.route("/project/<int:project_id>/consistency", methods=["POST"])
    def consistency_update(project_id):
        db = get_session()
        try:
            from pipeline.layers.consistency_system import (
                get_consistency_profile,
                update_consistency_profile,
            )

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            get_consistency_profile(project_id)
            kwargs = {}
            for k, _, _, _ in _CONSISTENCY_VARS:
                val = request.form.get(k, "").strip() or None
                kwargs[k] = val
            try:
                update_consistency_profile(project_id, **kwargs)
            except ValueError:
                pass
            return redirect(url_for("consistency_view", project_id=project_id))
        finally:
            db.close()

    @app.route("/project/<int:project_id>/consistency/lock", methods=["POST"])
    def consistency_lock(project_id):
        db = get_session()
        try:
            from pipeline.layers.consistency_system import lock_consistency_profile

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            lock_consistency_profile(project_id)
            return redirect(url_for("consistency_view", project_id=project_id))
        finally:
            db.close()

    @app.route("/project/<int:project_id>/feedback", methods=["GET"])
    def feedback_view(project_id):
        db = get_session()
        try:
            from pipeline.layers.feedback_handler import get_feedback_summary

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            summary = get_feedback_summary(db, project_id)
            return render_template("feedback.html", project=project, summary=summary)
        finally:
            db.close()

    @app.route("/project/<int:project_id>/feedback", methods=["POST"])
    def feedback_submit(project_id):
        db = get_session()
        try:
            from pipeline.layers.feedback_handler import submit_feedback

            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            slot_name = request.form.get("slot_name", "").strip()
            feedback_type = request.form.get("feedback_type", "").strip()
            feedback_text = request.form.get("feedback_text", "").strip()
            if slot_name and feedback_type:
                submit_feedback(db, project_id, slot_name, feedback_type, feedback_text)
            return redirect(url_for("feedback_view", project_id=project_id))
        finally:
            db.close()

    @app.route("/project/<int:project_id>/versions")
    def version_history(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            versions = (
                db.query(DeliveryVersion)
                .filter_by(project_id=project_id)
                .order_by(DeliveryVersion.version_number.desc())
                .all()
            )
            return render_template(
                "version_history.html", project=project, versions=versions
            )
        finally:
            db.close()

    @app.route("/revision-guide")
    def revision_guide():
        from pipeline.layers.revision_lookup import REVISION_TABLE

        return render_template("revision_guide.html", table=REVISION_TABLE)

    @app.route("/project/<int:project_id>/prompts")
    def prompt_list(project_id):
        from pipeline.models.prompt_asset import PromptAsset

        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            assets = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id)
                .order_by(PromptAsset.slot_index)
                .all()
            )
            return render_template("prompt_list.html", project=project, assets=assets)
        finally:
            db.close()

    @app.route(
        "/project/<int:project_id>/prompts/<slot_name>",
        methods=["GET", "POST"],
    )
    def prompt_editor(project_id, slot_name):
        from pipeline.models.prompt_asset import PromptAsset
        from pipeline.layers.prompt_manager import (
            update_prompt_text,
            _slot_name_to_index,
        )

        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404

            slot_index = _slot_name_to_index(slot_name)
            if slot_index is None:
                return "Invalid slot name", 404

            asset = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .first()
            )
            if asset is None:
                return "Prompt asset not found", 404

            if request.method == "POST":
                new_text = request.form.get("prompt_text", "")
                update_prompt_text(db, project_id, slot_name, new_text)
                return redirect(url_for("prompt_list", project_id=project_id))

            return render_template(
                "prompt_editor.html",
                project=project,
                asset=asset,
                slot_name=slot_name,
            )
        finally:
            db.close()

    @app.route("/project/<int:project_id>/rankings", methods=["GET"])
    def rankings_view(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            from pipeline.layers.ranking_tracker import get_ranking_summary

            rankings = get_ranking_summary(db, project_id)
            return render_template(
                "ranking_history.html", project=project, rankings=rankings
            )
        finally:
            db.close()

    @app.route("/project/<int:project_id>/changes")
    def change_history(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            snapshots = (
                db.query(ImageSnapshot)
                .filter_by(project_id=project_id)
                .order_by(ImageSnapshot.captured_at.desc())
                .all()
            )
            return render_template(
                "change_history.html", project=project, snapshots=snapshots
            )
        finally:
            db.close()

    @app.route("/knowledge")
    def knowledge():
        db = get_session()
        try:
            from pipeline.layers.knowledge_base import search_entries, VALID_CATEGORIES

            q = request.args.get("q", "").strip()
            category = request.args.get("category", "").strip() or None
            entries = search_entries(db, query=q or "", category=category)
            return render_template(
                "knowledge.html",
                entries=entries,
                query=q,
                selected_category=category or "",
                categories=VALID_CATEGORIES,
            )
        finally:
            db.close()

    return app
