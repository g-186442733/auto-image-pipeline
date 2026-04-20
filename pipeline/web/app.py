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
    abort,
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
from pipeline.models.tenant import Tenant
from pipeline.models.consistency_profile import ConsistencyProfile
from pipeline.models.client_feedback import ClientFeedback
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.asin_ranking import ASINRanking
from pipeline.models.image_snapshot import ImageSnapshot
from pipeline.models.knowledge_entry import KnowledgeEntry

# Global run status tracker: {project_id: {"state": "idle"|"running"|"done"|"error", "message": str}}
_run_status: dict[int, dict] = {}


def _run_pipeline_thread(project_id: int):
    """Phase 1: analyze + plan, then pause for human review."""
    from pipeline.orchestrator import step_analyze, step_plan

    try:
        _run_status[project_id] = {"state": "running", "message": "正在分析竞品..."}
        step_analyze(project_id)

        _run_status[project_id] = {"state": "running", "message": "正在生成图位规划..."}
        step_plan(project_id)

        _run_status[project_id] = {
            "state": "waiting_plan_review",
            "message": "图位规划完成，请确认后继续",
        }
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"失败: {exc}\n{traceback.format_exc()}",
        }


def _run_generate_qa_thread(project_id: int):
    """Phase 2: generate images + QA, then pause for human review."""
    from pipeline.orchestrator import step_generate, step_qa

    try:
        _run_status[project_id] = {"state": "running", "message": "正在生成图片..."}
        step_generate(project_id, adapter_name="gpt_image")

        _run_status[project_id] = {"state": "running", "message": "正在质检..."}
        step_qa(project_id)

        _run_status[project_id] = {
            "state": "waiting_qa_review",
            "message": "图片生成完成，请逐张审核",
            "approved_slots": set(),
        }
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"失败: {exc}\n{traceback.format_exc()}",
        }


def _run_redo_slot_thread(project_id: int, slot_index: int):
    """Redo a single slot: regenerate + QA."""
    from pipeline.orchestrator import step_generate, step_qa

    approved = _run_status.get(project_id, {}).get("approved_slots", set())
    try:
        _run_status[project_id] = {
            "state": "running",
            "message": f"正在重做图位 {slot_index}...",
            "approved_slots": approved,
        }
        step_generate(project_id, adapter_name="gpt_image", slot_indices=[slot_index])
        step_qa(project_id)
        approved.discard(slot_index)
        _run_status[project_id] = {
            "state": "waiting_qa_review",
            "message": "重做完成，请继续审核",
            "approved_slots": approved,
        }
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"重做失败: {exc}\n{traceback.format_exc()}",
            "approved_slots": approved,
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

    from pipeline.web.routes.project_routes import project_api_bp
    from pipeline.web.routes.hypothesis_routes import hypothesis_bp
    from pipeline.web.routes.decision_routes import decision_bp
    from pipeline.web.routes.tag_review_routes import tag_review_bp

    app.register_blueprint(project_api_bp)
    app.register_blueprint(hypothesis_bp)
    app.register_blueprint(decision_bp)
    app.register_blueprint(tag_review_bp)

    @app.route("/")
    def index():
        db = get_session()
        try:
            projects = db.query(Project).order_by(Project.updated_at.desc()).all()
            tenants = db.query(Tenant).order_by(Tenant.name).all()
            return render_template("index.html", projects=projects, tenants=tenants)
        finally:
            db.close()

    @app.route("/project/<int:project_id>")
    def project_detail(project_id):
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404
            slots = (
                db.query(SlotPlan)
                .filter_by(project_id=project_id)
                .order_by(SlotPlan.slot_index)
                .all()
            )
            prompts = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id)
                .order_by(PromptAsset.slot_index, PromptAsset.version.desc())
                .all()
            )
            benchmarks = (
                db.query(AmazonBenchmark).filter_by(project_id=project_id).all()
            )
            return render_template(
                "project_detail.html",
                project=project,
                slots=slots,
                prompts=prompts,
                benchmarks=benchmarks,
            )
        finally:
            db.close()

    @app.route("/project/new", methods=["GET", "POST"])
    def project_new():
        """轻量新建项目：3 字段表单（名称/ASIN/品类）。"""
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )

        if request.method == "GET":
            return render_template(
                "project_new_simple.html",
                amazon_categories=AMAZON_CATEGORIES,
                amazon_category_tree=json.dumps(
                    AMAZON_CATEGORY_TREE, ensure_ascii=False
                ),
            )

        # POST — 创建项目
        name = request.form.get("name", "").strip()
        if not name:
            return "项目名称为必填项", 400

        asin = request.form.get("asin", "").strip()
        category = request.form.get("category", "").strip()

        import re as _re

        db = get_session()
        try:
            tenant_id = request.form.get("tenant_id", "").strip()
            new_customer_name = request.form.get("new_customer_name", "").strip()

            if new_customer_name:
                slug = _re.sub(r"[^a-z0-9]+", "-", new_customer_name.lower()).strip("-")
                base_slug = slug
                counter = 1
                while db.query(Tenant).filter(Tenant.slug == slug).first():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                new_tenant = Tenant(name=new_customer_name, slug=slug)
                db.add(new_tenant)
                db.flush()
                tenant_id = new_tenant.id

            if not tenant_id:
                tenant_id = 1

            project = Project(
                name=name,
                asin=asin,
                category=category,
                status="draft",
                tenant_id=int(tenant_id),
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            return redirect(url_for("project_detail", project_id=project.id))
        finally:
            db.close()

    @app.route("/prompts")
    def prompts_list():
        db = get_session()
        try:
            prompts = (
                db.query(PromptAsset).order_by(PromptAsset.created_at.desc()).all()
            )
            return render_template("prompts.html", prompts=prompts)
        finally:
            db.close()

    @app.route("/benchmarks")
    def benchmarks_list():
        db = get_session()
        try:
            benchmarks = (
                db.query(AmazonBenchmark)
                .order_by(AmazonBenchmark.created_at.desc())
                .all()
            )
            return render_template("benchmarks.html", benchmarks=benchmarks)
        finally:
            db.close()

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
        result = {
            "state": status.get("state", "idle"),
            "message": status.get("message", ""),
        }

        if result["state"] == "waiting_plan_review":
            db = get_session()
            try:
                slots = (
                    db.query(SlotPlan)
                    .filter_by(project_id=project_id)
                    .order_by(SlotPlan.slot_index)
                    .all()
                )
                result["slots"] = [
                    {
                        "slot_index": s.slot_index,
                        "intent_tag": s.intent_tag,
                        "layout_tag": s.layout_tag,
                        "style_tag": s.style_tag,
                        "color_tag": getattr(s, "color_tag", ""),
                        "description": s.description,
                    }
                    for s in slots
                ]
            finally:
                db.close()

        elif result["state"] == "waiting_qa_review":
            db = get_session()
            try:
                assets = (
                    db.query(PromptAsset)
                    .filter_by(project_id=project_id)
                    .order_by(PromptAsset.slot_index)
                    .all()
                )
                approved = status.get("approved_slots", set())
                items = []
                for pa in assets:
                    qa = (
                        db.query(QARecord)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(QARecord.id.desc())
                        .first()
                    )
                    items.append(
                        {
                            "slot_index": pa.slot_index,
                            "prompt_text": pa.prompt_text[:120]
                            if pa.prompt_text
                            else "",
                            "image_url": url_for("serve_image", path=pa.image_path)
                            if pa.image_path
                            else "",
                            "version": pa.version,
                            "qa_score": qa.score if qa else None,
                            "qa_passed": qa.passed if qa else None,
                            "qa_details": qa.details if qa else "",
                            "approved": pa.slot_index in approved,
                        }
                    )
                result["items"] = items
                result["all_approved"] = (
                    len(approved) >= len(assets) and len(assets) > 0
                )
            finally:
                db.close()

        return jsonify(result)

    # --- Semi-auto pipeline review routes ---

    @app.route("/project/<int:project_id>/confirm-plan", methods=["POST"])
    def confirm_plan(project_id):
        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_plan_review":
            return jsonify({"error": "当前状态不是等待规划确认"}), 400
        _run_status[project_id] = {
            "state": "running",
            "message": "规划已确认，正在生成图片...",
        }
        t = threading.Thread(
            target=_run_generate_qa_thread, args=(project_id,), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": "开始生成图片"})

    @app.route("/project/<int:project_id>/approve-slot", methods=["POST"])
    def approve_slot(project_id):
        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        approved = status.setdefault("approved_slots", set())
        approved.add(slot_index)
        return jsonify({"approved": True, "slot_index": slot_index})

    @app.route("/project/<int:project_id>/redo-slot", methods=["POST"])
    def redo_slot(project_id):
        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        t = threading.Thread(
            target=_run_redo_slot_thread, args=(project_id, slot_index), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": f"正在重做图位 {slot_index}"})

    @app.route("/project/<int:project_id>/finish-review", methods=["POST"])
    def finish_review(project_id):
        from pipeline.orchestrator import step_report

        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        try:
            _run_status[project_id] = {"state": "running", "message": "正在生成报告..."}
            step_report(project_id)
            # 品牌自动更新：根据 A/B 测试结果更新品牌画像
            try:
                from pipeline.layers.feedback_loop import (
                    update_brand_profile_from_results,
                )

                update_brand_profile_from_results(project_id)
            except Exception as _e:
                logger.warning(
                    "Brand auto-update failed for project=%s: %s", project_id, _e
                )
            _run_status[project_id] = {
                "state": "done",
                "message": "全部完成！报告已生成。",
            }
            return jsonify({"state": "done", "message": "完成"})
        except Exception as exc:
            _run_status[project_id] = {
                "state": "error",
                "message": f"报告生成失败: {exc}",
            }
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/brand/auto-update", methods=["POST"])
    def brand_auto_update():
        from pipeline.layers.feedback_loop import update_brand_profile_from_results

        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id is required"}), 400
        brand = update_brand_profile_from_results(int(project_id))
        return jsonify(
            {"updated": True, "brand_profile_id": brand.id if brand else None}
        )

    @app.route("/api/price-band-analysis", methods=["POST"])
    def price_band_analysis():
        from pipeline.layers.price_band_analyzer import analyze_price_band

        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id is required"}), 400
        try:
            result = analyze_price_band(int(project_id), 1)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify(result)

    @app.route("/api/translate-feedback", methods=["POST"])
    def translate_feedback_route():
        from pipeline.layers.feedback_translator import translate_feedback

        data = request.get_json(silent=True) or {}
        feedback = data.get("feedback")
        project_id = data.get("project_id")
        if not feedback or not project_id:
            return jsonify({"error": "feedback and project_id are required"}), 400
        try:
            result = translate_feedback(str(feedback), int(project_id), 1)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify(result)

    @app.route("/api/fanout-query", methods=["POST"])
    def fanout_query_route():
        from pipeline.layers.fanout_engine import fanout_query

        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        prompt = data.get("prompt")
        if not project_id or not prompt:
            return jsonify({"error": "project_id and prompt are required"}), 400
        result = fanout_query(str(prompt), int(project_id), 1)
        return jsonify(result)

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
        "asin",
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
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )

        return render_template(
            "customer_input.html",
            step_data={},
            project_id=None,
            amazon_categories=AMAZON_CATEGORIES,
            amazon_category_tree=json.dumps(AMAZON_CATEGORY_TREE, ensure_ascii=False),
        )

    @app.route("/input/new", methods=["POST"])
    def customer_input_create():
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )
        from pipeline.layers.input_layer import upsert_brand_profile

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

            brand_data = {"project_id": project.id}
            if data.get("primary_color"):
                brand_data["color_system"] = data["primary_color"]
            if data.get("style_keywords"):
                brand_data["photo_style"] = data["style_keywords"]
            if data.get("brand_history"):
                brand_data["brand_story"] = data["brand_history"]
            upsert_brand_profile(brand_data)

            return redirect(url_for("project_detail", project_id=project.id))
        finally:
            db.close()

    @app.route("/input/<int:project_id>/edit", methods=["GET"])
    def customer_input_edit(project_id):
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )

        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return "Project not found", 404
            step_data = {}
            if project.customer_brief:
                step_data = json.loads(project.customer_brief)
            return render_template(
                "customer_input.html",
                step_data=step_data,
                project_id=project_id,
                amazon_categories=AMAZON_CATEGORIES,
                amazon_category_tree=json.dumps(
                    AMAZON_CATEGORY_TREE, ensure_ascii=False
                ),
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

    def _assets_dir(project_id: int, tenant_id: int = 1) -> str:
        from pipeline.utils.paths import tenant_output_dir

        base = getattr(app, "_aip_output_dir", None) or _app_config.output_dir
        base = tenant_output_dir(base, tenant_id)
        return os.path.join(base, str(project_id), "assets")

    @app.route("/upload/<int:project_id>")
    def upload_page(project_id):
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

    # --- 客户（租户）搜索 API ---

    @app.route("/api/customers/search")
    def api_customers_search():
        """根据名称模糊搜索租户，返回 [{id, name, slug}]。"""
        import re as _re

        q = request.args.get("q", "").strip()
        db = get_session()
        try:
            query = db.query(Tenant).filter(Tenant.status == "active")
            if q:
                query = query.filter(Tenant.name.ilike(f"%{q}%"))
            rows = query.order_by(Tenant.name).limit(20).all()
            return jsonify([{"id": r.id, "name": r.name, "slug": r.slug} for r in rows])
        finally:
            db.close()

    # --- 品牌三级体系 CRUD API ---

    @app.route("/api/customers", methods=["GET", "POST"])
    def api_customers():
        from pipeline.models.customer_profile import CustomerProfile

        db = get_session()
        try:
            if request.method == "GET":
                rows = db.query(CustomerProfile).all()
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "name": r.name,
                            "industry": r.industry,
                            "contact_email": r.contact_email,
                            "notes": r.notes,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            if not data.get("name"):
                return jsonify({"error": "name is required"}), 400
            cp = CustomerProfile(
                tenant_id=1,
                name=data["name"],
                industry=data.get("industry"),
                contact_email=data.get("contact_email"),
                notes=data.get("notes"),
            )
            db.add(cp)
            db.commit()
            db.refresh(cp)
            return jsonify({"id": cp.id, "name": cp.name}), 201
        finally:
            db.close()

    @app.route("/api/customers/<int:customer_id>/brands", methods=["GET", "POST"])
    def api_customer_brands(customer_id):
        from pipeline.models.customer_profile import CustomerProfile

        db = get_session()
        try:
            customer = db.query(CustomerProfile).filter_by(id=customer_id).first()
            if customer is None:
                return jsonify({"error": "Customer not found"}), 404

            if request.method == "GET":
                rows = (
                    db.query(BrandProfile)
                    .filter_by(customer_profile_id=customer_id)
                    .all()
                )
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "project_id": r.project_id,
                            "brand_tone": r.brand_tone,
                            "color_system": r.color_system,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            bp = BrandProfile(
                project_id=data.get("project_id"),
                customer_profile_id=customer_id,
                tenant_id=1,
                brand_tone=data.get("brand_tone"),
                color_system=data.get("color_system"),
            )
            db.add(bp)
            db.commit()
            db.refresh(bp)
            return jsonify({"id": bp.id, "customer_profile_id": customer_id}), 201
        finally:
            db.close()

    @app.route(
        "/api/projects/<int:project_id>/product-profile", methods=["GET", "POST"]
    )
    def api_product_profile(project_id):
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404

            pp = db.query(ProductProfile).filter_by(project_id=project_id).first()

            if request.method == "GET":
                if pp is None:
                    return jsonify({})
                return jsonify(
                    {
                        "id": pp.id,
                        "project_id": pp.project_id,
                        "brand_profile_id": pp.brand_profile_id,
                        "product_name": pp.product_name,
                        "product_category": pp.product_category,
                        "price_point": pp.price_point,
                        "key_features": pp.key_features,
                        "visual_notes": pp.visual_notes,
                    }
                )

            data = request.get_json(force=True)
            if pp is None:
                pp = ProductProfile(
                    project_id=project_id,
                    tenant_id=1,
                )
                db.add(pp)
            for field in (
                "brand_profile_id",
                "product_name",
                "product_category",
                "price_point",
                "key_features",
                "visual_notes",
            ):
                if field in data:
                    setattr(pp, field, data[field])
            db.commit()
            db.refresh(pp)
            return jsonify({"id": pp.id, "project_id": pp.project_id}), 200
        finally:
            db.close()

    @app.route("/project/<int:project_id>/aplus")
    def project_aplus(project_id):
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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

            project = db.query(Project).filter_by(id=project_id).first()
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
            project = db.query(Project).filter_by(id=project_id).first()
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
            project = db.query(Project).filter_by(id=project_id).first()
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
            project = db.query(Project).filter_by(id=project_id).first()
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
            project = db.query(Project).filter_by(id=project_id).first()
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
            project = db.query(Project).filter_by(id=project_id).first()
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

    # ---- Review Page ----

    @app.route("/review")
    def review():
        db = get_session()
        try:
            from sqlalchemy import func

            latest_sub = (
                db.query(
                    DeliveryVersion.project_id,
                    func.max(DeliveryVersion.id).label("max_id"),
                )
                .filter(DeliveryVersion.client_signed_at.is_(None))
                .group_by(DeliveryVersion.project_id)
                .subquery()
            )
            pending = (
                db.query(DeliveryVersion)
                .join(latest_sub, DeliveryVersion.id == latest_sub.c.max_id)
                .order_by(DeliveryVersion.created_at.desc())
                .all()
            )
            for dv in pending:
                proj = db.query(Project).filter_by(id=dv.project_id).first()
                dv._project_name = proj.name if proj else "Unknown"
                dv._customer_name = proj.tenant.name if proj and proj.tenant else ""
            tenants = db.query(Tenant).order_by(Tenant.name).all()
            return render_template("review.html", versions=pending, tenants=tenants)
        finally:
            db.close()

    @app.route("/review/<int:vid>/approve", methods=["POST"])
    def review_approve(vid):
        from datetime import datetime, timezone

        db = get_session()
        try:
            dv = db.query(DeliveryVersion).filter_by(id=vid).first()
            if not dv:
                return "Not Found", 404
            dv.client_signed_at = datetime.now(timezone.utc)
            db.commit()
            return redirect(url_for("review"))
        finally:
            db.close()

    @app.route("/review/<int:vid>/reject", methods=["POST"])
    def review_reject(vid):
        db = get_session()
        try:
            dv = db.query(DeliveryVersion).filter_by(id=vid).first()
            if not dv:
                return "Not Found", 404
            reason = request.form.get("reason", "")
            dv.change_summary = f"[REJECTED] {reason}\n{dv.change_summary or ''}"
            db.commit()
            return redirect(url_for("review"))
        finally:
            db.close()

    # ---- QA Dashboard ----

    @app.route("/qa-dashboard")
    def qa_dashboard():
        db = get_session()
        try:
            records = db.query(QARecord).order_by(QARecord.created_at.desc()).all()
            total = len(records)
            passed = sum(1 for r in records if r.passed)
            pass_rate = round(passed / total * 100) if total else 0
            return render_template(
                "qa_dashboard.html",
                records=records,
                total=total,
                passed=passed,
                pass_rate=pass_rate,
            )
        finally:
            db.close()

    # ---- Project Report ----

    @app.route("/project/<int:project_id>/report")
    def project_report(project_id):
        from pipeline.layers.feedback_loop import export_project_report

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404
            report = export_project_report(project_id)
            return render_template("report.html", project=project, report=report)
        finally:
            db.close()

    # ---- Project Deliver ----

    @app.route("/project/<int:project_id>/deliver")
    def project_deliver(project_id):
        import os

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404
            delivery_dir = os.path.join("data", "output", str(project_id), "delivery")
            files = []
            if os.path.isdir(delivery_dir):
                files = sorted(os.listdir(delivery_dir))
            return render_template(
                "deliver.html", project=project, files=files, delivery_dir=delivery_dir
            )
        finally:
            db.close()

    # ---- 客户管理页面 ----

    @app.route("/customers")
    def customers_list():
        """客户列表页面，展示所有租户及其项目数。"""
        from sqlalchemy import func as sa_func

        db = get_session()
        try:
            tenants = db.query(Tenant).order_by(Tenant.name).all()
            # 每个租户的项目数
            counts = dict(
                db.query(Project.tenant_id, sa_func.count(Project.id))
                .group_by(Project.tenant_id)
                .all()
            )
            return render_template("customers.html", tenants=tenants, counts=counts)
        finally:
            db.close()

    @app.route("/customers/new", methods=["POST"])
    def customers_new():
        """新增客户（租户）。"""
        name = (request.form.get("name") or "").strip()
        slug = (request.form.get("slug") or "").strip()
        if not name or not slug:
            return "名称和 Slug 不能为空", 400
        db = get_session()
        try:
            # slug 唯一性检查
            existing = db.query(Tenant).filter_by(slug=slug).first()
            if existing:
                return f"Slug '{slug}' 已存在，请使用其他值", 400
            tenant = Tenant(name=name, slug=slug)
            db.add(tenant)
            db.commit()
            return redirect(url_for("customers_list"))
        finally:
            db.close()

    return app
