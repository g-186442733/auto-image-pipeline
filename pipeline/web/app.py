import json
import logging
import os

from pipeline.config import config as _app_config
from pipeline.constants.tags import (
    COLOR_TAGS,
    INTENT_TAGS,
    LAYOUT_TAGS,
    STYLE_TAGS,
    TAG_LOOKUP,
)
import secrets

logger = logging.getLogger(__name__)


def _json_loads_safe(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


import threading
import traceback
from datetime import datetime, timedelta

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
    flash,
)
from werkzeug.utils import secure_filename

from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.product_profile import ProductProfile
from pipeline.models.aplus_content import APlusContent
from pipeline.models.tenant import Tenant
from pipeline.models.consistency_profile import ConsistencyProfile
from pipeline.models.client_feedback import ClientFeedback
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.asin_ranking import ASINRanking
from pipeline.models.image_snapshot import ImageSnapshot
from pipeline.models.knowledge_entry import KnowledgeEntry
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.customer_brief import CustomerBrief
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.price_analysis import PriceAnalysis
from pipeline.models.promo_analysis import PromoAnalysis
from pipeline.models.pipeline_run import PipelineRun
from pipeline.models.human_image_score import HumanImageScore
from pipeline.models.flywheel_example import FlywheelExample
from pipeline.models.image_brief import ImageBrief

# Global run status tracker: {project_id: {"state": "idle"|"running"|"done"|"error", "message": str}}
_run_status: dict[int, dict] = {}


def _get_or_restore_status(project_id: int) -> dict:
    status = _run_status.get(project_id)
    if status is not None and status.get("state") not in ("idle", "done"):
        return status
    db = get_session()
    try:
        proj = db.query(Project).filter_by(id=project_id).first()
        db_status = proj.status if proj else "draft"
        latest_run = (
            db.query(PipelineRun)
            .filter_by(project_id=project_id)
            .order_by(PipelineRun.id.desc())
            .first()
        )
        latest_run_id = latest_run.id if latest_run else None
    finally:
        db.close()
    if db_status == "planned":
        restored = {
            "state": "waiting_plan_review",
            "message": "图位规划已完成，请确认后继续",
            "pipeline_run_id": latest_run_id,
            "steps": [],
            "logs": [],
        }
    elif db_status in ("generating", "generated", "qa_review", "qa_failed"):
        restored = {
            "state": "waiting_qa_review",
            "message": "图片已生成，请审核",
            "pipeline_run_id": latest_run_id,
            "steps": [],
            "logs": [],
        }
    elif db_status == "completed":
        restored = {"state": "done", "message": "流水线已完成", "steps": [], "logs": []}
    else:
        restored = {"state": "idle", "message": ""}
    _run_status[project_id] = restored
    return restored


def _step(label: str, status: str, detail: str = "") -> dict:
    return {"label": label, "status": status, "detail": detail}


def _serialize_tag_options(tags) -> list[dict[str, str]]:
    return [
        {
            "code": tag.code,
            "name_cn": tag.name_cn,
            "name_en": tag.name_en,
            "description": tag.description,
        }
        for tag in tags
    ]


TAG_OPTIONS = {
    "intent": _serialize_tag_options(INTENT_TAGS),
    "layout": _serialize_tag_options(LAYOUT_TAGS),
    "style": _serialize_tag_options(STYLE_TAGS),
    "color": _serialize_tag_options(COLOR_TAGS),
}

CUSTOM_TAG_LABELS = {
    "LAY_PRODUCT_ONLY": "单品主图",
    "LAY_DETAIL_CLOSEUP": "细节特写",
    "LAY_INFOGRAPHIC_CLEAN": "清爽信息图",
    "LAY_PACKAGING_ACCESSORY": "包装配件展示",
    "single_product_centered": "单品居中",
    "STUDIO_PREMIUM": "高端棚拍",
    "AMAZON_US_PREMIUM": "亚马逊高级风",
    "MACRO_PREMIUM": "高端微距",
    "clean_amazon_main_image": "亚马逊简洁主图",
    "BLACK": "黑色",
    "neutral_white": "中性白",
}

TAG_LOOKUP_PAYLOAD = {
    code: {
        "name_cn": tag.name_cn,
        "name_en": tag.name_en,
        "description": tag.description,
    }
    for code, tag in TAG_LOOKUP.items()
}
TAG_LOOKUP_PAYLOAD.update(
    {
        code: {"name_cn": label, "name_en": code, "description": "项目自定义标签"}
        for code, label in CUSTOM_TAG_LABELS.items()
    }
)

VALID_SLOT_TAGS = {
    "intent_tag": {tag["code"] for tag in TAG_OPTIONS["intent"]},
    "layout_tag": {tag["code"] for tag in TAG_OPTIONS["layout"]},
    "style_tag": {tag["code"] for tag in TAG_OPTIONS["style"]},
    "color_tag": {tag["code"] for tag in TAG_OPTIONS["color"]},
}


FLYWHEEL_SCORE_THRESHOLD = 4.0


def _flush_flywheel_examples(project_id: int) -> None:
    db = get_session()
    try:
        high_scores = (
            db.query(HumanImageScore)
            .filter(
                HumanImageScore.project_id == project_id,
                HumanImageScore.overall_score >= FLYWHEEL_SCORE_THRESHOLD,
                HumanImageScore.entered_flywheel == False,  # noqa: E712
            )
            .all()
        )
        for hs in high_scores:
            pa = db.query(PromptAsset).filter_by(id=hs.prompt_asset_id).first()
            pp = db.query(ProductProfile).filter_by(project_id=project_id).first()
            ex = FlywheelExample(
                prompt_asset_id=hs.prompt_asset_id,
                project_id=project_id,
                slot_index=hs.slot_index,
                slot_type=str(pa.slot_index) if pa else None,
                prompt_text=pa.prompt_text if pa else None,
                human_score=round(
                    hs.overall_score, 2
                ),  # overall_score 已是 0-5 星量程，与 pairwise vote 对齐
                product_category=pp.product_category if pp else None,
                tenant_id=hs.tenant_id,
            )
            db.add(ex)
            hs.entered_flywheel = True
        db.commit()
    except Exception as exc:
        logger.warning("飞轮写入失败 project=%s: %s", project_id, exc)
    finally:
        db.close()


def _build_verification_steps(project_id: int, has_asin: bool) -> list:
    db = get_session()
    steps = []
    try:
        benchmarks_count = (
            db.query(AmazonBenchmark).filter_by(project_id=project_id).count()
        )
        vision_count = (
            db.query(AmazonBenchmark)
            .filter(
                AmazonBenchmark.project_id == project_id,
                AmazonBenchmark.score.isnot(None),
            )
            .count()
        )

        if has_asin:
            cl = db.query(CompetitorListing).filter_by(project_id=project_id).first()
            steps.append(
                _step(
                    "Keepa API / 竞品数据拉取",
                    "success" if cl else "failed",
                    f"competitor_listings 已写入" if cl else "无竞品数据写入",
                )
            )
            steps.append(
                _step(
                    "品类竞品基准抓取",
                    "success" if benchmarks_count > 0 else "failed",
                    f"amazon_benchmarks {benchmarks_count} 条"
                    if benchmarks_count > 0
                    else "无数据写入",
                )
            )
            rc_count = db.query(ReviewCluster).filter_by(project_id=project_id).count()
            steps.append(
                _step(
                    "Review 聚类分析",
                    "success" if rc_count > 0 else "failed",
                    f"review_clusters {rc_count} 条" if rc_count > 0 else "无数据写入",
                )
            )
            pa = db.query(PriceAnalysis).filter_by(project_id=project_id).first()
            steps.append(
                _step(
                    "价格分析",
                    "success" if pa else "failed",
                    "price_analyses 已写入" if pa else "无数据写入",
                )
            )
            prom = db.query(PromoAnalysis).filter_by(project_id=project_id).first()
            steps.append(
                _step(
                    "促销分析",
                    "success" if prom else "failed",
                    "promo_analysis 已写入" if prom else "无数据写入",
                )
            )
            ib_count = db.query(ImageBrief).filter_by(project_id=project_id).count()
            steps.append(
                _step(
                    "竞品图片 Brief 生成",
                    "success" if ib_count > 0 else "failed",
                    f"image_briefs {ib_count} 条" if ib_count > 0 else "无数据写入",
                )
            )
            steps.append(
                _step(
                    "Gemini Vision 视觉分析",
                    "success" if vision_count > 0 else "failed",
                    f"{vision_count}/{benchmarks_count} 条已完成视觉评分"
                    if benchmarks_count > 0
                    else "无图片可分析",
                )
            )
        else:
            steps.append(
                _step(
                    "Keepa API / 竞品数据拉取",
                    "skipped",
                    "无 ASIN，已跳过",
                )
            )
            steps.append(
                _step(
                    "品类竞品基准抓取（降级模式）",
                    "success" if benchmarks_count > 0 else "failed",
                    f"amazon_benchmarks {benchmarks_count} 条"
                    if benchmarks_count > 0
                    else "无数据写入",
                )
            )
            for label in [
                "Review 聚类分析",
                "价格分析",
                "促销分析",
                "竞品图片 Brief 生成",
            ]:
                steps.append(_step(label, "skipped", "无 ASIN，已跳过"))
            steps.append(
                _step(
                    "Gemini Vision 视觉分析",
                    "success" if vision_count > 0 else "failed",
                    f"{vision_count}/{benchmarks_count} 条已完成视觉评分"
                    if benchmarks_count > 0
                    else "无图片可分析",
                )
            )
    finally:
        db.close()
    return steps


def _run_pipeline_thread(project_id: int):
    from pipeline.orchestrator import step_analyze, step_plan

    steps = []
    logs = []
    try:
        _run_status[project_id] = {
            "state": "running",
            "message": "正在分析竞品...",
            "steps": steps,
            "logs": logs,
        }
        db = get_session()
        try:
            proj = db.query(Project).filter_by(id=project_id).first()
            has_asin = bool(proj and proj.asin and proj.asin.strip())
        finally:
            db.close()

        logs.append(
            {
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "msg": "🔍 正在启动竞品分析...",
            }
        )

        def log_fn(msg: str):
            logs.append({"ts": datetime.utcnow().strftime("%H:%M:%S"), "msg": msg})
            _run_status[project_id]["message"] = msg

        analysis_results = step_analyze(project_id, progress_cb=log_fn)
        steps.extend(_build_verification_steps(project_id, has_asin))
        logs.append(
            {"ts": datetime.utcnow().strftime("%H:%M:%S"), "msg": "✅ 竞品分析完成"}
        )

        logs.append(
            {
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "msg": "🗂️ 正在生成图位规划...",
            }
        )
        _run_status[project_id] = {
            "state": "running",
            "message": "正在生成图位规划...",
            "steps": steps,
            "logs": logs,
        }
        step_plan(project_id, analysis_results=analysis_results)
        steps.append(_step("图位规划生成", "success", "SlotPlan 已写入"))
        logs.append(
            {
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "msg": "✅ 图位规划完成，等待确认",
            }
        )

        _run_status[project_id] = {
            "state": "waiting_plan_review",
            "message": "图位规划完成，请确认后继续",
            "steps": steps,
            "logs": logs,
            "pipeline_run_id": (analysis_results or {}).get("pipeline_run_id"),
        }
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"失败: {exc}\n{traceback.format_exc()}",
            "steps": steps,
            "logs": logs,
        }


def _run_generate_qa_thread(project_id: int):
    from pipeline.orchestrator import _finish_pipeline_run, step_generate, step_qa

    prev_steps = list(_run_status.get(project_id, {}).get("steps", []))
    logs = _run_status.get(project_id, {}).get("logs", [])
    steps = prev_steps
    # BUG-08：读取当前 run 的 pipeline_run_id，只处理本 run 的 slot
    _pipeline_run_id = _run_status.get(project_id, {}).get("pipeline_run_id")
    try:
        logs.append(
            {
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "msg": "🎨 正在生成图片...",
            }
        )
        _run_status[project_id] = {
            "state": "running",
            "message": "正在生成图片...",
            "steps": steps,
            "logs": logs,
            "pipeline_run_id": _pipeline_run_id,
        }
        step_generate(
            project_id,
            adapter_name=_app_config.image_adapter,
            pipeline_run_id=_pipeline_run_id,
        )
        steps.append(_step("图片生成", "success", "PromptAsset 图片已生成"))
        logs.append(
            {"ts": datetime.utcnow().strftime("%H:%M:%S"), "msg": "✅ 图片生成完成"}
        )

        logs.append(
            {
                "ts": datetime.utcnow().strftime("%H:%M:%S"),
                "msg": "🔬 正在执行质检...",
            }
        )
        _run_status[project_id] = {
            "state": "running",
            "message": "正在质检...",
            "steps": steps,
            "logs": logs,
            "pipeline_run_id": _pipeline_run_id,
        }
        # 必须与生成步骤使用相同 adapter，避免 QA 重试用 mock 覆盖真实图路径
        step_qa(
            project_id,
            adapter_name=_app_config.image_adapter,
            pipeline_run_id=_pipeline_run_id,
        )
        steps.append(_step("图片质检", "success", "QA 评分已完成"))
        logs.append(
            {"ts": datetime.utcnow().strftime("%H:%M:%S"), "msg": "✅ 质检完成"}
        )

        # 读取 project.status（step_qa 内部已写入 qa_passed / qa_failed）
        # 将结果同步到 pipeline_runs 表，避免 pipeline_runs.status 永远停在 running
        if _pipeline_run_id:
            from pipeline.models.base import get_session
            from pipeline.models import Project as _Project

            _sess = get_session()
            try:
                _proj = _sess.get(_Project, project_id)
                _proj_status = _proj.status if _proj else "qa_passed"
            finally:
                _sess.close()
            _pr_status = (
                _proj_status
                if _proj_status in ("qa_passed", "qa_failed")
                else "qa_passed"
            )
            _finish_pipeline_run(_pipeline_run_id, _pr_status)

        _run_status[project_id] = {
            "state": "waiting_qa_review",
            "message": "图片生成完成，请逐张审核",
            "approved_slots": set(),
            "steps": steps,
            "logs": logs,
        }
    except Exception as exc:
        if _pipeline_run_id:
            try:
                _finish_pipeline_run(_pipeline_run_id, "failed", str(exc))
            except Exception:
                pass
        _run_status[project_id] = {
            "state": "error",
            "message": f"失败: {exc}\n{traceback.format_exc()}",
            "steps": steps,
            "logs": logs,
        }


def _run_redo_slot_thread(project_id: int, slot_index: int):
    """Redo a single slot: regenerate + QA."""
    from pipeline.orchestrator import step_generate, step_qa

    prev = _run_status.get(project_id, {})
    approved = prev.get("approved_slots", set())
    pipeline_run_id = prev.get("pipeline_run_id")
    try:
        _run_status[project_id] = {
            "state": "running",
            "message": f"正在重做图位 {slot_index}...",
            "approved_slots": approved,
            "pipeline_run_id": pipeline_run_id,
        }
        step_generate(
            project_id,
            adapter_name=_app_config.image_adapter,
            slot_indices=[slot_index],
        )
        step_qa(project_id, adapter_name=_app_config.image_adapter)
        approved.discard(slot_index)
        _run_status[project_id] = {
            "state": "waiting_qa_review",
            "message": "重做完成，请继续审核",
            "approved_slots": approved,
            "pipeline_run_id": pipeline_run_id,
        }
    except Exception as exc:
        _run_status[project_id] = {
            "state": "error",
            "message": f"重做失败: {exc}\n{traceback.format_exc()}",
            "approved_slots": approved,
            "pipeline_run_id": pipeline_run_id,
        }


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)

    import json as _json

    @app.template_filter("from_json")
    def _filter_from_json(s):
        if not s:
            return {}
        try:
            return _json.loads(s) if isinstance(s, str) else s
        except Exception:
            return {}

    @app.before_request
    def _make_session_permanent():
        session.permanent = True

    create_all()

    from pipeline.web.routes.project_routes import project_api_bp
    from pipeline.web.routes.hypothesis_routes import hypothesis_bp
    from pipeline.web.routes.decision_routes import decision_bp
    from pipeline.web.routes.tag_review_routes import tag_review_bp
    from pipeline.web.routes.flywheel_routes import flywheel_bp

    app.register_blueprint(project_api_bp)
    app.register_blueprint(hypothesis_bp)
    app.register_blueprint(decision_bp)
    app.register_blueprint(tag_review_bp)
    app.register_blueprint(flywheel_bp)

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
        from flask import request as flask_request
        from pipeline.models.image_brief import ImageBrief

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404
            # 验证 tenant_id：防止跨 tenant 访问 HTML 页面
            req_tid = flask_request.args.get("tenant_id", type=int)
            if req_tid is not None and project.tenant_id != req_tid:
                return "Forbidden", 403

            selected_run_id = flask_request.args.get("run_id", type=int)

            pipeline_runs = (
                db.query(PipelineRun)
                .filter_by(project_id=project_id)
                .order_by(PipelineRun.started_at.desc())
                .all()
            )

            # 未指定 run_id 时默认选最新一次
            if selected_run_id is None and pipeline_runs:
                selected_run_id = pipeline_runs[0].id

            slots_q = db.query(SlotPlan).filter_by(project_id=project_id)
            if selected_run_id is not None:
                slots_q = slots_q.filter(SlotPlan.pipeline_run_id == selected_run_id)
            slots = slots_q.order_by(SlotPlan.slot_index).all()

            prompts_q = db.query(PromptAsset).filter_by(project_id=project_id)
            if selected_run_id is not None:
                prompts_q = prompts_q.filter(
                    PromptAsset.pipeline_run_id == selected_run_id
                )
            all_prompts_raw = prompts_q.order_by(
                PromptAsset.slot_index, PromptAsset.version.desc()
            ).all()
            # 每个 slot 只保留最新版本
            seen_prompt_slots = set()
            prompts = []
            for _p in all_prompts_raw:
                if _p.slot_index not in seen_prompt_slots:
                    seen_prompt_slots.add(_p.slot_index)
                    prompts.append(_p)
            # 构建 QA 数据映射 {prompt_asset_id: {record, details_parsed}}
            qa_map = {}
            for _p in prompts:
                _qa = (
                    db.query(QARecord)
                    .filter_by(prompt_asset_id=_p.id)
                    .order_by(QARecord.id.desc())
                    .first()
                )
                if _qa:
                    # 解析 details JSON，供模板直接使用
                    try:
                        _details = json.loads(_qa.details) if _qa.details else {}
                    except Exception:
                        _details = {}
                    qa_map[_p.id] = {
                        "record": _qa,
                        "quality_score": _details.get("quality_score"),
                        "visual_quality": _details.get("visual_quality"),
                        "visual_quality_score": (
                            (_details.get("visual_quality") or {}).get("overall")
                        ),
                        "dims": {
                            "A": {
                                "label": "平台合规",
                                "max": 25,
                                "score": _details.get("A", 0),
                                "sub": [
                                    {
                                        "key": "A1",
                                        "label": "背景纯白度",
                                        "max": 10,
                                        "score": _details.get("A1", 0),
                                    },
                                    {
                                        "key": "A2",
                                        "label": "产品占比",
                                        "max": 8,
                                        "score": _details.get("A2", 0),
                                    },
                                    {
                                        "key": "A3",
                                        "label": "无文字水印",
                                        "max": 7,
                                        "score": _details.get("A3", 0),
                                    },
                                ],
                            },
                            "B": {
                                "label": "技术质量",
                                "max": 15,
                                "score": _details.get("B", 0),
                                "sub": [
                                    {
                                        "key": "B1",
                                        "label": "分辨率清晰度",
                                        "max": 8,
                                        "score": _details.get("B1", 0),
                                    },
                                    {
                                        "key": "B2",
                                        "label": "曝光色彩",
                                        "max": 7,
                                        "score": _details.get("B2", 0),
                                    },
                                ],
                            },
                            "C": {
                                "label": "AI瑕疵检测",
                                "max": 25,
                                "score": _details.get("C", 0),
                                "sub": [
                                    {
                                        "key": "C1",
                                        "label": "边缘完整性",
                                        "max": 5,
                                        "score": _details.get("C1", 0),
                                    },
                                    {
                                        "key": "C2",
                                        "label": "无鬼影重影",
                                        "max": 4,
                                        "score": _details.get("C2", 0),
                                    },
                                    {
                                        "key": "C3",
                                        "label": "纹理自然度",
                                        "max": 4,
                                        "score": _details.get("C3", 0),
                                    },
                                    {
                                        "key": "C4",
                                        "label": "无变形畸变",
                                        "max": 4,
                                        "score": _details.get("C4", 0),
                                    },
                                    {
                                        "key": "C5",
                                        "label": "细节保真度",
                                        "max": 3,
                                        "score": _details.get("C5", 0),
                                    },
                                ],
                            },
                            "D": {
                                "label": "产品一致性",
                                "max": 25,
                                "score": _details.get("D", 0),
                                "sub": [
                                    {
                                        "key": "D1",
                                        "label": "外观形态匹配",
                                        "max": 18,
                                        "score": _details.get("D1", 0),
                                    },
                                    {
                                        "key": "D2",
                                        "label": "颜色材质匹配",
                                        "max": 7,
                                        "score": _details.get("D2", 0),
                                    },
                                ],
                            },
                            "E": {
                                "label": "商业品质",
                                "max": 10,
                                "score": _details.get("E", 0),
                                "sub": [
                                    {
                                        "key": "E1",
                                        "label": "视觉吸引力",
                                        "max": 5,
                                        "score": _details.get("E1", 0),
                                    },
                                    {
                                        "key": "E2",
                                        "label": "场景契合度",
                                        "max": 5,
                                        "score": _details.get("E2", 0),
                                    },
                                ],
                            },
                        },
                        "issues": _details.get("issues", []),
                        "reasoning": _details.get("reasoning", ""),
                    }

            benchmarks_q = db.query(AmazonBenchmark).filter_by(project_id=project_id)
            if selected_run_id is not None:
                benchmarks_q = benchmarks_q.filter(
                    AmazonBenchmark.pipeline_run_id == selected_run_id
                )
            benchmarks = benchmarks_q.all()

            brief_data = {}
            if project.customer_brief:
                try:
                    brief_data = json.loads(project.customer_brief)
                except Exception:
                    brief_data = {}

            # 检查当前 run 的 Brief 是否存在 confidence:low
            has_low_confidence = False
            image_briefs_q = db.query(ImageBrief).filter_by(project_id=project_id)
            if selected_run_id is not None:
                image_briefs_q = image_briefs_q.filter(
                    ImageBrief.pipeline_run_id == selected_run_id
                )
            for _ib in image_briefs_q.all():
                try:
                    _ib_data = json.loads(_ib.brief_json)
                    if _ib_data.get("confidence") == "low":
                        has_low_confidence = True
                        break
                except Exception:
                    pass

            slot_map = {s.slot_index: s for s in slots}

            from pipeline.models.aplus_content import APlusContent
            from pipeline.models.human_aplus_score import HumanAPlusScore
            from sqlalchemy import func as sa_func

            aplus_modules = (
                db.query(APlusContent)
                .filter_by(project_id=project_id)
                .order_by(APlusContent.slot_index, APlusContent.id)
                .all()
            )

            _score_rows = (
                db.query(
                    HumanAPlusScore.module_id,
                    sa_func.avg(
                        sa_func.coalesce(
                            HumanAPlusScore.overall_score, HumanAPlusScore.score
                        )
                    ).label("avg"),
                )
                .filter(HumanAPlusScore.module_id.in_([m.id for m in aplus_modules]))
                .group_by(HumanAPlusScore.module_id)
                .all()
            )
            aplus_avg_scores = {
                row.module_id: round(float(row.avg), 1)
                for row in _score_rows
                if row.avg is not None
            }

            # 每个 module 最新一票（用于初始化前端星星高亮）
            _my_score_rows = (
                db.query(HumanAPlusScore)
                .filter(HumanAPlusScore.module_id.in_([m.id for m in aplus_modules]))
                .order_by(HumanAPlusScore.id.desc())
                .all()
            )
            _seen = set()
            aplus_my_scores = {}
            for row in _my_score_rows:
                if row.module_id not in _seen:
                    aplus_my_scores[row.module_id] = {
                        "score": row.score,
                        "overall_score": row.overall_score,
                        "image_quality": row.score_image_quality,
                        "copy_quality": row.score_copy_quality,
                        "layout": row.score_layout,
                        "brand_fit": row.score_brand_fit,
                        "conversion": row.score_conversion,
                    }
                    _seen.add(row.module_id)

            aplus_missing_steps = []

            _brief_json = json.loads(project.customer_brief or "{}")
            if not _brief_json.get("listing_title"):
                aplus_missing_steps.append("Brief（Listing 标题）")

            _has_competitor = (
                db.query(CompetitorListing).filter_by(project_id=project_id).first()
            )
            if not _has_competitor:
                aplus_missing_steps.append("竞品基准分析")

            _has_slot = db.query(SlotPlan).filter_by(project_id=project_id).first()
            if not _has_slot:
                aplus_missing_steps.append("图位规划")

            return render_template(
                "project_detail.html",
                project=project,
                slots=slots,
                slot_map=slot_map,
                prompts=prompts,
                benchmarks=benchmarks,
                brief_data=brief_data,
                tag_options=TAG_OPTIONS,
                tag_lookup=TAG_LOOKUP_PAYLOAD,
                pipeline_runs=pipeline_runs,
                selected_run_id=selected_run_id,
                qa_map=qa_map,
                has_low_confidence=has_low_confidence,
                aplus_modules=aplus_modules,
                aplus_avg_scores=aplus_avg_scores,
                aplus_my_scores=aplus_my_scores,
                aplus_missing_steps=aplus_missing_steps,
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
                first_tenant = db.query(Tenant).order_by(Tenant.id).first()
                tenant_id = first_tenant.id if first_tenant else 1

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

    _bm_retry_status: dict[int, dict] = {}

    def _run_benchmark_retry_thread(project_id: int) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from pipeline.layers.vision_analyzer import analyze_image
        from pipeline.layers.amazon_data import scrape_listing_images

        db = get_session()
        retried = 0
        updated = 0
        try:
            null_image_bms = (
                db.query(AmazonBenchmark)
                .filter(
                    AmazonBenchmark.project_id == project_id,
                    AmazonBenchmark.image_url.is_(None),
                )
                .all()
            )

            for bm in null_image_bms:
                retried += 1
                try:
                    images = scrape_listing_images(bm.competitor_asin)
                    if images:
                        matched = next(
                            (
                                url
                                for s, url in images
                                if bm.image_slot and s == bm.image_slot
                            ),
                            None,
                        )
                        bm.image_url = matched if matched else images[0][1]
                        updated += 1
                except Exception as exc:
                    logger.warning(
                        "重新抓取竞品图片失败 benchmark_id=%d asin=%s: %s",
                        bm.id,
                        bm.competitor_asin,
                        exc,
                    )
            db.commit()

            all_need_analysis = (
                db.query(AmazonBenchmark)
                .filter(
                    AmazonBenchmark.project_id == project_id,
                    AmazonBenchmark.image_url.isnot(None),
                    AmazonBenchmark.analysis.is_(None),
                )
                .all()
            )

            if all_need_analysis:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    fut_to_bm = {
                        pool.submit(analyze_image, bm.image_url): bm
                        for bm in all_need_analysis
                    }
                    for fut in as_completed(fut_to_bm):
                        bm = fut_to_bm[fut]
                        try:
                            result = fut.result()
                            bm.analysis = __import__("json").dumps(result)
                            bm.score = result.get("quality_score")
                            updated += 1
                        except Exception as exc:
                            logger.warning(
                                "Vision 重分析失败 benchmark_id=%d: %s", bm.id, exc
                            )
                db.commit()

            _bm_retry_status[project_id] = {
                "state": "idle",
                "retried": retried,
                "updated": updated,
            }
            logger.info(
                "竞品重试完成 project_id=%d retried=%d updated=%d",
                project_id,
                retried,
                updated,
            )
        except Exception as exc:
            logger.error("竞品重试线程异常 project_id=%d: %s", project_id, exc)
            _bm_retry_status[project_id] = {
                "state": "error",
                "error": str(exc),
                "retried": retried,
                "updated": updated,
            }
        finally:
            db.close()

    @app.route("/project/<int:project_id>/benchmarks/retry", methods=["POST"])
    def benchmark_retry(project_id):
        status = _bm_retry_status.get(project_id, {})
        if status.get("state") == "running":
            return jsonify({"error": "已有重试任务正在进行中"}), 409
        _bm_retry_status[project_id] = {"state": "running"}
        t = threading.Thread(
            target=_run_benchmark_retry_thread, args=(project_id,), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": "重试任务已启动"}), 202

    @app.route("/project/<int:project_id>/benchmarks/retry/status")
    def benchmark_retry_status(project_id):
        status = _bm_retry_status.get(project_id, {"state": "idle"})
        return jsonify(status)

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
        # 若传入 run_id，直接查历史 Run 数据，跳过内存状态
        view_run_id_early = request.args.get("run_id", type=int)
        if view_run_id_early:
            db = get_session()
            try:
                all_assets = (
                    db.query(PromptAsset)
                    .filter_by(project_id=project_id)
                    .filter(PromptAsset.pipeline_run_id == view_run_id_early)
                    .order_by(PromptAsset.slot_index, PromptAsset.version.desc())
                    .all()
                )
                seen_slots = set()
                assets = []
                for a in all_assets:
                    if a.slot_index not in seen_slots:
                        seen_slots.add(a.slot_index)
                        assets.append(a)
                items = []
                for pa in assets:
                    qa = (
                        db.query(QARecord)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(QARecord.id.desc())
                        .first()
                    )
                    hs = (
                        db.query(HumanImageScore)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(HumanImageScore.id.desc())
                        .first()
                    )
                    qa_details = (
                        _json_loads_safe(qa.details) if qa and qa.details else {}
                    )
                    slot = (
                        db.query(SlotPlan)
                        .filter_by(project_id=project_id, slot_index=pa.slot_index)
                        .first()
                    )
                    items.append(
                        {
                            "id": pa.id,
                            "slot_index": pa.slot_index,
                            "intent_tag": slot.intent_tag if slot else "",
                            "prompt_text": pa.prompt_text if pa.prompt_text else "",
                            "model_name": pa.model_name or "",
                            "image_url": url_for("serve_image", path=pa.image_path)
                            if pa.image_path
                            else "",
                            "version": pa.version,
                            "qa_score": qa.score if qa else None,
                            "quality_score": qa_details.get("quality_score"),
                            "visual_quality": qa_details.get("visual_quality"),
                            "visual_quality_score": (
                                qa_details.get("visual_quality") or {}
                            ).get("overall"),
                            "qa_passed": qa.passed if qa else None,
                            "qa_details": qa.details if qa else "",
                            "delivery_status": pa.status or "",
                            "visual_tags": pa.visual_tags or "",
                            "approved": bool(pa.approved),
                            "human_scores": {
                                "fidelity": hs.score_fidelity,
                                "lighting": hs.score_lighting,
                                "composition": hs.score_composition,
                                "material": hs.score_material,
                                "commercial": hs.score_commercial,
                                "overall": hs.overall_score,
                                "failure_tags": hs.get_failure_tags(),
                            }
                            if hs
                            else None,
                        }
                    )
                all_approved = (
                    all(bool(pa.approved) for pa in assets) and len(assets) > 0
                )
                proj = db.query(Project).filter_by(id=project_id).first()
                db_status = proj.status if proj else "draft"
                _DB_TO_STATE = {
                    "planned": "waiting_plan_review",
                    "generating": "waiting_qa_review",
                    "generated": "waiting_qa_review",
                    "qa_review": "waiting_qa_review",
                    "qa_failed": "waiting_qa_review",
                    "completed": "done",
                }
                actual_state = _DB_TO_STATE.get(db_status, "done")
                return jsonify(
                    {
                        "state": actual_state,
                        "message": "",
                        "steps": [],
                        "logs": [],
                        "items": items,
                        "all_approved": all_approved,
                    }
                )
            finally:
                db.close()

        status = _run_status.get(project_id)
        if status is None:
            db = get_session()
            try:
                proj = db.query(Project).filter_by(id=project_id).first()
                db_status = proj.status if proj else "draft"
            finally:
                db.close()
            if db_status == "planned":
                status = {
                    "state": "waiting_plan_review",
                    "message": "图位规划已完成，请确认后继续",
                    "steps": [],
                    "logs": [],
                }
            elif db_status in ("generating", "generated", "qa_review", "qa_failed"):
                status = {
                    "state": "waiting_qa_review",
                    "message": "图片已生成，请审核",
                    "steps": [],
                    "logs": [],
                }
            elif db_status == "completed":
                status = {
                    "state": "done",
                    "message": "流水线已完成",
                    "steps": [],
                    "logs": [],
                }
            else:
                status = {"state": "idle", "message": ""}
        result = {
            "state": status.get("state", "idle"),
            "message": status.get("message", ""),
            "steps": status.get("steps", []),
            "logs": status.get("logs", []),
        }

        if result["state"] == "done":
            result["report_url"] = status.get("report_url", "")
            view_run_id = request.args.get("run_id", type=int)
            db = get_session()
            try:
                assets_q = db.query(PromptAsset).filter_by(project_id=project_id)
                if view_run_id:
                    assets_q = assets_q.filter(
                        PromptAsset.pipeline_run_id == view_run_id
                    )
                all_assets = assets_q.order_by(
                    PromptAsset.slot_index, PromptAsset.version.desc()
                ).all()
                seen_slots = set()
                assets = []
                for a in all_assets:
                    if a.slot_index not in seen_slots:
                        seen_slots.add(a.slot_index)
                        assets.append(a)
                items = []
                for pa in assets:
                    qa = (
                        db.query(QARecord)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(QARecord.id.desc())
                        .first()
                    )
                    hs = (
                        db.query(HumanImageScore)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(HumanImageScore.id.desc())
                        .first()
                    )
                    qa_details = (
                        _json_loads_safe(qa.details) if qa and qa.details else {}
                    )
                    items.append(
                        {
                            "id": pa.id,
                            "slot_index": pa.slot_index,
                            "prompt_text": pa.prompt_text if pa.prompt_text else "",
                            "model_name": pa.model_name or "",
                            "image_url": url_for("serve_image", path=pa.image_path)
                            if pa.image_path
                            else "",
                            "version": pa.version,
                            "qa_score": qa.score if qa else None,
                            "quality_score": qa_details.get("quality_score"),
                            "visual_quality": qa_details.get("visual_quality"),
                            "visual_quality_score": (
                                qa_details.get("visual_quality") or {}
                            ).get("overall"),
                            "qa_passed": qa.passed if qa else None,
                            "qa_details": qa.details if qa else "",
                            "delivery_status": pa.status or "",
                            "visual_tags": pa.visual_tags or "",
                            "approved": bool(pa.approved),
                            "human_scores": {
                                "fidelity": hs.score_fidelity,
                                "lighting": hs.score_lighting,
                                "composition": hs.score_composition,
                                "material": hs.score_material,
                                "commercial": hs.score_commercial,
                                "overall": hs.overall_score,
                                "failure_tags": hs.get_failure_tags(),
                            }
                            if hs
                            else None,
                        }
                    )
                result["items"] = items
                result["all_approved"] = (
                    all(bool(pa.approved) for pa in assets) and len(assets) > 0
                )
            finally:
                db.close()

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
                        "custom_prompt": s.custom_prompt or "",
                        "custom_image_paths": [
                            p
                            for p in (s.custom_image_paths or "").split(",")
                            if p.strip()
                        ],
                    }
                    for s in slots
                ]
            finally:
                db.close()
            result["steps"] = status.get("steps", [])

        elif result["state"] == "waiting_qa_review":
            db = get_session()
            try:
                view_run_id = request.args.get("run_id", type=int)
                assets_q = db.query(PromptAsset).filter_by(project_id=project_id)
                if view_run_id:
                    assets_q = assets_q.filter(
                        PromptAsset.pipeline_run_id == view_run_id
                    )
                all_assets = assets_q.order_by(
                    PromptAsset.slot_index, PromptAsset.version.desc()
                ).all()
                seen_slots = set()
                assets = []
                for a in all_assets:
                    if a.slot_index not in seen_slots:
                        seen_slots.add(a.slot_index)
                        assets.append(a)
                approved = status.get("approved_slots", set())
                items = []
                for pa in assets:
                    qa = (
                        db.query(QARecord)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(QARecord.id.desc())
                        .first()
                    )
                    hs = (
                        db.query(HumanImageScore)
                        .filter_by(prompt_asset_id=pa.id)
                        .order_by(HumanImageScore.id.desc())
                        .first()
                    )
                    items.append(
                        {
                            "id": pa.id,
                            "slot_index": pa.slot_index,
                            "prompt_text": pa.prompt_text if pa.prompt_text else "",
                            "model_name": pa.model_name or "",
                            "image_url": url_for("serve_image", path=pa.image_path)
                            if pa.image_path
                            else "",
                            "version": pa.version,
                            "qa_score": qa.score if qa else None,
                            "qa_passed": qa.passed if qa else None,
                            "qa_details": qa.details if qa else "",
                            "delivery_status": pa.status or "",
                            "visual_tags": pa.visual_tags or "",
                            "approved": bool(pa.approved),
                            # rejected 字段：套图拒绝状态（不触发重生）
                            "rejected": bool(pa.rejected)
                            if pa.rejected is not None
                            else False,
                            "human_scores": {
                                "fidelity": hs.score_fidelity,
                                "lighting": hs.score_lighting,
                                "composition": hs.score_composition,
                                "material": hs.score_material,
                                "commercial": hs.score_commercial,
                                "overall": hs.overall_score,
                                "failure_tags": hs.get_failure_tags(),
                            }
                            if hs
                            else None,
                        }
                    )
                result["items"] = items
                result["all_approved"] = (
                    all(bool(pa.approved) for pa in assets) and len(assets) > 0
                )
            finally:
                db.close()

        return jsonify(result)

    # --- Semi-auto pipeline review routes ---

    @app.route("/project/<int:project_id>/update-slot-plan", methods=["POST"])
    def update_slot_plan(project_id):
        status = _get_or_restore_status(project_id)
        if status.get("state") != "waiting_plan_review":
            return jsonify({"error": "当前状态不是等待规划确认"}), 400

        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400

        updates = {
            "intent_tag": (data.get("intent_tag") or "").strip(),
            "layout_tag": (data.get("layout_tag") or "").strip(),
            "style_tag": (data.get("style_tag") or "").strip(),
            "color_tag": (data.get("color_tag") or "").strip(),
            "description": (data.get("description") or "").strip(),
        }

        for field, valid_values in VALID_SLOT_TAGS.items():
            value = updates[field]
            if value not in valid_values:
                return jsonify({"error": f"{field} 非法: {value or '空值'}"}), 400

        db = get_session()
        try:
            slot = (
                db.query(SlotPlan)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .first()
            )
            if not slot:
                return jsonify({"error": "图位不存在"}), 404

            slot.intent_tag = updates["intent_tag"]
            slot.layout_tag = updates["layout_tag"]
            slot.style_tag = updates["style_tag"]
            slot.color_tag = updates["color_tag"]
            slot.description = updates["description"]

            if "custom_prompt" in data:
                slot.custom_prompt = (data["custom_prompt"] or "").strip() or None

            db.commit()

            return jsonify(
                {
                    "ok": True,
                    "slot": {
                        "slot_index": slot.slot_index,
                        "intent_tag": slot.intent_tag,
                        "layout_tag": slot.layout_tag,
                        "style_tag": slot.style_tag,
                        "color_tag": slot.color_tag,
                        "description": slot.description or "",
                        "custom_prompt": slot.custom_prompt or "",
                    },
                }
            )
        finally:
            db.close()

    @app.route(
        "/project/<int:project_id>/slot/<int:slot_index>/custom-image",
        methods=["POST"],
    )
    def upload_slot_custom_image(project_id, slot_index):
        db = get_session()
        try:
            slot = (
                db.query(SlotPlan)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .first()
            )
            if not slot:
                return jsonify({"error": "图位不存在"}), 404

            existing: list[str] = []
            if slot.custom_image_paths:
                existing = [p for p in slot.custom_image_paths.split(",") if p.strip()]

            upload_dir = os.path.join("uploads", str(project_id), f"slot_{slot_index}")
            os.makedirs(upload_dir, exist_ok=True)

            new_files = request.files.getlist("custom_images")
            added: list[str] = []
            for f in new_files:
                if not f or not f.filename:
                    continue
                fname = secure_filename(f.filename)
                fpath = os.path.join(upload_dir, fname)
                f.save(fpath)
                added.append(fpath)

            combined = existing + added
            if len(combined) > 2:
                return jsonify({"error": "参考图最多 2 张"}), 400

            slot.custom_image_paths = ",".join(combined) if combined else None
            db.commit()

            return jsonify({"ok": True, "custom_image_paths": combined})
        finally:
            db.close()

    @app.route(
        "/project/<int:project_id>/slot/<int:slot_index>/custom-image/delete",
        methods=["POST"],
    )
    def delete_slot_custom_image(project_id, slot_index):
        data = request.get_json(force=True) or {}
        target = data.get("path", "").strip()
        if not target:
            return jsonify({"error": "缺少 path 参数"}), 400
        db = get_session()
        try:
            slot = (
                db.query(SlotPlan)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .first()
            )
            if not slot:
                return jsonify({"error": "图位不存在"}), 404
            existing = [
                p for p in (slot.custom_image_paths or "").split(",") if p.strip()
            ]
            remaining = [p for p in existing if p != target]
            slot.custom_image_paths = ",".join(remaining) if remaining else None
            db.commit()
            if os.path.exists(target):
                os.remove(target)
            return jsonify({"ok": True, "custom_image_paths": remaining})
        finally:
            db.close()

    @app.route("/project/<int:project_id>/confirm-plan", methods=["POST"])
    def confirm_plan(project_id):
        status = _get_or_restore_status(project_id)
        if status.get("state") != "waiting_plan_review":
            return jsonify({"error": "当前状态不是等待规划确认"}), 400
        db = get_session()
        try:
            proj = db.query(Project).filter_by(id=project_id).first()
            if not proj:
                return jsonify({"error": "项目不存在"}), 404
            brief = json.loads(proj.customer_brief or "{}")
            if not brief.get("white_bg_image_path"):
                return jsonify({"error": "请先上传白底图，否则无法生成真实产品图"}), 400
        finally:
            db.close()
        # 保留之前存储的 pipeline_run_id，避免 BUG-08 过滤失效
        _prev_pipeline_run_id = _run_status.get(project_id, {}).get("pipeline_run_id")
        _run_status[project_id] = {
            "state": "running",
            "message": "规划已确认，正在生成图片...",
            "pipeline_run_id": _prev_pipeline_run_id,
        }
        t = threading.Thread(
            target=_run_generate_qa_thread, args=(project_id,), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": "开始生成图片"})

    @app.route("/project/<int:project_id>/approve-slot", methods=["POST"])
    def approve_slot(project_id):
        status = _get_or_restore_status(project_id)
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        # 允许已通过的槽重新编辑评分；其他非审核状态仍拒绝
        state = status.get("state")
        already_approved = slot_index in status.get("approved_slots", set())
        if state != "waiting_qa_review" and not already_approved:
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        approved = status.setdefault("approved_slots", set())
        approved.add(slot_index)

        scores = data.get("scores") or {}
        failure_tags = data.get("failure_tags") or []
        overall_score = data.get("overall_score")
        run_id = data.get("run_id")

        db = get_session()
        try:
            q = db.query(PromptAsset).filter_by(
                project_id=project_id, slot_index=slot_index
            )
            # 优先按 run_id 精确匹配，保证更新的是页面所显示的 PA
            if run_id:
                q = q.filter(PromptAsset.pipeline_run_id == run_id)
            pa = q.order_by(PromptAsset.version.desc()).first()
            if pa:
                pa.approved = True
                human_score = None
                if scores and overall_score is not None:
                    human_score = HumanImageScore(
                        prompt_asset_id=pa.id,
                        project_id=project_id,
                        slot_index=slot_index,
                        score_fidelity=scores.get("fidelity"),
                        score_lighting=scores.get("lighting"),
                        score_composition=scores.get("composition"),
                        score_material=scores.get("material"),
                        score_commercial=scores.get("commercial"),
                        overall_score=overall_score,
                        failure_tags=json.dumps(failure_tags, ensure_ascii=False),
                    )
                    db.add(human_score)
                    db.flush()
                    try:
                        from pipeline.layers.flywheel_observation import (
                            record_listing_human_observation,
                        )
                        from pipeline.models.slot_plan import SlotPlan

                        slot_plan = (
                            db.query(SlotPlan)
                            .filter_by(project_id=project_id, slot_index=slot_index)
                            .first()
                        )
                        record_listing_human_observation(db, pa, human_score, slot_plan)
                    except Exception as _obs_exc:
                        logger.warning(
                            "human flywheel observation failed project=%s slot=%s: %s",
                            project_id,
                            slot_index,
                            _obs_exc,
                        )
                db.commit()
        finally:
            db.close()
        # 每次 Approve 后立即将评分写入飞轮训练池，无需等待最终报告
        _flush_flywheel_examples(project_id)
        return jsonify({"approved": True, "slot_index": slot_index})

    @app.route("/api/prompt/<int:prompt_asset_id>/translate-zh", methods=["POST"])
    def translate_prompt_zh(prompt_asset_id):
        from pipeline.layers.prompt_translator import (
            PromptTranslationError,
            translate_prompt_to_zh,
        )

        db = get_session()
        try:
            pa = db.query(PromptAsset).filter_by(id=prompt_asset_id).first()
            if not pa:
                return jsonify({"error": "提示词不存在"}), 404
            if pa.prompt_text_zh:
                return jsonify({"zh": pa.prompt_text_zh, "cached": True})
            try:
                translated = translate_prompt_to_zh(pa.prompt_text)
            except PromptTranslationError as exc:
                return jsonify({"error": str(exc)}), 502
            pa.prompt_text_zh = translated
            db.commit()
            return jsonify({"zh": translated, "cached": False})
        finally:
            db.close()

    @app.route("/project/<int:project_id>/reject-slot", methods=["POST"])
    def reject_slot(project_id):
        """将指定图位标记为拒绝；不启动重生线程，仅打标记"""
        status = _get_or_restore_status(project_id)
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        # 如果该图位之前已 approve，从内存集合移除
        approved = status.get("approved_slots", set())
        approved.discard(slot_index)
        db = get_session()
        try:
            pa = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .order_by(PromptAsset.version.desc())
                .first()
            )
            if not pa:
                return jsonify({"error": f"图位 {slot_index} 不存在或尚未生成"}), 404
            pa.rejected = True
            pa.approved = False
            db.commit()
        finally:
            db.close()
        return jsonify({"rejected": True, "slot_index": slot_index})

    @app.route("/project/<int:project_id>/redo-slot", methods=["POST"])
    def redo_slot(project_id):
        status = _get_or_restore_status(project_id)
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        db = get_session()
        try:
            pa = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .first()
            )
            if not pa:
                return jsonify({"error": f"图位 {slot_index} 不存在或尚未生成"}), 404
            pa.approved = False
            db.commit()
        finally:
            db.close()
        t = threading.Thread(
            target=_run_redo_slot_thread, args=(project_id, slot_index), daemon=True
        )
        t.start()
        return jsonify({"state": "running", "message": f"正在重做图位 {slot_index}"})

    @app.route("/project/<int:project_id>/edit-prompt-and-redo", methods=["POST"])
    def edit_prompt_and_redo(project_id):
        status = _get_or_restore_status(project_id)
        if status.get("state") != "waiting_qa_review":
            return jsonify({"error": "当前状态不是等待QA审核"}), 400
        data = request.get_json(force=True)
        slot_index = data.get("slot_index")
        new_prompt = (data.get("prompt_text") or "").strip()
        if slot_index is None:
            return jsonify({"error": "缺少 slot_index"}), 400
        if not new_prompt:
            return jsonify({"error": "Prompt 不能为空"}), 400
        db = get_session()
        try:
            # 更新最新版本的 PromptAsset 的 prompt_text
            pa = (
                db.query(PromptAsset)
                .filter_by(project_id=project_id, slot_index=slot_index)
                .order_by(PromptAsset.version.desc())
                .first()
            )
            if not pa:
                return jsonify(
                    {"error": f"找不到图位 {slot_index} 的 PromptAsset"}
                ), 404
            pa.prompt_text = new_prompt
            pa.prompt_text_zh = None
            pa.approved = False
            pa.user_edited = True
            db.commit()
        finally:
            db.close()
        # 重新生成该图位（同 redo_slot 逻辑）
        approved = _run_status.get(project_id, {}).get("approved_slots", set())
        approved.discard(slot_index)
        t = threading.Thread(
            target=_run_redo_slot_thread, args=(project_id, slot_index), daemon=True
        )
        t.start()
        return jsonify(
            {"state": "running", "message": f"正在用新Prompt重做图位 {slot_index}"}
        )

    @app.route("/project/<int:project_id>/finish-review", methods=["POST"])
    def finish_review(project_id):
        from pipeline.orchestrator import step_deliver, step_report

        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_qa_review":
            db = get_session()
            try:
                proj = db.query(Project).filter_by(id=project_id).first()
                db_ok = proj and proj.status in ("qa_passed", "waiting_qa_review")
            finally:
                db.close()
            if not db_ok:
                return jsonify({"error": "当前状态不是等待QA审核"}), 400
            _run_status[project_id] = {"state": "waiting_qa_review", "steps": []}
            status = _run_status[project_id]
        try:
            prev_steps = list(status.get("steps", []))
            _run_status[project_id] = {
                "state": "running",
                "message": "正在生成报告...",
                "steps": prev_steps,
            }
            step_deliver(project_id)
            step_report(project_id)
            prev_steps.append(_step("最终报告生成", "success", "报告已生成"))
            try:
                from pipeline.layers.feedback_loop import (
                    update_brand_profile_from_results,
                )

                update_brand_profile_from_results(project_id)
                prev_steps.append(_step("品牌画像更新", "success", "自动更新完成"))
            except Exception as _e:
                logger.warning(
                    "Brand auto-update failed for project=%s: %s", project_id, _e
                )
                prev_steps.append(
                    _step("品牌画像更新", "failed", "自动更新失败（不影响主流程）")
                )

            _flush_flywheel_examples(project_id)

            _run_status[project_id] = {
                "state": "done",
                "message": "全部完成！报告已生成。",
                "steps": prev_steps,
                "report_url": url_for("project_report", project_id=project_id),
            }
            return jsonify({"state": "done", "message": "完成"})
        except Exception as exc:
            _run_status[project_id] = {
                "state": "error",
                "message": f"报告生成失败: {exc}",
            }
            return jsonify({"error": str(exc)}), 500

    @app.route(
        "/project/<int:project_id>/regen-slot/<int:slot_index>", methods=["POST"]
    )
    def regen_slot(project_id, slot_index):
        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_plan_review":
            return jsonify({"error": "当前状态不是等待规划确认"}), 400
        _run_status[project_id] = {
            "state": "running",
            "message": f"正在重新规划图位 {slot_index}...",
            "logs": status.get("logs", []),
        }

        def _regen(pid, sidx):
            from pipeline.orchestrator import step_regen_single_slot

            try:
                step_regen_single_slot(pid, sidx)
                _run_status[pid] = {
                    "state": "waiting_plan_review",
                    "message": f"图位 {sidx} 重新规划完成，请确认",
                    "logs": _run_status.get(pid, {}).get("logs", []),
                }
            except Exception as exc:
                _run_status[pid] = {
                    "state": "error",
                    "message": f"重新规划失败: {exc}",
                }

        t = threading.Thread(target=_regen, args=(project_id, slot_index), daemon=True)
        t.start()
        return jsonify(
            {"state": "running", "message": f"正在重新规划图位 {slot_index}"}
        )

    @app.route("/project/<int:project_id>/regen-all-slots", methods=["POST"])
    def regen_all_slots(project_id):
        status = _run_status.get(project_id, {})
        if status.get("state") != "waiting_plan_review":
            return jsonify({"error": "当前状态不是等待规划确认"}), 400
        _run_status[project_id] = {
            "state": "running",
            "message": "正在重新规划全部图位...",
            "logs": status.get("logs", []),
        }

        def _regen_all(pid):
            from pipeline.orchestrator import step_regen_single_slot

            errors = []
            for sidx in range(1, 9):
                try:
                    step_regen_single_slot(pid, sidx)
                except Exception as exc:
                    errors.append(f"slot {sidx}: {exc}")
            if errors:
                _run_status[pid] = {
                    "state": "error",
                    "message": "部分图位重新规划失败: " + "; ".join(errors),
                }
            else:
                _run_status[pid] = {
                    "state": "waiting_plan_review",
                    "message": "全部重新规划完成，请确认",
                    "logs": _run_status.get(pid, {}).get("logs", []),
                }

        t = threading.Thread(target=_regen_all, args=(project_id,), daemon=True)
        t.start()
        return jsonify({"state": "running", "message": "正在重新规划全部图位"})

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
    ]

    CUSTOMER_INPUT_ALL = CUSTOMER_INPUT_REQUIRED + [
        "product_profile_id",
        "asin",
        "price_point",
        "key_features",
        "visual_notes",
        "primary_color",
        "competitor_asins",
        "differentiation",
        "reference_urls",
        "reference_image_paths",
        "listing_title",
        "listing_keywords",
        "listing_bullets",
        "target_audience",
        "customer_pain_points",
        "audience_scenarios",
        "brand_voice",
        "product_dimensions",
        "product_weight",
        "product_material",
        "white_bg_image_path",
        "multiangle_image_paths",
        "packaging_image_path",
        "inbox_flatlay_image_path",
        "detail_closeup_image_paths",
        "scale_ref_image_path",
        "usage_context_image_paths",
        "color_variant_image_paths",
        "custom_requirements_text",
        "style_direction",
        "must_show",
        "must_not_show",
        "listing_image_preferences",
        "aplus_module_preferences",
        "allow_invent_accessories",
        "allow_invent_color_variants",
        "allow_ai_background_generation",
        "prefer_real_product_composite",
    ]

    @app.route("/input/new", methods=["GET"])
    def customer_input_new():
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )

        db = get_session()
        try:
            tenants = db.query(Tenant).order_by(Tenant.name).all()
            tenants_json = json.dumps(
                [{"id": t.id, "name": t.name} for t in tenants], ensure_ascii=False
            )
        finally:
            db.close()

        return render_template(
            "customer_input.html",
            step_data={},
            project_id=None,
            amazon_categories=AMAZON_CATEGORIES,
            amazon_category_tree=json.dumps(AMAZON_CATEGORY_TREE, ensure_ascii=False),
            tenants_json=tenants_json,
        )

    @app.route("/input/new", methods=["POST"])
    def customer_input_create():
        from pipeline.constants.amazon_categories import (
            AMAZON_CATEGORIES,
            AMAZON_CATEGORY_TREE,
        )

        data = {k: request.form.get(k, "").strip() for k in CUSTOMER_INPUT_ALL}
        missing = [f for f in CUSTOMER_INPUT_REQUIRED if not data.get(f)]
        if missing:
            return f"Missing required fields: {', '.join(missing)}", 400

        white_bg_file = request.files.get("white_bg_file")
        if not white_bg_file or not white_bg_file.filename:
            return "Missing required field: white_bg_file (产品白底图为必填项)", 400
        try:
            from PIL import Image as _PILImage
            from io import BytesIO as _BytesIO

            _wb_data = white_bg_file.read()
            _img = _PILImage.open(_BytesIO(_wb_data))
            _img.verify()
            white_bg_file.seek(0)
        except Exception:
            return "产品白底图文件损坏或格式不支持，请重新上传", 400

        db = get_session()
        try:
            import re as _re

            tenant_id = request.form.get("tenant_id", "").strip()
            new_customer_name = request.form.get("new_customer_name", "").strip()

            if new_customer_name:
                slug = (
                    _re.sub(r"[^a-z0-9]+", "-", new_customer_name.lower()).strip("-")
                    or "customer"
                )
                base_slug = slug
                counter = 2
                while db.query(Tenant).filter(Tenant.slug == slug).first():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                new_tenant = Tenant(name=new_customer_name, slug=slug)
                db.add(new_tenant)
                db.flush()
                tenant_id = new_tenant.id

            product_profile_id_raw = data.get("product_profile_id", "")
            product_profile_id = (
                int(product_profile_id_raw) if product_profile_id_raw else None
            )

            project = Project(
                name=data["product_name"],
                asin=data.get("asin", ""),
                category=data.get("product_category", ""),
                status="draft",
                customer_brief=json.dumps(data, ensure_ascii=False),
                tenant_id=int(tenant_id) if tenant_id else None,
                product_profile_id=product_profile_id,
            )
            db.add(project)
            db.commit()
            db.refresh(project)

            # 回写产品档案和品牌档案，只更新表单中有值的字段
            if product_profile_id:
                prod = db.get(ProductProfile, product_profile_id)
                if prod:
                    for field in (
                        "product_name",
                        "product_category",
                        "price_point",
                        "key_features",
                        "visual_notes",
                    ):
                        val = data.get(field, "")
                        if val:
                            setattr(prod, field, val)
                    db.commit()
                    # 回写关联品牌档案
                    if prod.brand_profile_id:
                        brand = db.get(BrandProfile, prod.brand_profile_id)
                        if brand:
                            # brand_voice → brand_tone 且同步写回 brand_story
                            if data.get("brand_voice"):
                                brand.brand_tone = data["brand_voice"]
                                brand.brand_story = data["brand_voice"]
                            # primary_color → color_system
                            if data.get("primary_color"):
                                brand.color_system = data["primary_color"]
                            db.commit()

            upload_dir = os.path.join("uploads", str(project.id))
            brief = json.loads(project.customer_brief or "{}")
            file_fields_updated = False

            white_bg_file = request.files.get("white_bg_file")
            if white_bg_file and white_bg_file.filename:
                os.makedirs(upload_dir, exist_ok=True)
                wb_name = secure_filename(white_bg_file.filename)
                wb_path = os.path.join(upload_dir, wb_name)
                white_bg_file.save(wb_path)
                brief["white_bg_image_path"] = wb_path
                file_fields_updated = True

            multiangle_files = request.files.getlist("multiangle_files")
            valid_multiangle = [mf for mf in multiangle_files if mf and mf.filename]
            if len(valid_multiangle) > 10:
                return "多角度图最多上传 10 张", 400
            if valid_multiangle:
                os.makedirs(upload_dir, exist_ok=True)
                multi_paths = []
                for mf in valid_multiangle:
                    from PIL import Image as _PILImage
                    from io import BytesIO as _BytesIO

                    try:
                        _mf_data = mf.read()
                        _PILImage.open(_BytesIO(_mf_data)).verify()
                        mf.seek(0)
                    except Exception:
                        return f"多角度图 {mf.filename} 文件损坏或格式不支持", 400
                    mf_name = secure_filename(mf.filename)
                    mf_path = os.path.join(upload_dir, mf_name)
                    mf.save(mf_path)
                    multi_paths.append(mf_path)
                if multi_paths:
                    brief["multiangle_image_paths"] = ",".join(multi_paths)
                    file_fields_updated = True

            _single_extra = {
                "packaging_file": "packaging_image_path",
                "inbox_flatlay_file": "inbox_flatlay_image_path",
                "scale_ref_file": "scale_ref_image_path",
            }
            for _field, _key in _single_extra.items():
                _f = request.files.get(_field)
                if _f and _f.filename:
                    os.makedirs(upload_dir, exist_ok=True)
                    try:
                        from PIL import Image as _PILImage
                        from io import BytesIO as _BytesIO

                        _d = _f.read()
                        _PILImage.open(_BytesIO(_d)).verify()
                        _f.seek(0)
                    except Exception:
                        return f"{_key} 文件损坏或格式不支持，请重新上传", 400
                    _fname = secure_filename(_f.filename)
                    _fpath = os.path.join(upload_dir, _fname)
                    _f.save(_fpath)
                    brief[_key] = _fpath
                    file_fields_updated = True

            _multi_extra = {
                "detail_closeup_files": "detail_closeup_image_paths",
                "usage_context_files": "usage_context_image_paths",
                "color_variant_files": "color_variant_image_paths",
            }
            for _field, _key in _multi_extra.items():
                _files = request.files.getlist(_field)
                _valid = [_fi for _fi in _files if _fi and _fi.filename]
                if _valid:
                    os.makedirs(upload_dir, exist_ok=True)
                    from PIL import Image as _PILImage
                    from io import BytesIO as _BytesIO

                    _paths = []
                    for _fi in _valid:
                        try:
                            _d = _fi.read()
                            _PILImage.open(_BytesIO(_d)).verify()
                            _fi.seek(0)
                        except Exception:
                            return f"{_fi.filename} 文件损坏或格式不支持", 400
                        _fname = secure_filename(_fi.filename)
                        _fpath = os.path.join(upload_dir, _fname)
                        _fi.save(_fpath)
                        _paths.append(_fpath)
                    if _paths:
                        brief[_key] = ",".join(_paths)
                        file_fields_updated = True

            from pipeline.layers.project_constraints import enrich_customer_brief

            brief = enrich_customer_brief(brief)
            project.customer_brief = json.dumps(brief, ensure_ascii=False)
            db.commit()

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

            tenant_info = None
            brand_info = None
            if project.tenant_id:
                t = db.get(Tenant, project.tenant_id)
                if t:
                    tenant_info = {"id": t.id, "name": t.name}
            if project.product_profile_id:
                from pipeline.models.product_profile import ProductProfile

                pp = db.get(ProductProfile, project.product_profile_id)
                if pp and pp.brand_profile_id:
                    bp = db.get(BrandProfile, pp.brand_profile_id)
                    if bp:
                        brand_info = {"id": bp.id, "name": bp.name}

            return render_template(
                "customer_input.html",
                step_data=step_data,
                project_id=project_id,
                amazon_categories=AMAZON_CATEGORIES,
                amazon_category_tree=json.dumps(
                    AMAZON_CATEGORY_TREE, ensure_ascii=False
                ),
                tenant_info=tenant_info,
                brand_info=brand_info,
                product_profile_id=project.product_profile_id,
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

            if not data.get("white_bg_image_path"):
                return (
                    "Missing required field: white_bg_image_path (产品白底图为必填项)",
                    400,
                )

            project.name = data["product_name"]
            project.asin = data.get("asin", "")
            project.category = data.get("product_category", "")
            from pipeline.layers.project_constraints import enrich_customer_brief

            data = enrich_customer_brief(data)
            project.customer_brief = json.dumps(data, ensure_ascii=False)
            db.commit()

            # 回写产品档案和品牌档案
            product_profile_id_raw = data.get("product_profile_id", "")
            product_profile_id = (
                int(product_profile_id_raw) if product_profile_id_raw else None
            )
            if product_profile_id:
                prod = db.get(ProductProfile, product_profile_id)
                if prod:
                    for field in (
                        "product_name",
                        "product_category",
                        "price_point",
                        "key_features",
                        "visual_notes",
                    ):
                        val = data.get(field, "")
                        if val:
                            setattr(prod, field, val)
                    db.commit()
                    if prod.brand_profile_id:
                        brand = db.get(BrandProfile, prod.brand_profile_id)
                        if brand:
                            if data.get("brand_voice"):
                                brand.brand_tone = data["brand_voice"]
                                brand.brand_story = data["brand_voice"]
                            if data.get("primary_color"):
                                brand.color_system = data["primary_color"]
                            db.commit()

            return redirect(url_for("project_detail", project_id=project.id))
        finally:
            db.close()

    @app.route("/input/<int:project_id>/save", methods=["POST"])
    def customer_input_save(project_id):
        db = get_session()
        try:
            project = db.get(Project, project_id)
            if project is None:
                return jsonify({"ok": False, "error": "Project not found"}), 404
            existing = {}
            if project.customer_brief:
                try:
                    existing = json.loads(project.customer_brief)
                except Exception:
                    existing = {}
            incoming = {k: request.form.get(k, "").strip() for k in CUSTOMER_INPUT_ALL}
            existing.update({k: v for k, v in incoming.items() if v != ""})
            if project.customer_brief is None:
                for k, v in incoming.items():
                    existing[k] = v
            if existing.get("product_name"):
                project.name = existing["product_name"]
            if existing.get("asin"):
                project.asin = existing["asin"]
            if existing.get("product_category"):
                cat_val = existing["product_category"].strip()
                if cat_val.isdigit():
                    project.category = cat_val
            tenant_id_raw = request.form.get("tenant_id", "").strip()
            if tenant_id_raw:
                project.tenant_id = int(tenant_id_raw)
            product_profile_id_raw = request.form.get("product_profile_id", "").strip()
            if product_profile_id_raw:
                project.product_profile_id = int(product_profile_id_raw)
            from pipeline.layers.project_constraints import enrich_customer_brief

            existing = enrich_customer_brief(existing)
            project.customer_brief = json.dumps(existing, ensure_ascii=False)
            db.commit()
            return jsonify({"ok": True})
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
            from pipeline.models.brand_profile import BrandProfile as BP
            from pipeline.models.product_profile import ProductProfile

            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404

            pp = db.query(ProductProfile).filter_by(project_id=project_id).first()
            bp = None
            if pp and pp.brand_profile_id:
                bp = db.query(BP).filter_by(id=pp.brand_profile_id).first()
            if bp is None:
                bp = BP()

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
            from pipeline.models.product_profile import ProductProfile

            bp_obj = None
            pp = db.query(ProductProfile).filter_by(project_id=project_id).first()
            if pp and pp.brand_profile_id:
                bp_obj = db.query(BP).filter_by(id=pp.brand_profile_id).first()
            if bp_obj is None:
                bp_obj = BP()
                db.add(bp_obj)
                db.flush()
                if pp is None:
                    pp = ProductProfile(
                        project_id=project_id, brand_profile_id=bp_obj.id, tenant_id=1
                    )
                    db.add(pp)
                else:
                    pp.brand_profile_id = bp_obj.id
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
            first_tenant = db.query(Tenant).order_by(Tenant.id).first()
            cp = CustomerProfile(
                tenant_id=data.get("tenant_id")
                or (first_tenant.id if first_tenant else None),
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
                tenant_id=customer.tenant_id,
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
                    tenant_id=project.tenant_id,
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

    # --- P2: 四级层级 REST API ---

    @app.route("/api/tenants", methods=["GET", "POST"])
    def api_tenants():
        db = get_session()
        try:
            if request.method == "GET":
                rows = db.query(Tenant).order_by(Tenant.id).all()
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "name": r.name,
                            "slug": r.slug,
                            "status": r.status,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            if not data.get("name"):
                return jsonify({"error": "name is required"}), 400
            t = Tenant(
                name=data["name"],
                slug=data.get("slug", data["name"].lower().replace(" ", "-")),
                status=data.get("status", "active"),
            )
            db.add(t)
            db.commit()
            db.refresh(t)
            return jsonify({"id": t.id, "name": t.name}), 201
        finally:
            db.close()

    @app.route("/api/tenants/<int:tenant_id>", methods=["GET", "PUT", "DELETE"])
    def api_tenant_detail(tenant_id):
        db = get_session()
        try:
            t = db.query(Tenant).filter_by(id=tenant_id).first()
            if t is None:
                return jsonify({"error": "Tenant not found"}), 404
            if request.method == "GET":
                return jsonify(
                    {"id": t.id, "name": t.name, "slug": t.slug, "status": t.status}
                )
            if request.method == "DELETE":
                db.delete(t)
                db.commit()
                return jsonify({"ok": True})
            data = request.get_json(force=True)
            for field in ("name", "slug", "status"):
                if field in data:
                    setattr(t, field, data[field])
            db.commit()
            db.refresh(t)
            return jsonify({"id": t.id, "name": t.name})
        finally:
            db.close()

    @app.route("/api/tenants/<int:tenant_id>/brands", methods=["GET", "POST"])
    def api_tenant_brands(tenant_id):
        db = get_session()
        try:
            t = db.query(Tenant).filter_by(id=tenant_id).first()
            if t is None:
                return jsonify({"error": "Tenant not found"}), 404
            if request.method == "GET":
                rows = db.query(BrandProfile).filter_by(tenant_id=tenant_id).all()
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "label": r.name or r.brand_tone or f"品牌#{r.id}",
                            "name": r.name,
                            "brand_tone": r.brand_tone,
                            "color_system": r.color_system,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            bp = BrandProfile(
                tenant_id=tenant_id,
                project_id=data.get("project_id"),
                brand_tone=data.get("brand_tone"),
                color_system=data.get("color_system"),
            )
            db.add(bp)
            db.commit()
            db.refresh(bp)
            return jsonify({"id": bp.id, "tenant_id": tenant_id}), 201
        finally:
            db.close()

    @app.route("/api/brands/<int:brand_id>", methods=["GET", "PUT", "DELETE"])
    def api_brand_detail(brand_id):
        db = get_session()
        try:
            bp = db.query(BrandProfile).filter_by(id=brand_id).first()
            if bp is None:
                return jsonify({"error": "Brand not found"}), 404
            # 验证 tenant_id：若请求携带 ?tenant_id= 则校验归属，防止跨 tenant 访问
            req_tid = request.args.get("tenant_id", type=int)
            if req_tid is not None and bp.tenant_id != req_tid:
                return jsonify({"error": "Forbidden"}), 403
            if request.method == "GET":
                return jsonify(
                    {
                        "id": bp.id,
                        "tenant_id": bp.tenant_id,
                        "name": bp.name,
                        "brand_tone": bp.brand_tone,
                        "color_system": bp.color_system,
                        "font_preference": bp.font_preference,
                        "photo_style": bp.photo_style,
                        "model_type": bp.model_type,
                        "scene_preference": bp.scene_preference,
                        "composition_preference": bp.composition_preference,
                        "material_texture": bp.material_texture,
                        "competitor_positioning": bp.competitor_positioning,
                        "brand_story": bp.brand_story,
                        "messaging_pillars": bp.messaging_pillars,
                        "guidelines": bp.guidelines,
                    }
                )
            if request.method == "DELETE":
                db.delete(bp)
                db.commit()
                return jsonify({"ok": True})
            data = request.get_json(force=True)
            for field in (
                "brand_tone",
                "color_system",
                "font_preference",
                "photo_style",
                "model_type",
                "scene_preference",
                "composition_preference",
                "material_texture",
                "competitor_positioning",
                "brand_story",
                "messaging_pillars",
                "guidelines",
                "project_id",
            ):
                if field in data:
                    setattr(bp, field, data[field])
            db.commit()
            db.refresh(bp)
            return jsonify({"id": bp.id})
        finally:
            db.close()

    @app.route("/api/brands/<int:brand_id>/products", methods=["GET", "POST"])
    def api_brand_products(brand_id):
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            bp = db.query(BrandProfile).filter_by(id=brand_id).first()
            if bp is None:
                return jsonify({"error": "Brand not found"}), 404
            # 验证 tenant_id：防止跨 tenant 访问
            req_tid = request.args.get("tenant_id", type=int)
            if req_tid is not None and bp.tenant_id != req_tid:
                return jsonify({"error": "Forbidden"}), 403
            if request.method == "GET":
                rows = (
                    db.query(ProductProfile).filter_by(brand_profile_id=brand_id).all()
                )
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "product_name": r.product_name,
                            "product_category": r.product_category,
                            "price_point": r.price_point,
                            "key_features": r.key_features,
                            "visual_notes": r.visual_notes,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            pp = ProductProfile(
                brand_profile_id=brand_id,
                tenant_id=bp.tenant_id,
                product_name=data.get("product_name"),
                product_category=data.get("product_category"),
                price_point=data.get("price_point"),
                key_features=data.get("key_features"),
                visual_notes=data.get("visual_notes"),
            )
            db.add(pp)
            db.commit()
            db.refresh(pp)
            return jsonify({"id": pp.id, "brand_profile_id": brand_id}), 201
        finally:
            db.close()

    @app.route("/api/products/<int:product_id>", methods=["GET", "PUT", "DELETE"])
    def api_product_detail(product_id):
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            pp = db.query(ProductProfile).filter_by(id=product_id).first()
            if pp is None:
                return jsonify({"error": "Product not found"}), 404
            # 验证 tenant_id：防止跨 tenant 访问
            req_tid = request.args.get("tenant_id", type=int)
            if req_tid is not None and pp.tenant_id != req_tid:
                return jsonify({"error": "Forbidden"}), 403
            if request.method == "GET":
                return jsonify(
                    {
                        "id": pp.id,
                        "brand_profile_id": pp.brand_profile_id,
                        "product_name": pp.product_name,
                        "product_category": pp.product_category,
                        "price_point": pp.price_point,
                        "key_features": pp.key_features,
                        "visual_notes": pp.visual_notes,
                    }
                )
            if request.method == "DELETE":
                db.delete(pp)
                db.commit()
                return jsonify({"ok": True})
            data = request.get_json(force=True)
            for field in (
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
            return jsonify({"id": pp.id})
        finally:
            db.close()

    @app.route("/api/products/<int:product_id>/projects", methods=["GET", "POST"])
    def api_product_projects(product_id):
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            pp = db.query(ProductProfile).filter_by(id=product_id).first()
            if pp is None:
                return jsonify({"error": "Product not found"}), 404
            # 验证 tenant_id：防止跨 tenant 访问
            req_tid = request.args.get("tenant_id", type=int)
            if req_tid is not None and pp.tenant_id != req_tid:
                return jsonify({"error": "Forbidden"}), 403
            if request.method == "GET":
                rows = db.query(Project).filter_by(product_profile_id=product_id).all()
                return jsonify(
                    [
                        {
                            "id": r.id,
                            "name": r.name,
                            "status": r.status,
                            "asin": r.asin,
                        }
                        for r in rows
                    ]
                )
            data = request.get_json(force=True)
            if not data.get("name"):
                return jsonify({"error": "name is required"}), 400
            proj = Project(
                name=data["name"],
                asin=data.get("asin"),
                category=data.get("category"),
                notes=data.get("notes"),
                tenant_id=pp.tenant_id,
                product_profile_id=product_id,
            )
            db.add(proj)
            db.commit()
            db.refresh(proj)
            return jsonify({"id": proj.id, "product_profile_id": product_id}), 201
        finally:
            db.close()

    @app.route("/project/<int:project_id>/aplus/generate", methods=["POST"])
    def project_aplus_generate(project_id):
        from pipeline.orchestrator import step_aplus, step_generate_aplus_images

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
        finally:
            db.close()

        try:
            modules = step_aplus(project_id)
            step_generate_aplus_images(project_id)
            return jsonify({"status": "ok", "module_count": len(modules)})
        except Exception as exc:
            logger.error("A+ generate failed for project=%s: %s", project_id, exc)
            return jsonify({"error": str(exc)}), 500

    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/regenerate",
        methods=["POST"],
    )
    def project_aplus_regenerate_one(project_id: int, module_id: int):
        from pipeline.layers.aplus_image_generator import (
            regenerate_single_aplus_image,
        )

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id,
                    project_id=project_id,
                    tenant_id=project.tenant_id,
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404
            try:
                result = regenerate_single_aplus_image(module_id, session=db)
                if result is None:
                    return jsonify({"error": "Module disappeared"}), 404
                # 生成后 image_path 仍为空，说明无法自动生成（如 slot_index 未设置或无可复用图）
                if not result.image_path:
                    return jsonify(
                        {
                            "error": f"未能生成图片（{result.module_type}：slot_index 未设置或无可复用图片）",
                        }
                    )
                return jsonify(
                    {
                        "status": "ok",
                        "module_id": result.id,
                        "module_type": result.module_type,
                        "image_path": result.image_path,
                        "image_size": result.image_size,
                        "qa_score": result.qa_score,
                        "qa_passed": result.qa_passed,
                    }
                )
            except Exception as exc:
                logger.error(
                    "A+ regenerate failed project=%s module=%s: %s",
                    project_id,
                    module_id,
                    exc,
                )
                return jsonify({"error": str(exc)}), 500
        finally:
            db.close()

    # ── 人工检测：编辑 Prompt ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/edit-prompt",
        methods=["POST"],
    )
    def project_aplus_edit_prompt(project_id: int, module_id: int):
        """保存用户手动编辑的 custom_prompt"""
        import json as _json

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id, project_id=project_id, tenant_id=project.tenant_id
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404
            data = request.get_json(silent=True) or {}
            custom_prompt = (data.get("custom_prompt") or "").strip()
            module.custom_prompt = custom_prompt or None
            db.commit()
            return jsonify({"status": "ok", "custom_prompt": module.custom_prompt})
        finally:
            db.close()

    # ── 人工检测：上传参考图 ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/reference-image",
        methods=["POST"],
    )
    def project_aplus_upload_ref(project_id: int, module_id: int):
        """上传参考图（最多 2 张），存于 uploads/<project_id>/aplus_<module_id>/"""
        import os

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id, project_id=project_id, tenant_id=project.tenant_id
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404

            existing = [p for p in (module.reference_image_paths or "").split(",") if p]
            if len(existing) >= 2:
                return jsonify({"error": "最多上传 2 张参考图"}), 400

            file = request.files.get("file")
            if file is None or file.filename == "":
                return jsonify({"error": "No file uploaded"}), 400

            save_dir = os.path.join("uploads", str(project_id), f"aplus_{module_id}")
            os.makedirs(save_dir, exist_ok=True)
            filename = f"ref_{len(existing)}_{file.filename}"
            save_path = os.path.join(save_dir, filename)
            file.save(save_path)

            existing.append(save_path)
            module.reference_image_paths = ",".join(existing)
            db.commit()
            return jsonify({"status": "ok", "paths": existing})
        finally:
            db.close()

    # ── 人工检测：删除参考图 ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/reference-image/delete",
        methods=["POST"],
    )
    def project_aplus_delete_ref(project_id: int, module_id: int):
        """删除指定参考图（按路径）"""
        import os

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id, project_id=project_id, tenant_id=project.tenant_id
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404

            data = request.get_json(silent=True) or {}
            target = (data.get("path") or "").strip()
            existing = [p for p in (module.reference_image_paths or "").split(",") if p]
            if target not in existing:
                return jsonify({"error": "Path not found"}), 404

            existing.remove(target)
            module.reference_image_paths = ",".join(existing) or None
            db.commit()

            try:
                if os.path.exists(target):
                    os.remove(target)
            except OSError:
                pass

            return jsonify({"status": "ok", "paths": existing})
        finally:
            db.close()

    # ── T8: A+ Approve ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/approve",
        methods=["POST"],
    )
    def project_aplus_approve(project_id: int, module_id: int):
        """人工确认通过指定 A+ 模块"""
        from datetime import datetime, UTC

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id,
                    project_id=project_id,
                    tenant_id=project.tenant_id,
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404
            # 写入确认状态
            module.approved = True
            module.approved_at = datetime.now(UTC)
            module.rejected = False
            db.commit()
            return jsonify({"status": "ok", "approved": True})
        finally:
            db.close()

    # ── T8: A+ Reject ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/reject",
        methods=["POST"],
    )
    def project_aplus_reject(project_id: int, module_id: int):
        """人工拒绝指定 A+ 模块"""
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id,
                    project_id=project_id,
                    tenant_id=project.tenant_id,
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404
            # 写入拒绝状态，清除 approved_at
            module.rejected = True
            module.approved = False
            module.approved_at = None
            db.commit()
            return jsonify({"status": "ok", "rejected": True})
        finally:
            db.close()

    # ── T7: A+ 人工评分 ──
    @app.route(
        "/project/<int:project_id>/aplus/<int:module_id>/score",
        methods=["POST"],
    )
    def project_aplus_score(project_id: int, module_id: int):
        from pipeline.models.human_aplus_score import HumanAPlusScore
        from sqlalchemy import func

        data = request.get_json(silent=True) or {}
        comment_val = data.get("comment", "")

        legacy_score = data.get("score")
        scores_dict = data.get("scores")
        overall_score_val = data.get("overall_score")

        if scores_dict and isinstance(scores_dict, dict):

            def _clamp(v):
                try:
                    v = float(v)
                    return max(1.0, min(5.0, v))
                except (TypeError, ValueError):
                    return None

            score_image_quality = _clamp(scores_dict.get("image_quality"))
            score_copy_quality = _clamp(scores_dict.get("copy_quality"))
            score_layout = _clamp(scores_dict.get("layout"))
            score_brand_fit = _clamp(scores_dict.get("brand_fit"))
            score_conversion = _clamp(scores_dict.get("conversion"))
            if overall_score_val is not None:
                try:
                    overall_score_val = max(1.0, min(5.0, float(overall_score_val)))
                except (TypeError, ValueError):
                    overall_score_val = None
            use_new_format = True
        elif isinstance(legacy_score, int) and 1 <= legacy_score <= 5:
            score_image_quality = score_copy_quality = score_layout = (
                score_brand_fit
            ) = score_conversion = None
            overall_score_val = None
            use_new_format = False
        else:
            return jsonify(
                {"error": "请提供 scores 对象（5维度）或 score 整数（1-5）"}
            ), 400

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            module = (
                db.query(APlusContent)
                .filter_by(
                    id=module_id,
                    project_id=project_id,
                    tenant_id=project.tenant_id,
                )
                .first()
            )
            if module is None:
                return jsonify({"error": "Module not found"}), 404

            existing = (
                db.query(HumanAPlusScore)
                .filter_by(module_id=module_id)
                .order_by(HumanAPlusScore.id.desc())
                .first()
            )
            if existing:
                if use_new_format:
                    if score_image_quality is not None:
                        existing.score_image_quality = score_image_quality
                    if score_copy_quality is not None:
                        existing.score_copy_quality = score_copy_quality
                    if score_layout is not None:
                        existing.score_layout = score_layout
                    if score_brand_fit is not None:
                        existing.score_brand_fit = score_brand_fit
                    if score_conversion is not None:
                        existing.score_conversion = score_conversion
                    if overall_score_val is not None:
                        existing.overall_score = overall_score_val
                else:
                    existing.score = legacy_score
                if comment_val:
                    existing.comment = comment_val
            else:
                kwargs = dict(
                    project_id=project_id,
                    module_id=module_id,
                    comment=comment_val or None,
                )
                if use_new_format:
                    # score 字段 nullable=False，用 overall_score 四舍五入填充，确保满足 CHECK 约束
                    _score_int = (
                        max(1, min(5, round(overall_score_val)))
                        if overall_score_val is not None
                        else 3
                    )
                    kwargs.update(
                        score=_score_int,
                        score_image_quality=score_image_quality,
                        score_copy_quality=score_copy_quality,
                        score_layout=score_layout,
                        score_brand_fit=score_brand_fit,
                        score_conversion=score_conversion,
                        overall_score=overall_score_val,
                    )
                else:
                    kwargs["score"] = legacy_score
                db.add(HumanAPlusScore(**kwargs))
            db.commit()

            avg_overall = (
                db.query(func.avg(HumanAPlusScore.overall_score))
                .filter_by(module_id=module_id)
                .filter(HumanAPlusScore.overall_score.isnot(None))
                .scalar()
            )
            if avg_overall is None:
                avg_overall = (
                    db.query(func.avg(HumanAPlusScore.score))
                    .filter_by(module_id=module_id)
                    .scalar()
                )
            return jsonify(
                {
                    "status": "ok",
                    "avg_score": round(float(avg_overall), 1)
                    if avg_overall is not None
                    else None,
                }
            )
        finally:
            db.close()

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

    @app.route("/project/<int:project_id>/runs")
    def project_runs(project_id):
        db = get_session()
        try:
            runs = (
                db.query(PipelineRun)
                .filter_by(project_id=project_id)
                .order_by(PipelineRun.started_at.desc())
                .all()
            )
            return jsonify(
                [
                    {
                        "id": r.id,
                        "status": r.status,
                        "started_at": r.started_at.isoformat()
                        if r.started_at
                        else None,
                        "finished_at": r.finished_at.isoformat()
                        if r.finished_at
                        else None,
                        "error_message": r.error_message,
                    }
                    for r in runs
                ]
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

    @app.route("/knowledge/new", methods=["POST"])
    def knowledge_new():
        db = get_session()
        try:
            from pipeline.layers.knowledge_base import add_entry, VALID_CATEGORIES

            category = request.form.get("category", "").strip()
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            tags = request.form.get("tags", "").strip()
            source_project_id = (
                request.form.get("source_project_id", "").strip() or None
            )
            if source_project_id:
                source_project_id = int(source_project_id)
            if not category or category not in VALID_CATEGORIES:
                flash("请选择有效的分类", "error")
                return redirect(url_for("knowledge"))
            if not title or not content:
                flash("标题和内容不能为空", "error")
                return redirect(url_for("knowledge"))
            tenant_id = getattr(request, "tenant_id", 1)
            add_entry(
                db,
                source_project_id=source_project_id,
                category=category,
                title=title,
                content=content,
                tags=tags,
                tenant_id=tenant_id,
            )
            flash("知识条目已添加", "success")
        finally:
            db.close()
        return redirect(url_for("knowledge"))

    @app.route("/knowledge/<int:entry_id>/delete", methods=["POST"])
    def knowledge_delete(entry_id: int):
        db = get_session()
        try:
            from pipeline.layers.knowledge_base import delete_entry

            tenant_id = getattr(request, "tenant_id", 1)
            ok = delete_entry(db, entry_id=entry_id, tenant_id=tenant_id)
            if ok:
                flash("知识条目已删除", "success")
            else:
                flash("条目不存在或无权限删除", "error")
        finally:
            db.close()
        return redirect(url_for("knowledge"))

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

    _DELIVERY_OUTPUT_DIR = os.path.join("data", "output")

    @app.route("/project/<int:project_id>/deliver")
    def project_deliver(project_id):
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404

            delivery_dir = os.path.join(
                _DELIVERY_OUTPUT_DIR, str(project_id), "delivery"
            )

            manifest_slots = []
            manifest_path = os.path.join(delivery_dir, "manifest.json")
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as _f:
                        _m = json.load(_f)
                    _project_root = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "..")
                    )
                    for _slot in _m.get("slots", []):
                        _ip = _slot.get("image_path") or ""
                        if _ip and os.path.isabs(_ip):
                            try:
                                _slot["image_path"] = os.path.relpath(
                                    _ip, _project_root
                                )
                            except ValueError:
                                pass
                    manifest_slots = _m.get("slots", [])
                except Exception:
                    pass

            from pipeline.layers.version_manager import get_version_history

            versions = get_version_history(db, project_id)

            has_delivery = os.path.isdir(delivery_dir) and bool(
                [f for f in os.listdir(delivery_dir) if f.startswith("slot_")]
            )

            return render_template(
                "deliver.html",
                project=project,
                manifest_slots=manifest_slots,
                versions=versions,
                has_delivery=has_delivery,
                delivery_dir=delivery_dir,
            )
        finally:
            db.close()

    @app.route("/project/<int:project_id>/deliver/build", methods=["POST"])
    def project_deliver_build(project_id):
        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return jsonify({"error": "Project not found"}), 404
            from pipeline.layers.delivery import build_delivery_package

            delivery_dir = build_delivery_package(
                project_id, session=db, output_dir=_DELIVERY_OUTPUT_DIR
            )
            return jsonify({"ok": True, "delivery_dir": delivery_dir})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            db.close()

    @app.route("/project/<int:project_id>/deliver/download")
    def project_deliver_download(project_id):
        import tempfile
        import zipfile as _zipfile

        db = get_session()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return "Project not found", 404
            delivery_dir = os.path.join(
                _DELIVERY_OUTPUT_DIR, str(project_id), "delivery"
            )
            if not os.path.isdir(delivery_dir):
                return "交付包尚未生成", 404
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            tmp.close()
            with _zipfile.ZipFile(tmp.name, "w", _zipfile.ZIP_DEFLATED) as zf:
                for fname in sorted(os.listdir(delivery_dir)):
                    fpath = os.path.join(delivery_dir, fname)
                    if os.path.isfile(fpath):
                        zf.write(fpath, fname)
            zip_name = f"delivery_{project_id}.zip"
            return send_file(tmp.name, as_attachment=True, download_name=zip_name)
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
        """新增客户（租户），slug 自动由名称生成。"""
        import re as _re2

        name = (request.form.get("name") or "").strip()
        if not name:
            return "客户名称不能为空", 400
        db = get_session()
        try:
            slug = _re2.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "customer"
            base_slug = slug
            counter = 2
            while db.query(Tenant).filter_by(slug=slug).first():
                slug = f"{base_slug}-{counter}"
                counter += 1
            tenant = Tenant(name=name, slug=slug)
            db.add(tenant)
            db.commit()
            return redirect(url_for("customers_list"))
        finally:
            db.close()

    @app.route("/customers/<int:tenant_id>/edit", methods=["POST"])
    def customers_edit(tenant_id):
        """编辑客户名称。"""
        name = (request.form.get("name") or "").strip()
        if not name:
            return "客户名称不能为空", 400
        db = get_session()
        try:
            tenant = db.get(Tenant, tenant_id)
            if not tenant:
                return "客户不存在", 404
            tenant.name = name
            db.commit()
            return redirect(url_for("customers_list"))
        finally:
            db.close()

    @app.route("/customers/<int:tenant_id>/delete", methods=["POST"])
    def customers_delete(tenant_id):
        db = get_session()
        try:
            count = db.query(Project).filter_by(tenant_id=tenant_id).count()
            if count > 0:
                return f"该客户下有 {count} 个项目，无法删除", 400
            tenant = db.get(Tenant, tenant_id)
            if not tenant:
                return "客户不存在", 404
            db.delete(tenant)
            db.commit()
            return redirect(url_for("customers_list"))
        finally:
            db.close()

    @app.route("/tenants/<int:tenant_id>/brands")
    def brands_list(tenant_id):
        """品牌管理页面，展示指定客户下的所有品牌及其产品数。"""
        from sqlalchemy import func as sa_func
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            tenant = db.get(Tenant, tenant_id)
            if not tenant:
                return "客户不存在", 404
            brands = (
                db.query(BrandProfile)
                .filter_by(tenant_id=tenant_id)
                .order_by(BrandProfile.id.asc())
                .all()
            )
            product_counts = (
                dict(
                    db.query(
                        ProductProfile.brand_profile_id,
                        sa_func.count(ProductProfile.id),
                    )
                    .filter(ProductProfile.brand_profile_id.in_([b.id for b in brands]))
                    .group_by(ProductProfile.brand_profile_id)
                    .all()
                )
                if brands
                else {}
            )
            return render_template(
                "brands.html",
                tenant=tenant,
                brands=brands,
                product_counts=product_counts,
            )
        finally:
            db.close()

    @app.route("/tenants/<int:tenant_id>/brands/new", methods=["POST"])
    def brands_new(tenant_id):
        """新增品牌，归属指定客户。"""
        db = get_session()
        try:
            tenant = db.get(Tenant, tenant_id)
            if not tenant:
                return "客户不存在", 404
            brand_tone = (request.form.get("brand_tone") or "").strip()
            name = (request.form.get("name") or "").strip() or None
            if not brand_tone and not name:
                return "品牌名称不能为空", 400
            bp = BrandProfile(
                tenant_id=tenant_id,
                name=name,
                brand_tone=brand_tone,
                color_system=(request.form.get("color_system") or "").strip() or None,
                font_preference=(request.form.get("font_preference") or "").strip()
                or None,
                photo_style=(request.form.get("photo_style") or "").strip() or None,
                model_type=(request.form.get("model_type") or "").strip() or None,
                scene_preference=(request.form.get("scene_preference") or "").strip()
                or None,
                composition_preference=(
                    request.form.get("composition_preference") or ""
                ).strip()
                or None,
                material_texture=(request.form.get("material_texture") or "").strip()
                or None,
                competitor_positioning=(
                    request.form.get("competitor_positioning") or ""
                ).strip()
                or None,
                brand_story=(request.form.get("brand_story") or "").strip() or None,
                messaging_pillars=(request.form.get("messaging_pillars") or "").strip()
                or None,
                guidelines=(request.form.get("guidelines") or "").strip() or None,
            )
            db.add(bp)
            db.commit()
            return redirect(url_for("brands_list", tenant_id=tenant_id))
        finally:
            db.close()

    @app.route("/tenants/<int:tenant_id>/brands/<int:brand_id>/edit", methods=["POST"])
    def brands_edit(tenant_id, brand_id):
        """编辑品牌信息。"""
        db = get_session()
        try:
            bp = (
                db.query(BrandProfile)
                .filter_by(id=brand_id, tenant_id=tenant_id)
                .first()
            )
            if not bp:
                return "品牌不存在", 404
            brand_tone = (request.form.get("brand_tone") or "").strip()
            if not brand_tone:
                return "品牌基调不能为空", 400
            fields = [
                "name",
                "brand_tone",
                "color_system",
                "font_preference",
                "photo_style",
                "model_type",
                "scene_preference",
                "composition_preference",
                "material_texture",
                "competitor_positioning",
                "brand_story",
                "messaging_pillars",
                "guidelines",
            ]
            for field in fields:
                val = (request.form.get(field) or "").strip() or None
                setattr(bp, field, val)
            db.commit()
            return redirect(url_for("brands_list", tenant_id=tenant_id))
        finally:
            db.close()

    @app.route(
        "/tenants/<int:tenant_id>/brands/<int:brand_id>/delete", methods=["POST"]
    )
    def brands_delete(tenant_id, brand_id):
        """删除品牌，若品牌下有产品则拒绝。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            count = (
                db.query(ProductProfile).filter_by(brand_profile_id=brand_id).count()
            )
            if count > 0:
                return f"该品牌下有 {count} 个产品档案，无法删除", 400
            bp = (
                db.query(BrandProfile)
                .filter_by(id=brand_id, tenant_id=tenant_id)
                .first()
            )
            if not bp:
                return "品牌不存在", 404
            db.delete(bp)
            db.commit()
            return redirect(url_for("brands_list", tenant_id=tenant_id))
        finally:
            db.close()

    @app.route("/brands/<int:brand_id>/products")
    def products_list(brand_id):
        """产品档案管理页面，展示指定品牌下的所有产品。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            bp = db.query(BrandProfile).filter_by(id=brand_id).first()
            if not bp:
                return "品牌不存在", 404
            tenant = db.get(Tenant, bp.tenant_id)
            products = (
                db.query(ProductProfile)
                .filter_by(brand_profile_id=brand_id)
                .order_by(ProductProfile.id.asc())
                .all()
            )
            return render_template(
                "products.html", brand=bp, tenant=tenant, products=products
            )
        finally:
            db.close()

    @app.route("/brands/<int:brand_id>/products/new", methods=["POST"])
    def products_new(brand_id):
        """新增产品档案，归属指定品牌。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            bp = db.query(BrandProfile).filter_by(id=brand_id).first()
            if not bp:
                return "品牌不存在", 404
            product_name = (request.form.get("product_name") or "").strip()
            product_category = (request.form.get("product_category") or "").strip()
            if not product_name:
                return "产品名称不能为空", 400
            if not product_category:
                return "产品品类不能为空", 400
            pp = ProductProfile(
                brand_profile_id=brand_id,
                tenant_id=bp.tenant_id,
                product_name=product_name,
                product_category=product_category,
                price_point=(request.form.get("price_point") or "").strip() or None,
                key_features=(request.form.get("key_features") or "").strip() or None,
                visual_notes=(request.form.get("visual_notes") or "").strip() or None,
            )
            db.add(pp)
            db.commit()
            return redirect(url_for("products_list", brand_id=brand_id))
        finally:
            db.close()

    @app.route(
        "/brands/<int:brand_id>/products/<int:product_id>/edit", methods=["POST"]
    )
    def products_edit(brand_id, product_id):
        """编辑产品档案。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            pp = (
                db.query(ProductProfile)
                .filter_by(id=product_id, brand_profile_id=brand_id)
                .first()
            )
            if not pp:
                return "产品不存在", 404
            product_name = (request.form.get("product_name") or "").strip()
            product_category = (request.form.get("product_category") or "").strip()
            if not product_name:
                return "产品名称不能为空", 400
            if not product_category:
                return "产品品类不能为空", 400
            pp.product_name = product_name
            pp.product_category = product_category
            pp.price_point = (request.form.get("price_point") or "").strip() or None
            pp.key_features = (request.form.get("key_features") or "").strip() or None
            pp.visual_notes = (request.form.get("visual_notes") or "").strip() or None
            db.commit()
            return redirect(url_for("products_list", brand_id=brand_id))
        finally:
            db.close()

    @app.route(
        "/brands/<int:brand_id>/products/<int:product_id>/delete", methods=["POST"]
    )
    def products_delete(brand_id, product_id):
        """删除产品档案，若产品已关联项目则拒绝。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            count = db.query(Project).filter_by(product_profile_id=product_id).count()
            if count > 0:
                return f"该产品下有 {count} 个项目，无法删除", 400
            pp = (
                db.query(ProductProfile)
                .filter_by(id=product_id, brand_profile_id=brand_id)
                .first()
            )
            if not pp:
                return "产品不存在", 404
            db.delete(pp)
            db.commit()
            return redirect(url_for("products_list", brand_id=brand_id))
        finally:
            db.close()

    @app.route("/project/<int:project_id>/delete", methods=["POST"])
    def project_delete(project_id):
        from sqlalchemy.exc import IntegrityError

        db = get_session()
        try:
            has_assets = (
                db.query(PromptAsset).filter_by(project_id=project_id).count() > 0
                or db.query(SlotPlan).filter_by(project_id=project_id).count() > 0
            )
            if has_assets:
                return "该项目已有生成资产，无法删除", 400
            project = db.get(Project, project_id)
            if not project:
                return "项目不存在", 404
            db.delete(project)
            db.commit()
            return redirect(url_for("index"))
        except IntegrityError:
            db.rollback()
            return "该项目存在关联数据（如竞品、需求等），请先清除关联数据后再删除", 400
        finally:
            db.close()

    @app.route("/brands")
    def brands_all():
        """所有客户的品牌汇总页（含完整字段，支持内嵌 CRUD）。"""
        from sqlalchemy import func
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            rows = (
                db.query(BrandProfile, Tenant)
                .join(Tenant, BrandProfile.tenant_id == Tenant.id)
                .order_by(Tenant.name, BrandProfile.id)
                .all()
            )
            brand_ids = [bp.id for bp, _ in rows]
            product_counts = {}
            if brand_ids:
                counts = (
                    db.query(
                        ProductProfile.brand_profile_id,
                        func.count(ProductProfile.id),
                    )
                    .filter(ProductProfile.brand_profile_id.in_(brand_ids))
                    .group_by(ProductProfile.brand_profile_id)
                    .all()
                )
                product_counts = {bid: cnt for bid, cnt in counts}
            brands = [
                {
                    "id": bp.id,
                    "name": bp.name,
                    "brand_tone": bp.brand_tone,
                    "color_system": bp.color_system,
                    "font_preference": bp.font_preference,
                    "photo_style": bp.photo_style,
                    "model_type": bp.model_type,
                    "scene_preference": bp.scene_preference,
                    "composition_preference": bp.composition_preference,
                    "material_texture": bp.material_texture,
                    "competitor_positioning": bp.competitor_positioning,
                    "brand_story": bp.brand_story,
                    "messaging_pillars": bp.messaging_pillars,
                    "guidelines": bp.guidelines,
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "product_count": product_counts.get(bp.id, 0),
                }
                for bp, tenant in rows
            ]
            tenants = db.query(Tenant).order_by(Tenant.name).all()
            tenants_list = [{"id": t.id, "name": t.name} for t in tenants]
            return render_template(
                "brands_all.html", brands=brands, tenants=tenants_list
            )
        finally:
            db.close()

    @app.route("/products")
    def products_all():
        """所有品牌的产品汇总页（含完整字段，支持内嵌 CRUD）。"""
        from pipeline.models.product_profile import ProductProfile

        db = get_session()
        try:
            rows = (
                db.query(ProductProfile, BrandProfile, Tenant)
                .join(BrandProfile, ProductProfile.brand_profile_id == BrandProfile.id)
                .join(Tenant, BrandProfile.tenant_id == Tenant.id)
                .order_by(Tenant.name, BrandProfile.id, ProductProfile.id)
                .all()
            )
            products = [
                {
                    "id": pp.id,
                    "name": pp.product_name,
                    "product_category": pp.product_category,
                    "price_point": pp.price_point,
                    "key_features": pp.key_features,
                    "visual_notes": pp.visual_notes,
                    "brand_id": bp.id,
                    "brand_name": bp.name or bp.brand_tone or f"品牌#{bp.id}",
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                }
                for pp, bp, tenant in rows
            ]
            brands_rows = (
                db.query(BrandProfile, Tenant)
                .join(Tenant, BrandProfile.tenant_id == Tenant.id)
                .order_by(Tenant.name, BrandProfile.id)
                .all()
            )
            brands_list = [
                {
                    "id": bp.id,
                    "label": bp.name or bp.brand_tone or f"品牌#{bp.id}",
                    "tenant_name": t.name,
                }
                for bp, t in brands_rows
            ]
            return render_template(
                "products_all.html", products=products, brands=brands_list
            )
        finally:
            db.close()

    return app
