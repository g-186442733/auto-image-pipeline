"""Pipeline orchestrator — runs the full pipeline end-to-end."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline.config import config
from pipeline.models.base import commit_with_retry, get_session, create_all
from pipeline.models.project import Project
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.pipeline_run import PipelineRun
from pipeline.layers.input_layer import create_project
from pipeline.layers.amazon_data import (
    fetch_asin_detail,
    fetch_asins_price_batch,
    fetch_category_top,
    KeepaDataError,
)
from pipeline.layers.vision_analyzer import analyze_competitor_listing
from pipeline.layers.slot_planner import generate_slot_plan
from pipeline.layers.prompt_engine import generate_slot_prompts
from pipeline.layers.qa_gate import run_qa_checks
from pipeline.layers.confidence_routing import ConfidenceRouter

_confidence_router = ConfidenceRouter()


def _route_by_confidence(score: float) -> str:
    return _confidence_router.route(score)


from pipeline.layers.feedback_loop import export_project_report
from pipeline.layers.price_analyzer import analyze_price
from pipeline.layers.promo_analyzer import analyze_promo
from pipeline.adapters.registry import get_adapter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.orchestrator")


def _call_vision(image_url: str) -> dict:
    """
    调用 Vision 分析器，带指数退避重试。
    最多重试 3 次（间隔 2s / 4s / 8s），避免 147ai.com 速率限制导致静默失败。
    """
    from pipeline.layers.vision_analyzer import analyze_image

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return analyze_image(image_url)
        except Exception as exc:
            last_exc = exc
            wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
            logger.warning(
                "Vision API call failed (attempt %d/3) for %s: %s — retrying in %ds",
                attempt + 1,
                image_url[-40:],
                exc,
                wait,
            )
            time.sleep(wait)
    # 三次全部失败，抛出最后一个异常
    raise last_exc  # type: ignore[misc]


def _update_status(project_id: int, status: str) -> None:
    session = get_session()
    try:
        proj = session.get(Project, project_id)
        if proj:
            proj.status = status
            commit_with_retry(session)
    finally:
        session.close()


def _finish_pipeline_run(
    pipeline_run_id: int, status: str, error_message: str | None = None
) -> None:
    from datetime import datetime, timezone

    session = get_session()
    try:
        run = session.get(PipelineRun, pipeline_run_id)
        if run:
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = error_message
            session.commit()
    finally:
        session.close()


def step_init(brief_path: str) -> Project:
    """Load brief JSON and create project. Sets status='initialized'."""
    path = Path(brief_path)
    if not path.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")
    brief = json.loads(path.read_text(encoding="utf-8"))
    create_all()
    project = create_project(brief)
    _update_status(project.id, "initialized")
    logger.info("Project %d created: %s", project.id, project.name)
    return project


def step_analyze(project_id: int, progress_cb=None) -> dict:
    """Fetch Amazon data and analyze competitors. Sets status='analyzed'."""

    def _cb(msg: str):
        if progress_cb:
            progress_cb(msg)

    if not config.keepa_api_key:
        raise RuntimeError("E_CONFIG_001: KEEPA_API_KEY not set")
    if not config.openai_api_key:
        raise RuntimeError("E_CONFIG_002: OPENAI_API_KEY not set")

    parallel = config.parallel_analyze

    session = get_session()
    try:
        proj = session.get(Project, project_id)
        if not proj:
            raise ValueError(f"Project {project_id} not found")

        pipeline_run = PipelineRun(
            project_id=project_id,
            tenant_id=getattr(proj, "tenant_id", None),
            status="running",
        )
        session.add(pipeline_run)
        session.flush()
        pipeline_run_id = pipeline_run.id
        session.commit()
        logger.info(
            "PipelineRun %d created for project %d", pipeline_run_id, project_id
        )

        # --- Phase 1: fetch Amazon data (parallel or sequential) ---
        has_asin = bool(proj.asin and proj.asin.strip())
        asin_detail = None
        category_top = None
        if parallel:
            _cb("⏳ Phase 1 · 正在并行拉取 Keepa 竞品数据 + 品类 Top 榜单...")
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_asin = (
                    pool.submit(fetch_asin_detail, proj.asin) if has_asin else None
                )
                fut_cat = pool.submit(
                    lambda: fetch_category_top(proj.category, top_n=9)
                )
                if fut_asin is not None:
                    try:
                        asin_detail = fut_asin.result()
                    except Exception as e:
                        logger.error(
                            "fetch_asin_detail failed for project %d: %s", project_id, e
                        )
                try:
                    category_top = fut_cat.result()
                except Exception as e:
                    raise RuntimeError(
                        f"E_PIPELINE_001: 竞品数据拉取失败，流程终止。原因: {e}"
                    ) from e
        else:
            _cb("⏳ Phase 1 · 正在拉取 Keepa 竞品数据...")
            if has_asin:
                try:
                    asin_detail = fetch_asin_detail(proj.asin)
                except Exception as e:
                    logger.error(
                        "fetch_asin_detail failed for project %d: %s", project_id, e
                    )
            _cb("⏳ Phase 1 · 正在拉取品类 Top 榜单...")
            try:
                category_top = fetch_category_top(proj.category, top_n=9)
            except Exception as e:
                raise RuntimeError(
                    f"E_PIPELINE_001: 竞品数据拉取失败，流程终止。原因: {e}"
                ) from e
        if not has_asin:
            logger.info(
                "Project %d has no ASIN; skipping ASIN-dependent phases", project_id
            )
        _cb(
            f"✅ Phase 1 完成 · 竞品数据已拉取（品类 Top {len(category_top or [])} 条）"
        )

        # 竞品数据完整性校验 — 0 条则终止流程，不得进入后续分析阶段
        if not category_top:
            raise RuntimeError(
                "E_PIPELINE_002: 品类 Top 竞品数据为空（0 条），流程终止。"
                "请检查 category 字段是否填写正确，或 Keepa API 是否返回异常。"
            )

        # 持久化竞品主 listing（CompetitorListing）— requires ASIN
        if has_asin and asin_detail is not None:
            existing_cl = (
                session.query(CompetitorListing)
                .filter(
                    CompetitorListing.project_id == project_id,
                    CompetitorListing.asin == proj.asin,
                )
                .first()
            )
            if existing_cl:
                existing_cl.title = asin_detail.get("title")
                existing_cl.price = asin_detail.get("price")
                existing_cl.rating = asin_detail.get("rating")
                existing_cl.review_count = asin_detail.get("review_count")
                existing_cl.category_rank = asin_detail.get("bsr_rank")
                existing_cl.bullet_points = asin_detail.get("bullet_points") or ""
                existing_cl.description = asin_detail.get("description") or ""
            else:
                cl = CompetitorListing(
                    project_id=project_id,
                    tenant_id=getattr(proj, "tenant_id", None),
                    asin=proj.asin,
                    title=asin_detail.get("title"),
                    price=asin_detail.get("price"),
                    rating=asin_detail.get("rating"),
                    review_count=asin_detail.get("review_count"),
                    category_rank=asin_detail.get("bsr_rank"),
                    bullet_points=asin_detail.get("bullet_points") or "",
                    description=asin_detail.get("description") or "",
                )
                session.add(cl)
            # 写入品类面包屑路径（来自 Keepa categoryTree）
            if asin_detail.get("category_path"):
                proj.category_path = asin_detail["category_path"]
            session.commit()
            logger.info(
                "Upserted CompetitorListing for project %d asin %s",
                project_id,
                proj.asin,
            )

            if proj.customer_brief:
                try:
                    _cb_json = json.loads(proj.customer_brief)
                    _comp_asins_raw = _cb_json.get("competitor_asins", "")
                    _comp_asins = [
                        a.strip()
                        for a in _comp_asins_raw.replace(",", "\n").splitlines()
                        if a.strip() and a.strip() != proj.asin
                    ]
                    for _ca in _comp_asins[:5]:
                        try:
                            _ca_detail = fetch_asin_detail(_ca)
                            _existing_ca = (
                                session.query(CompetitorListing)
                                .filter(
                                    CompetitorListing.project_id == project_id,
                                    CompetitorListing.asin == _ca,
                                )
                                .first()
                            )
                            if _existing_ca:
                                _existing_ca.title = _ca_detail.get("title")
                                _existing_ca.bullet_points = (
                                    _ca_detail.get("bullet_points") or ""
                                )
                                _existing_ca.description = (
                                    _ca_detail.get("description") or ""
                                )
                            else:
                                session.add(
                                    CompetitorListing(
                                        project_id=project_id,
                                        tenant_id=getattr(proj, "tenant_id", None),
                                        asin=_ca,
                                        title=_ca_detail.get("title"),
                                        price=_ca_detail.get("price"),
                                        rating=_ca_detail.get("rating"),
                                        review_count=_ca_detail.get("review_count"),
                                        category_rank=_ca_detail.get("bsr_rank"),
                                        bullet_points=(
                                            _ca_detail.get("bullet_points") or ""
                                        ),
                                        description=(
                                            _ca_detail.get("description") or ""
                                        ),
                                    )
                                )
                        except Exception as _ce:
                            logger.warning(
                                "fetch competitor asin %s failed: %s", _ca, _ce
                            )
                    session.commit()
                except Exception as _bje:
                    logger.warning("competitor_asins batch failed: %s", _bje)

        # 预初始化变量，防止 try 块失败时未定义
        listing_result = None
        review_clusters = None
        qa_entries = None
        competitor_analysis = None

        if has_asin:
            # --- Phase 2: analyzer trio (parallel or sequential) ---
            _cb(
                "⏳ Phase 2 · 正在并行启动：Listing 分析 / Review 聚类 / Q&A 分析..."
                if parallel
                else "⏳ Phase 2 · 正在分析 Listing..."
            )

            def _run_listing(asin: str, detail: dict):
                from pipeline.layers.listing_analyzer import analyze_listing

                return analyze_listing(asin, detail)

            def _run_reviews(asin: str):
                from pipeline.layers.amazon_data import fetch_reviews
                from pipeline.layers.review_analyzer import analyze_reviews

                reviews = fetch_reviews(asin)
                return analyze_reviews(asin, reviews)

            def _run_qa(asin: str):
                from pipeline.layers.amazon_data import fetch_qa
                from pipeline.layers.qa_analyzer import analyze_qa

                qa_pairs = fetch_qa(asin)
                return analyze_qa(asin, qa_pairs)

            if parallel:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    fut_listing = pool.submit(_run_listing, proj.asin, asin_detail)
                    fut_reviews = pool.submit(_run_reviews, proj.asin)
                    fut_qa = pool.submit(_run_qa, proj.asin)

                    try:
                        listing_result = fut_listing.result()
                        _cb("✅ Phase 2 · Listing 竞品分析完成")
                    except Exception as exc:
                        _cb("❌ Phase 2 · Listing 分析失败，流水线中止")
                        raise RuntimeError(
                            f"E_PIPELINE_P2_LISTING: listing_analyzer failed for project {project_id}: {exc}"
                        ) from exc

                    try:
                        review_clusters = fut_reviews.result()
                        _cb(
                            f"✅ Phase 2 · Review 聚类完成（{len(review_clusters or [])} 个聚类）"
                        )
                    except KeepaDataError as exc:
                        review_clusters = []
                        _cb(f"⚠️ Phase 2 · Review 数据不可用，跳过（{exc}）")
                        logger.warning(
                            "review_analyzer no data for project %d: %s",
                            project_id,
                            exc,
                        )
                    except Exception as exc:
                        _cb("❌ Phase 2 · Review 聚类失败，流水线中止")
                        raise RuntimeError(
                            f"E_PIPELINE_P2_REVIEW: review_analyzer failed for project {project_id}: {exc}"
                        ) from exc

                    try:
                        qa_entries = fut_qa.result()
                        _cb(f"✅ Phase 2 · Q&A 分析完成（{len(qa_entries or [])} 条）")
                    except KeepaDataError as exc:
                        qa_entries = []
                        _cb(f"⚠️ Phase 2 · Q&A 数据不可用，跳过（{exc}）")
                        logger.warning(
                            "qa_analyzer no data for project %d: %s", project_id, exc
                        )
                    except Exception as exc:
                        _cb("❌ Phase 2 · Q&A 分析失败，流水线中止")
                        raise RuntimeError(
                            f"E_PIPELINE_P2_QA: qa_analyzer failed for project {project_id}: {exc}"
                        ) from exc
            else:
                try:
                    listing_result = _run_listing(proj.asin, asin_detail)
                    _cb("✅ Phase 2 · Listing 分析完成")
                except Exception as exc:
                    _cb("❌ Phase 2 · Listing 分析失败，流水线中止")
                    raise RuntimeError(
                        f"E_PIPELINE_P2_LISTING: listing_analyzer failed for project {project_id}: {exc}"
                    ) from exc
                _cb("⏳ Phase 2 · 正在分析 Review...")
                try:
                    review_clusters = _run_reviews(proj.asin)
                    _cb(
                        f"✅ Phase 2 · Review 聚类完成（{len(review_clusters or [])} 个聚类）"
                    )
                except KeepaDataError as exc:
                    review_clusters = []
                    _cb(f"⚠️ Phase 2 · Review 数据不可用，跳过（{exc}）")
                    logger.warning(
                        "review_analyzer no data for project %d: %s", project_id, exc
                    )
                except Exception as exc:
                    _cb("❌ Phase 2 · Review 聚类失败，流水线中止")
                    raise RuntimeError(
                        f"E_PIPELINE_P2_REVIEW: review_analyzer failed for project {project_id}: {exc}"
                    ) from exc
                _cb("⏳ Phase 2 · 正在分析 Q&A...")
                try:
                    qa_entries = _run_qa(proj.asin)
                    _cb(f"✅ Phase 2 · Q&A 分析完成（{len(qa_entries or [])} 条）")
                except KeepaDataError as exc:
                    qa_entries = []
                    _cb(f"⚠️ Phase 2 · Q&A 数据不可用，跳过（{exc}）")
                    logger.warning(
                        "qa_analyzer no data for project %d: %s", project_id, exc
                    )
                except Exception as exc:
                    _cb("❌ Phase 2 · Q&A 分析失败，流水线中止")
                    raise RuntimeError(
                        f"E_PIPELINE_P2_QA: qa_analyzer failed for project {project_id}: {exc}"
                    ) from exc

            # --- DB writes for Phase 2 results (main thread only) ---
            if listing_result is not None:
                listing_result.project_id = project_id
                session.query(CompetitorListing).filter(
                    CompetitorListing.project_id == project_id,
                    CompetitorListing.asin == proj.asin,
                ).delete()
                session.add(listing_result)
                session.commit()
                logger.info("listing_analyzer complete for project %d", project_id)

            if review_clusters is not None:
                from pipeline.models.review_cluster import ReviewCluster

                session.query(ReviewCluster).filter(
                    ReviewCluster.project_id == project_id,
                    ReviewCluster.asin == proj.asin,
                ).delete()
                for rc in review_clusters:
                    rc.project_id = project_id
                    session.add(rc)
                session.commit()
                logger.info("review_analyzer complete for project %d", project_id)

            if qa_entries is not None:
                from pipeline.models.qa_entry import QAEntry

                session.query(QAEntry).filter(
                    QAEntry.project_id == project_id,
                    QAEntry.asin == proj.asin,
                ).delete()
                for qe in qa_entries:
                    qe.project_id = project_id
                    session.add(qe)
                session.commit()
                logger.info("qa_analyzer complete for project %d", project_id)

                # --- Phase 2b: price & promo analyzers ---
                _cb("⏳ Phase 2b · 正在进行价格分析...")
            try:
                from pipeline.models.price_analysis import PriceAnalysis

                session.query(PriceAnalysis).filter(
                    PriceAnalysis.project_id == project_id,
                ).delete()
                _competitor_asins = [
                    bm.competitor_asin
                    for bm in (category_top or [])
                    if bm.competitor_asin
                ]
                _competitor_price_map = (
                    fetch_asins_price_batch(_competitor_asins)
                    if _competitor_asins
                    else {}
                )
                _competitor_prices = list(_competitor_price_map.values())
                pa = analyze_price(proj.asin, asin_detail, _competitor_prices)
                pa.project_id = project_id
                session.add(pa)
                session.commit()
                _cb("✅ Phase 2b · 价格分析完成")
                logger.info("price_analyzer complete for project %d", project_id)
            except Exception as exc:
                _cb("❌ Phase 2b · 价格分析失败，流水线中止")
                raise RuntimeError(
                    f"E_PIPELINE_P2B_PRICE: price_analyzer failed for project {project_id}: {exc}"
                ) from exc

            _cb("⏳ Phase 2b · 正在进行促销分析...")
            try:
                from pipeline.models.promo_analysis import PromoAnalysis

                session.query(PromoAnalysis).filter(
                    PromoAnalysis.project_id == project_id,
                ).delete()
                pra = analyze_promo(proj.asin, asin_detail or {})
                pra.project_id = project_id
                session.add(pra)
                session.commit()
                _cb("✅ Phase 2b · 促销分析完成")
                logger.info("promo_analyzer complete for project %d", project_id)
            except Exception as exc:
                _cb("❌ Phase 2b · 促销分析失败，流水线中止")
                raise RuntimeError(
                    f"E_PIPELINE_P2B_PROMO: promo_analyzer failed for project {project_id}: {exc}"
                ) from exc

        # Persist benchmarks to DB so step_plan() can query them
        _cb("⏳ Phase 3 · 正在持久化品类基准数据...")
        _bm_cols = {c.key for c in AmazonBenchmark.__table__.columns} - {
            "id",
            "created_at",
        }
        _top9_bms = [
            bm
            for bm in (category_top or [])
            if (
                bm.get("slot_index", 0)
                if isinstance(bm, dict)
                else getattr(bm, "slot_index", 0)
            )
            < 9
        ]
        persisted = 0
        for bm in _top9_bms:
            if isinstance(bm, dict):
                filtered = {k: v for k, v in bm.items() if k in _bm_cols}
                filtered["project_id"] = project_id
                filtered["pipeline_run_id"] = pipeline_run_id
                if not filtered.get("competitor_asin"):
                    continue
                values = filtered
            else:
                bm.project_id = project_id
                values = {
                    c.key: getattr(bm, c.key)
                    for c in AmazonBenchmark.__table__.columns
                    if c.key not in ("id", "created_at")
                }
                values["pipeline_run_id"] = pipeline_run_id
            session.execute(pg_insert(AmazonBenchmark).values(**values))
            persisted += 1
        session.commit()
        session.expire_all()  # 清除 ORM identity map，避免 Phase 4 读到 upsert 前的缓存对象
        _cb(f"✅ Phase 3 · 品类基准数据已写入（{persisted} 条 amazon_benchmarks）")
        logger.info("Persisted %d benchmarks for project %d", persisted, project_id)

        # --- Phase 4: Vision analysis (parallel or sequential) ---
        vision_analyzed = 0
        benchmarks = (
            session.query(AmazonBenchmark)
            .filter(
                AmazonBenchmark.project_id == project_id,
                AmazonBenchmark.pipeline_run_id == pipeline_run_id,
            )
            .all()
        )
        bms_with_images = [bm for bm in benchmarks if bm.image_url]
        _cb(f"⏳ Phase 4 · 正在对 {len(bms_with_images)} 张竞品图片进行 Vision 分析...")

        if parallel and bms_with_images:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_to_bm = {
                    pool.submit(_call_vision, bm.image_url): bm
                    for bm in bms_with_images
                }
                for fut in as_completed(fut_to_bm):
                    bm = fut_to_bm[fut]
                    try:
                        result = fut.result()
                        bm.analysis = json.dumps(result)
                        bm.score = result.get("quality_score")
                        vision_analyzed += 1
                        _cb(
                            f"⏳ Phase 4 · Vision 分析进度 {vision_analyzed}/{len(bms_with_images)}..."
                        )
                    except Exception as exc:
                        logger.warning(
                            "Vision analysis failed for benchmark %d: %s", bm.id, exc
                        )
        else:
            for bm in bms_with_images:
                try:
                    result = _call_vision(bm.image_url)
                    bm.analysis = json.dumps(result)
                    bm.score = result.get("quality_score")
                    vision_analyzed += 1
                except Exception as exc:
                    logger.warning(
                        "Vision analysis failed for benchmark %d: %s", bm.id, exc
                    )
        session.commit()
        logger.info(
            "Vision analyzed %d benchmarks for project %d",
            vision_analyzed,
            project_id,
        )
        _cb(f"✅ Phase 4 · Vision 分析完成（{vision_analyzed}/{len(bms_with_images)}）")

        if not bms_with_images:
            raise RuntimeError(
                "E_PIPELINE_003: 竞品图片 Vision 分析未执行（0 张有效图片），流程终止。"
                "请检查竞品数据中 image_url 字段是否已正确写入。"
            )

        _cb("⏳ Phase 4b · 正在生成竞品图位 Brief...")
        try:
            from pipeline.layers.brief_generator import generate_brief
            from pipeline.models.image_brief import ImageBrief
            from pipeline.models.brand_profile import BrandProfile
            from pipeline.models.product_profile import ProductProfile

            cl_for_brief = listing_result
            if cl_for_brief is None:
                cl_for_brief = (
                    session.query(CompetitorListing)
                    .filter(
                        CompetitorListing.project_id == project_id,
                        CompetitorListing.asin == proj.asin,
                    )
                    .first()
                )

            _bp_for_brief = None
            try:
                if proj.product_profile_id:
                    _pp_tmp = (
                        session.query(ProductProfile)
                        .filter_by(id=proj.product_profile_id)
                        .first()
                    )
                    if _pp_tmp and _pp_tmp.brand_profile_id:
                        _bp_for_brief = (
                            session.query(BrandProfile)
                            .filter_by(id=_pp_tmp.brand_profile_id)
                            .first()
                        )
            except Exception:
                logger.warning(
                    "Failed to load BrandProfile for brief generation",
                    exc_info=True,
                )

            _pp_for_brief = None
            try:
                if proj.product_profile_id:
                    _pp_for_brief = (
                        session.query(ProductProfile)
                        .filter_by(id=proj.product_profile_id)
                        .first()
                    )
            except Exception:
                logger.warning(
                    "Failed to load ProductProfile for brief generation",
                    exc_info=True,
                )

            _price_for_brief = None
            try:
                from pipeline.models.price_analysis import PriceAnalysis as _PA

                _price_for_brief = (
                    session.query(_PA).filter_by(project_id=project_id).first()
                )
            except Exception:
                logger.warning(
                    "Failed to load PriceAnalysis for brief generation",
                    exc_info=True,
                )

            _promo_for_brief = None
            try:
                from pipeline.models.promo_analysis import PromoAnalysis as _PRA

                _promo_for_brief = (
                    session.query(_PRA).filter_by(project_id=project_id).first()
                )
            except Exception:
                logger.warning(
                    "Failed to load PromoAnalysis for brief generation",
                    exc_info=True,
                )

            _vision_lines = []
            for bm in benchmarks:
                if not bm.analysis:
                    continue
                try:
                    _a = json.loads(bm.analysis)
                    _parts = []
                    if _a.get("visual_focus"):
                        _parts.append(f"visual_focus={_a['visual_focus']}")
                    if _a.get("depth_of_field"):
                        _parts.append(f"depth_of_field={_a['depth_of_field']}")
                    if _a.get("quality_score") is not None:
                        _parts.append(f"quality_score={_a['quality_score']}")
                    if _a.get("composition"):
                        _parts.append(f"composition={_a['composition']}")
                    if _parts:
                        _vision_lines.append(
                            f"- {bm.competitor_asin or 'competitor'}: {', '.join(_parts)}"
                        )
                except Exception:
                    pass
            _vision_insights_str = "\n".join(_vision_lines)

            if cl_for_brief is not None:
                # ── 软拦截：brief slots 全部填写则视为高置信度 ──
                _core_fields = [
                    "key_features",
                    "differentiation",
                    "target_audience",
                    "customer_pain_points",
                ]
                _brief_confidence = "low"
                _brief_confidence_reason = "customer_brief 未填写，Brief 基于竞品推断，建议补充产品信息以提升准确性"
                if proj.customer_brief:
                    try:
                        _cb_data = json.loads(proj.customer_brief)
                        _filled = [
                            f
                            for f in _core_fields
                            if _cb_data.get(f) and str(_cb_data[f]).strip()
                        ]
                        if len(_filled) == len(_core_fields):
                            _brief_confidence = "high"
                            _brief_confidence_reason = ""
                    except Exception:
                        pass  # 解析失败视为未填写

                briefs = generate_brief(
                    project_id=project_id,
                    competitor_listing=cl_for_brief,
                    review_clusters=review_clusters or [],
                    qa_entries=qa_entries or [],
                    session=session,
                    brand_profile=_bp_for_brief,
                    product_profile=_pp_for_brief,
                    vision_insights=_vision_insights_str,
                    pipeline_run_id=pipeline_run_id,
                    price_analysis=_price_for_brief,
                    promo_analysis=_promo_for_brief,
                    tenant_id=getattr(proj, "tenant_id", None),
                )

                # ── 将 confidence 注入每条 brief_json（不新增数据库列）──
                for _b in briefs:
                    try:
                        _slot = json.loads(_b.brief_json)
                        _slot["confidence"] = _brief_confidence
                        if _brief_confidence_reason:
                            _slot["confidence_reason"] = _brief_confidence_reason
                        _b.brief_json = json.dumps(_slot, ensure_ascii=False)
                    except Exception:
                        pass
                if session is not None:
                    session.commit()

                _cb(
                    f"✅ Phase 4b · 竞品图位 Brief 生成完成（{len(briefs)} 个 Brief，confidence={_brief_confidence}）"
                )
                logger.info(
                    "brief_generator complete for project %d: %d slots, confidence=%s",
                    project_id,
                    len(briefs),
                    _brief_confidence,
                )
            else:
                _cb("❌ Phase 4b · 无竞品 Listing，流水线中止")
                raise RuntimeError(
                    f"E_PIPELINE_P4B_NO_LISTING: no CompetitorListing for project {project_id}, cannot generate briefs"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            _cb("❌ Phase 4b · Brief 生成失败，流水线中止")
            raise RuntimeError(
                f"E_PIPELINE_P4B_BRIEF: brief_generator failed for project {project_id}: {exc}"
            ) from exc

        if has_asin:
            _cb("⏳ Phase 5 · 竞品 Listing 综合分析...")
            try:
                competitor_analysis = analyze_competitor_listing(proj.asin)
                _cb("✅ Phase 5 · 竞品 Listing 综合分析完成")
            except Exception as _phase5_exc:
                _cb(
                    f"❌ Phase 5 · 竞品 Listing 综合分析失败，流水线中止: {_phase5_exc}"
                )
                raise RuntimeError(
                    f"E_PIPELINE_P5_COMPETITOR: competitor analysis failed for project {project_id}: {_phase5_exc}"
                ) from _phase5_exc
    finally:
        session.close()

    _update_status(project_id, "analyzed")
    logger.info("Analysis complete for project %d", project_id)
    return {
        "asin_detail": asin_detail,
        "category_top": category_top,
        "competitor_analysis": competitor_analysis,
        "vision_analyzed": vision_analyzed,
        "pipeline_run_id": pipeline_run_id,
    }


def step_plan(project_id: int, analysis_results: dict | None = None) -> list:
    """Generate slot plan + seed PromptAssets. Sets status='planned'."""
    pipeline_run_id = (analysis_results or {}).get("pipeline_run_id")
    if analysis_results:
        logger.info(
            "step_plan received analysis_results keys: %s",
            list(analysis_results.keys()),
        )
    # 获取 tenant_id 以便写入 SlotPlan / PromptAsset
    _tenant_id = None
    try:
        _s = get_session()
        _p = _s.get(Project, project_id)
        _tenant_id = getattr(_p, "tenant_id", None) if _p else None
    except Exception:
        pass

    slots = generate_slot_plan(
        project_id, pipeline_run_id=pipeline_run_id, tenant_id=_tenant_id
    )

    from pipeline.layers.prompt_manager import create_prompt_asset
    from pipeline.constants.tags import SLOT_MAPPING

    for slot in slots:
        desc = SLOT_MAPPING.get(slot.slot_index, f"Slot {slot.slot_index}")
        prompt_text = (
            f"Slot {slot.slot_index}: {desc}\n"
            f"Intent: {slot.intent_tag or ''}\n"
            f"Layout: {slot.layout_tag or ''}\n"
            f"Style: {slot.style_tag or ''}\n"
            f"Color: {slot.color_tag or ''}"
        )
        try:
            create_prompt_asset(
                project_id=project_id,
                slot_index=slot.slot_index,
                prompt_text=prompt_text,
                model_name=config.image_model,
                pipeline_run_id=pipeline_run_id,
                tenant_id=_tenant_id,
            )
        except ValueError as exc:
            logger.warning(
                "Could not seed PromptAsset for slot %d: %s", slot.slot_index, exc
            )

    _update_status(project_id, "planned")
    logger.info("Slot plan generated for project %d: %d slots", project_id, len(slots))
    return slots


def step_regen_single_slot(project_id: int, slot_index: int) -> SlotPlan:
    from pipeline.layers.slot_planner import regen_single_slot
    from pipeline.layers.prompt_manager import create_prompt_asset
    from pipeline.constants.tags import SLOT_MAPPING

    _tenant_id = None
    _s = get_session()
    try:
        _p = _s.get(Project, project_id)
        _tenant_id = getattr(_p, "tenant_id", None) if _p else None
    finally:
        _s.close()

    slot = regen_single_slot(project_id, slot_index)
    desc = SLOT_MAPPING.get(slot.slot_index, f"Slot {slot.slot_index}")
    prompt_text = (
        f"Slot {slot.slot_index}: {desc}\n"
        f"Intent: {slot.intent_tag or ''}\n"
        f"Layout: {slot.layout_tag or ''}\n"
        f"Style: {slot.style_tag or ''}\n"
        f"Color: {slot.color_tag or ''}"
    )
    try:
        create_prompt_asset(
            project_id=project_id,
            slot_index=slot.slot_index,
            prompt_text=prompt_text,
            model_name=config.image_model,
            tenant_id=_tenant_id,
        )
    except ValueError as exc:
        logger.warning(
            "Could not seed PromptAsset for slot %d: %s", slot.slot_index, exc
        )
    logger.info("Regen single slot %d for project %d done", slot_index, project_id)
    return slot


def step_aplus(project_id: int) -> list:
    """Generate A+ content storyboard for project. Returns list of APlusContent rows."""
    from pipeline.layers.aplus_generator import generate_aplus_storyboard

    session = get_session()
    try:
        return generate_aplus_storyboard(project_id, session=session)
    finally:
        session.close()


def step_generate_aplus_images(project_id: int) -> list:
    """为 A+ 宽幅模块（HERO/LIFESTYLE/BRAND_STORY）生成专属图片，写回 aplus_contents.image_path。"""
    from pipeline.layers.aplus_image_generator import generate_aplus_images

    session = get_session()
    try:
        return generate_aplus_images(project_id, session=session)
    finally:
        session.close()


import os as _os

_SLOT_INTENT_REF_TYPES: dict[str, list[str]] = {
    "INT_HERO": ["front_view_image_paths", "white_bg"],
    "INT_LIFESTYLE": ["usage_context_image_paths", "side_view_image_paths"],
    "INT_DETAIL": ["macro_view_image_paths", "detail_closeup_image_paths"],
    "INT_INFOGRAPHIC": ["macro_view_image_paths", "front_view_image_paths", "white_bg"],
    "INT_COMPARISON": ["white_bg", "color_variant_image_paths"],
    "INT_PACKAGING": ["packaging_image_path", "inbox_flatlay_image_path"],
}


def _build_slot_ref_paths(
    white_bg_path: str | None,
    multiangle_paths: list[str],
    extra: dict,
    intent_tag: str | None,
) -> list[str]:
    keys = _SLOT_INTENT_REF_TYPES.get(intent_tag or "", ["white_bg"])
    candidates: list[str] = []
    for k in keys:
        if k == "white_bg":
            if white_bg_path:
                candidates.append(white_bg_path)
        elif k == "multiangle":
            candidates.extend(multiangle_paths)
        else:
            val = extra.get(k) or ""
            if isinstance(val, list):
                candidates.extend(val)
            else:
                candidates.append(val)
    paths = [p for p in candidates if p and _os.path.isfile(p)]
    if not paths and white_bg_path and _os.path.isfile(white_bg_path):
        paths = [white_bg_path]
    return paths


def step_generate(
    project_id: int,
    adapter_name: str = "gpt_image",
    slot_indices: list[int] | None = None,
    pipeline_run_id: int | None = None,
) -> dict[str, str]:
    """Generate prompts and run image adapter. Sets status='generated'."""
    from pipeline.models.prompt_asset import PromptAsset
    from pipeline.models.slot_plan import SlotPlan

    # Gate 4：提前检查 consistency_profile，避免 8 张图全部生成后才发现品牌档案不完整
    from pipeline.layers.consistency_system import (
        check_gate4,
        warm_start_consistency_profile,
    )

    _proj_session = get_session()
    try:
        _proj = _proj_session.get(Project, project_id)
        _category = _proj.category if _proj else None
    finally:
        _proj_session.close()

    warm_start_consistency_profile(project_id, category=_category)

    gate4 = check_gate4(project_id)
    if not gate4["passed"]:
        raise RuntimeError(
            f"Gate 4 未通过，以下 consistency_profile 字段为空："
            f"{gate4['missing']}，请先完善一致性配置再执行生成步骤。"
        )

    prompts = generate_slot_prompts(project_id, slot_indices=slot_indices)
    adapter = get_adapter(adapter_name)

    session = get_session()
    try:
        plans = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.slot_index)
            .all()
        )
        label_to_slot_index = {}
        for plan in plans:
            from pipeline.layers.prompt_engine import _slot_label

            label_to_slot_index[_slot_label(plan.slot_index)] = plan.slot_index

        proj = session.get(Project, project_id)
        white_bg_path: str | None = None
        reference_assets: dict[str, list[str]] = {}
        if proj is not None:
            from pipeline.layers.project_constraints import (
                enrich_customer_brief,
                load_customer_brief,
            )
            from pipeline.layers.reference_asset_normalizer import normalize_reference_assets

            _cb = enrich_customer_brief(load_customer_brief(proj))
            proj.customer_brief = json.dumps(_cb, ensure_ascii=False)
            session.add(proj)
            commit_with_retry(session)
            reference_assets = normalize_reference_assets(_cb)
            white_paths = reference_assets.get("white_bg", [])
            white_bg_path = white_paths[0] if white_paths else None

        # 白底图为必填项，缺失直接报错，不允许走纯文生图路径
        if not white_bg_path:
            raise ValueError(
                f"项目 {project_id} 缺少白底图（white_bg_image_path），"
                "请先上传白底图后再执行生成步骤。"
            )

        slot_index_to_plan = {
            plan.slot_index: {
                "custom_image_paths": plan.custom_image_paths,
                "intent_tag": plan.intent_tag,
            }
            for plan in plans
        }
        session.close()
        session = None

        results = {}
        failed_slots: list[str] = []
        for slot_label, prompt_text in prompts.items():
            try:
                _slot_idx = label_to_slot_index.get(slot_label)
                _plan = (
                    slot_index_to_plan.get(_slot_idx) if _slot_idx is not None else None
                )
                _custom_paths: list[str] = []
                if _plan and _plan.get("custom_image_paths"):
                    _custom_paths = [
                        p for p in str(_plan["custom_image_paths"]).split(",") if p.strip()
                    ]
                from pipeline.layers.reference_policy import select_reference_paths

                _intent_tag = _plan.get("intent_tag") if _plan else None
                try:
                    from pipeline.layers.delivery_status import is_product_fact_intent

                    _product_fact_only = is_product_fact_intent(_intent_tag)
                except Exception:
                    _product_fact_only = False
                _per_slot_paths = (
                    select_reference_paths(
                        reference_assets,
                        _intent_tag,
                        product_fact_only=_product_fact_only,
                    )
                    + _custom_paths
                )
                _edit_fn = getattr(adapter, "edit", None) or getattr(
                    adapter, "edit_image", None
                )
                if _edit_fn is not None:
                    if hasattr(adapter, "edit"):
                        result = getattr(adapter, "edit")(_per_slot_paths, prompt_text)
                    else:
                        import base64, os

                        _primary = _per_slot_paths[0]
                        abs_path = (
                            _primary
                            if os.path.isabs(_primary)
                            else os.path.abspath(_primary)
                        )
                        with open(abs_path, "rb") as _f:
                            image_b64 = base64.b64encode(_f.read()).decode()
                        result = getattr(adapter, "edit_image")(image_b64, prompt_text)
                else:
                    raise RuntimeError(
                        f"适配器 {adapter_name} 不支持 edit 模式，无法处理白底图。"
                    )
            except Exception as slot_exc:
                logger.warning("slot %s 生图失败，跳过继续：%s", slot_label, slot_exc)
                failed_slots.append(slot_label)
                continue

            results[slot_label] = result
            logger.info("Generated image for %s via %s", slot_label, adapter_name)

            if result.image_path:
                slot_index = label_to_slot_index.get(slot_label)
                if slot_index is not None:
                    vision = None
                    try:
                        from pipeline.layers.vision_analyzer import analyze_image

                        vision = analyze_image(result.image_path)
                    except Exception as _ve:
                        logger.warning(
                            "slot %s vision 回写失败，跳过：%s", slot_label, _ve
                        )

                    write_session = get_session()
                    try:
                        asset = (
                            write_session.query(PromptAsset)
                            .filter(
                                PromptAsset.project_id == project_id,
                                PromptAsset.slot_index == slot_index,
                                *(
                                    [PromptAsset.pipeline_run_id == pipeline_run_id]
                                    if pipeline_run_id is not None
                                    else []
                                ),
                            )
                            .order_by(PromptAsset.version.desc())
                            .first()
                        )
                        if asset and not asset.user_edited:
                            asset.image_path = result.image_path
                            asset.prompt_text = prompt_text
                        elif asset:
                            asset.image_path = result.image_path
                        if asset:
                            try:
                                from pipeline.layers.delivery_status import merge_visual_tags, reference_basis

                                asset.model_name = adapter_name
                                asset.visual_tags = merge_visual_tags(
                                    asset.visual_tags,
                                    {
                                        "model_used": adapter_name,
                                        "reference_paths": _per_slot_paths,
                                        "reference_basis": reference_basis(_per_slot_paths),
                                        "product_fact_required": _product_fact_only,
                                    },
                                )
                            except Exception as _meta_exc:
                                logger.warning("slot %s delivery metadata 写入失败：%s", slot_label, _meta_exc)

                        plan = (
                            write_session.query(SlotPlan)
                            .filter(
                                SlotPlan.project_id == project_id,
                                SlotPlan.slot_index == slot_index,
                                *(
                                    [SlotPlan.pipeline_run_id == pipeline_run_id]
                                    if pipeline_run_id is not None
                                    else []
                                ),
                            )
                            .order_by(SlotPlan.id.desc())
                            .first()
                        )
                        if plan is not None and vision:
                            plan.generated_lighting = vision.get("lighting") or None
                            plan.generated_angle = vision.get("angle") or None
                            plan.generated_shot_type = vision.get("shot_type") or None
                            plan.generated_bg_material = (
                                vision.get("background_material") or None
                            )
                            plan.generated_color_temp = vision.get("color_temp") or None
                            plan.generated_saturation = vision.get("saturation") or None
                        commit_with_retry(write_session)
                    finally:
                        write_session.close()

        if failed_slots:
            logger.warning("以下 slot 生图失败，已跳过：%s", failed_slots)
    finally:
        if session is not None:
            session.close()

    if slot_indices is None:
        _update_status(project_id, "generated")
    return results


_QA_MAX_RETRIES = 2
_QA_PASS_THRESHOLD = 70
_QA_RETRY_THRESHOLD = 60  # 重试阈值放宽至 60，与 A+ 图两档机制对齐


def _qa_record_details(record: object | None) -> dict:
    raw = getattr(record, "details", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _angle_mismatch_requires_retry(details: dict) -> bool:
    return details.get("angle_matches_target") is False


def step_qa(
    project_id: int, adapter_name: str = "gpt_image", pipeline_run_id: int | None = None
) -> list:
    """Run QA checks with retry loop. Max 2 retries per slot (3 total attempts)."""
    session = get_session()
    try:
        from pipeline.models.slot_plan import SlotPlan
        from pipeline.models.prompt_asset import PromptAsset

        # BUG-08：按 pipeline_run_id 过滤，避免处理旧 run 的 slot
        q = session.query(SlotPlan).filter(SlotPlan.project_id == project_id)
        if pipeline_run_id is not None:
            q = q.filter(SlotPlan.pipeline_run_id == pipeline_run_id)
        slots = q.all()
    finally:
        session.close()

    all_records = []
    all_passed = True
    for slot in slots:
        slot_id = slot.id
        slot_index = slot.slot_index
        passed_slot = False
        for attempt in range(_QA_MAX_RETRIES + 1):
            records = run_qa_checks(slot_id)
            all_records.extend(records)

            slot_score = records[0].score if records else 0
            slot_passed = records[0].passed if records else False
            record_details = _qa_record_details(records[0] if records else None)
            angle_retry_needed = _angle_mismatch_requires_retry(record_details)

            pass_threshold = _QA_PASS_THRESHOLD if attempt == 0 else _QA_RETRY_THRESHOLD
            if slot_passed and slot_score >= pass_threshold and not angle_retry_needed:
                passed_slot = True
                try:
                    ok_session = get_session()
                    try:
                        pa_ok = (
                            ok_session.query(PromptAsset)
                            .filter(
                                PromptAsset.project_id == project_id,
                                PromptAsset.slot_index == slot_index,
                            )
                            .order_by(PromptAsset.version.desc())
                            .first()
                        )
                        if pa_ok:
                            pa_ok.performance_score = slot_score / 100.0
                            commit_with_retry(ok_session)
                    finally:
                        ok_session.close()
                except Exception as exc:
                    logger.warning("无法写入 QA 通过分数 slot %d: %s", slot_id, exc)
                break

            if attempt < _QA_MAX_RETRIES:
                issues = []
                dim_scores = {}
                if record_details:
                    issues = record_details.get("issues", []) or []
                    if angle_retry_needed:
                        issues = [
                            *issues,
                            (
                                "Angle mismatch: target "
                                f"{record_details.get('target_angle')} but generated "
                                f"{record_details.get('actual_angle')}"
                            ),
                        ]
                    dim_scores = {
                        k: record_details.get(k, 0)
                        for k in ("A", "B", "C", "D", "E")
                        if k in record_details
                    }
                logger.info(
                    "QA retry for slot %d (attempt %d/%d, score=%.0f, angle_retry=%s), 改写 prompt 后重新生图",
                    slot_id,
                    attempt + 1,
                    _QA_MAX_RETRIES + 1,
                    slot_score,
                    angle_retry_needed,
                )
                try:
                    from pipeline.layers.qa_gate import refine_prompt_with_qa

                    pa_session = get_session()
                    try:
                        pa = (
                            pa_session.query(PromptAsset)
                            .filter(
                                PromptAsset.project_id == project_id,
                                PromptAsset.slot_index == slot_index,
                            )
                            .order_by(PromptAsset.version.desc())
                            .first()
                        )
                        if pa:
                            refine_prompt_with_qa(
                                pa.prompt_text,
                                issues,
                                dim_scores,
                                prompt_asset_id=pa.id,
                            )
                    finally:
                        pa_session.close()
                except Exception as exc:
                    logger.warning("Prompt 改写失败 slot %d: %s", slot_id, exc)

                try:
                    step_generate(
                        project_id,
                        adapter_name=adapter_name,
                        slot_indices=[slot_index],
                        pipeline_run_id=pipeline_run_id,
                    )
                except Exception as exc:
                    logger.warning("Regeneration failed for slot %d: %s", slot_id, exc)
                    break

        if not passed_slot:
            route = _route_by_confidence(slot_score)
            if route == "human_review":
                logger.error(
                    "QA failed for slot %d after %d attempts (score=%.0f); routed to human_review",
                    slot_id,
                    _QA_MAX_RETRIES + 1,
                    slot_score,
                )
                _update_status(project_id, "needs_human_review")
            else:
                logger.warning(
                    "QA failed for slot %d after %d attempts (score=%.0f < %d); skipping delivery for this slot",
                    slot_id,
                    _QA_MAX_RETRIES + 1,
                    slot_score,
                    _QA_RETRY_THRESHOLD,
                )
            all_passed = False
            try:
                warn_session = get_session()
                try:
                    pa_warn = (
                        warn_session.query(PromptAsset)
                        .filter(
                            PromptAsset.project_id == project_id,
                            PromptAsset.slot_index == slot_index,
                        )
                        .order_by(PromptAsset.version.desc())
                        .first()
                    )
                    if pa_warn:
                        pa_warn.performance_score = -1.0
                        commit_with_retry(warn_session)
                finally:
                    warn_session.close()
            except Exception as exc:
                logger.warning("无法写入 QA 失败标记 slot %d: %s", slot_id, exc)

    status = "qa_passed" if all_passed else "qa_failed"
    _update_status(project_id, status)
    logger.info("QA %s for project %d", status, project_id)

    try:
        from pipeline.layers.qa_gate import run_series_qa

        series_result = run_series_qa(project_id)
        if series_result.get("skipped"):
            logger.info(
                "Series QA skipped for project %d: %s",
                project_id,
                series_result.get("reason"),
            )
        else:
            total = series_result.get("total", 0) or 0
            _log = logger.warning if total < 70 else logger.info
            _log(
                "Series QA project %d: total=%d S1=%s S2=%s S3=%s S4=%s S5=%s issues=%s",
                project_id,
                total,
                series_result.get("S1"),
                series_result.get("S2"),
                series_result.get("S3"),
                series_result.get("S4"),
                series_result.get("S5"),
                series_result.get("issues"),
            )
    except Exception as _sq_exc:
        logger.warning("run_series_qa failed for project %d: %s", project_id, _sq_exc)

    return all_records


def step_report(project_id: int) -> dict:
    """Export project report. Sets status='completed'."""
    report = export_project_report(project_id)
    _update_status(project_id, "completed")
    logger.info("Report exported for project %d", project_id)
    return report


def step_deliver(project_id: int) -> str | None:
    """Build delivery package. Returns package path or None if empty."""
    from pipeline.layers.delivery import build_delivery_package

    delivery_path = build_delivery_package(project_id)
    if not delivery_path or not any(Path(delivery_path).iterdir()):
        logger.warning(
            "step_deliver: empty or missing delivery package for project %d",
            project_id,
        )
        return None
    logger.info("Delivery package built for project %d: %s", project_id, delivery_path)

    # BUG-06 修复：对已交付的 approved 图片调用 capture_snapshot，记录快照
    try:
        from pipeline.layers.change_detector import capture_snapshot
        from pipeline.models.prompt_asset import PromptAsset as _PA
        from pipeline.models.project import Project as _SnapProj

        _snap_session = get_session()
        try:
            _snap_proj = _snap_session.get(_SnapProj, project_id)
            _snap_asin = getattr(_snap_proj, "asin", None) if _snap_proj else None
            _snap_tenant = (
                getattr(_snap_proj, "tenant_id", None) if _snap_proj else None
            )
            if _snap_asin:
                _assets = (
                    _snap_session.query(_PA)
                    .filter_by(project_id=project_id, approved=True)
                    .all()
                )
                for _asset in _assets:
                    if _asset.image_path:
                        try:
                            capture_snapshot(
                                _snap_session,
                                project_id=project_id,
                                asin=_snap_asin,
                                image_url=_asset.image_path,
                                slot_position=_asset.slot_index,
                                tenant_id=_snap_tenant,
                            )
                        except Exception as _snap_exc:
                            logger.warning(
                                "capture_snapshot 失败 project %d slot %d: %s",
                                project_id,
                                _asset.slot_index,
                                _snap_exc,
                            )
        finally:
            _snap_session.close()
    except Exception as _bug06_exc:
        logger.warning(
            "BUG-06 snapshot 整体失败 project %d: %s", project_id, _bug06_exc
        )

    if getattr(config, "flywheel_enabled", False):
        from pipeline.flywheel import run_flywheel

        _proj_session = get_session()
        try:
            from pipeline.models.project import Project as _Proj

            _fw_proj = _proj_session.get(_Proj, project_id)
            _fw_tenant_id = getattr(_fw_proj, "tenant_id", None) if _fw_proj else None
        finally:
            _proj_session.close()

        _fw_session = get_session()
        try:
            fw_result = run_flywheel(
                project_id=project_id,
                session=_fw_session,
                tenant_id=_fw_tenant_id,
            )
            logger.info("飞轮归档 project %d: %s", project_id, fw_result)
        except Exception as exc:
            logger.warning("飞轮归档失败 project %d: %s", project_id, exc)
        finally:
            _fw_session.close()
    return delivery_path


# ── category_priors 更新三道门 ──────────────────────────────────────────────
# 门1：当前品牌 approved 图 ≥ 30 张
# 门2：同品类中达到门1条件的品牌 ≥ 2 个
# 门3：approved 图时间跨度 ≥ 14 天（用 created_at 代替，因无 approved_at 字段）
# 全部通过后，取所有达标品牌的 ELASTIC 字段值做众数融合，再写入 category_priors
# 单品牌即可写入，但置信度按 N/(N+pseudo_count) 折扣，避免裸跑空白先验
_PRIOR_MIN_APPROVED = 30
_PRIOR_MIN_DAYS = 14
_PRIOR_PSEUDO_COUNT = 20  # 业界默认值（Amazon/Zalando），N=1 时 confidence≈4.8%


def _try_update_category_priors(proj, brand, project_id: int, session) -> None:
    from pipeline.layers.brand_constraints import ELASTIC_FIELDS
    from pipeline.layers.cold_start import update_category_priors
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.models.product_profile import ProductProfile
    from pipeline.models.prompt_asset import PromptAsset

    approved_assets = (
        session.query(PromptAsset).filter_by(project_id=project_id, approved=True).all()
    )
    if len(approved_assets) < _PRIOR_MIN_APPROVED:
        logger.info(
            "project %d approved %d 张 < %d，跳过 category_priors（门1）",
            project_id,
            len(approved_assets),
            _PRIOR_MIN_APPROVED,
        )
        return

    dates = [a.created_at for a in approved_assets if a.created_at is not None]
    if dates and (max(dates) - min(dates)).days < _PRIOR_MIN_DAYS:
        logger.info(
            "project %d 时间跨度 %d 天 < %d，跳过 category_priors（门3）",
            project_id,
            (max(dates) - min(dates)).days,
            _PRIOR_MIN_DAYS,
        )
        return

    same_category_projects = (
        session.query(Project).filter_by(category=proj.category).all()
    )

    qualifying_brands: list = []
    for p in same_category_projects:
        pp = session.query(ProductProfile).filter_by(project_id=p.id).first()
        if not pp or not pp.brand_profile_id:
            continue
        bp = session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
        if bp is None:
            continue
        p_assets = (
            session.query(PromptAsset).filter_by(project_id=p.id, approved=True).all()
        )
        if len(p_assets) < _PRIOR_MIN_APPROVED:
            continue
        p_dates = [a.created_at for a in p_assets if a.created_at is not None]
        if p_dates and (max(p_dates) - min(p_dates)).days < _PRIOR_MIN_DAYS:
            continue
        qualifying_brands.append(bp)

    field_values: dict[str, list[str]] = {f: [] for f in ELASTIC_FIELDS}
    for bp in qualifying_brands:
        for f in ELASTIC_FIELDS:
            val = getattr(bp, f, None)
            if val is not None:
                field_values[f].append(val)

    field_values = {f: v for f, v in field_values.items() if v}
    if not field_values:
        return

    n_brands = len(qualifying_brands)
    confidence = n_brands / (n_brands + _PRIOR_PSEUDO_COUNT)
    logger.info(
        "品类 %s 两道门全过（%d 个品牌，置信度 %.1f%%），写入 category_priors",
        proj.category,
        n_brands,
        confidence * 100,
    )
    update_category_priors(proj.category, field_values, session, sample_count=n_brands)
    session.commit()


def step_feedback(project_id: int, session=None) -> None:
    """Run feedback loop to update BrandProfile from pipeline results.

    Skips silently if no BrandProfile exists for the project.
    """
    from pipeline.layers.feedback_loop import update_brand_profile_from_results
    from pipeline.models.brand_profile import BrandProfile

    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        # 正确路径：project → ProductProfile → BrandProfile
        from pipeline.models.product_profile import ProductProfile

        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        brand = (
            session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
            if pp and pp.brand_profile_id
            else None
        )
        if brand is None:
            logger.warning(
                "No BrandProfile found for project %d, skipping feedback loop",
                project_id,
            )
            return
        update_brand_profile_from_results(project_id)

        from pipeline.layers.feedback_loop import sync_qa_statuses

        sync_qa_statuses(project_id, session)

        proj = session.get(Project, project_id)
        if proj and proj.category and brand:
            _try_update_category_priors(proj, brand, project_id, session)

        logger.info("Feedback loop completed for project %d", project_id)
    finally:
        if owns_session:
            session.close()


def run_full_pipeline(brief_path: str, adapter_name: str = "gpt_image") -> dict:
    """Run all pipeline steps end-to-end.

    Returns dict with keys: project_id, status, report, delivery_path.
    On failure, sets project status to 'failed' and re-raises.
    """
    project = step_init(brief_path)
    project_id = project.id

    try:
        analysis_results = step_analyze(project_id)
        pipeline_run_id = analysis_results.get("pipeline_run_id")
        step_plan(project_id, analysis_results=analysis_results)
        step_generate(project_id, adapter_name, pipeline_run_id=pipeline_run_id)
        step_qa(project_id, adapter_name=adapter_name)
        step_aplus(project_id)
        step_generate_aplus_images(project_id)
        report = step_report(project_id)
        delivery_path = step_deliver(project_id)
        step_feedback(project_id)
        if pipeline_run_id:
            _finish_pipeline_run(pipeline_run_id, "completed")
        return {
            "project_id": project_id,
            "status": "completed",
            "report": report,
            "delivery_path": delivery_path,
        }
    except Exception as exc:
        _update_status(project_id, "failed")
        if "pipeline_run_id" in dir():
            _finish_pipeline_run(pipeline_run_id, "failed", str(exc))
        raise
