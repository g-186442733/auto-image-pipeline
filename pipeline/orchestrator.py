"""Pipeline orchestrator — runs the full pipeline end-to-end."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipeline.config import config
from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.pipeline_run import PipelineRun
from pipeline.models.prompt_asset import PromptAsset
from pipeline.layers.input_layer import create_project
from pipeline.layers.amazon_data import (
    fetch_asin_detail,
    fetch_category_top,
    KeepaDataError,
)
from pipeline.layers.vision_analyzer import analyze_competitor_listing
from pipeline.layers.slot_planner import generate_slot_plan
from pipeline.layers.prompt_engine import generate_slot_prompts
from pipeline.layers.qa_gate import run_qa_checks
from pipeline.layers.feedback_loop import export_project_report
from pipeline.layers.price_analyzer import analyze_price
from pipeline.layers.promo_analyzer import analyze_promo
from pipeline.adapters.registry import get_adapter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.orchestrator")


def _call_vision(image_url: str) -> dict:
    """Call vision analyzer for a single image URL. Returns analysis dict."""
    from pipeline.layers.vision_analyzer import analyze_image

    return analyze_image(image_url)


def _update_status(project_id: int, status: str) -> None:
    session = get_session()
    try:
        proj = session.get(Project, project_id)
        if proj:
            proj.status = status
            session.commit()
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
                fut_cat = pool.submit(fetch_category_top, proj.category)
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
                category_top = fetch_category_top(proj.category)
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
                pa = analyze_price(proj.asin, asin_detail, category_top)
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
            with ThreadPoolExecutor(max_workers=4) as pool:
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
                )
                _cb(f"✅ Phase 4b · 竞品图位 Brief 生成完成（{len(briefs)} 个 Brief）")
                logger.info(
                    "brief_generator complete for project %d: %d slots",
                    project_id,
                    len(briefs),
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
    slots = generate_slot_plan(project_id, pipeline_run_id=pipeline_run_id)

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


def step_generate(
    project_id: int,
    adapter_name: str = "gpt_image",
    slot_indices: list[int] | None = None,
) -> dict[str, str]:
    """Generate prompts and run image adapter. Sets status='generated'."""
    from pipeline.models.prompt_asset import PromptAsset
    from pipeline.models.slot_plan import SlotPlan

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
        multiangle_paths: list[str] = []
        if proj and proj.customer_brief:
            try:
                _cb = json.loads(proj.customer_brief)
                white_bg_path = _cb.get("white_bg_image_path") or None
                _raw = _cb.get("multiangle_image_paths", "")
                if _raw:
                    multiangle_paths = [p for p in _raw.split(",") if p.strip()]
            except (json.JSONDecodeError, AttributeError):
                white_bg_path = None

        # 白底图为必填项，缺失直接报错，不允许走纯文生图路径
        if not white_bg_path:
            raise ValueError(
                f"项目 {project_id} 缺少白底图（white_bg_image_path），"
                "请先上传白底图后再执行生成步骤。"
            )

        edit_image_paths: list[str] = [white_bg_path] + multiangle_paths

        results = {}
        for slot_label, prompt_text in prompts.items():
            _edit_fn = getattr(adapter, "edit", None) or getattr(
                adapter, "edit_image", None
            )
            if _edit_fn is not None:
                if hasattr(adapter, "edit"):
                    result = getattr(adapter, "edit")(edit_image_paths, prompt_text)
                else:
                    import base64, os

                    _primary = edit_image_paths[0]
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
            results[slot_label] = result
            logger.info("Generated image for %s via %s", slot_label, adapter_name)

            if result.image_path:
                slot_index = label_to_slot_index.get(slot_label)
                if slot_index is not None:
                    asset = (
                        session.query(PromptAsset)
                        .filter(
                            PromptAsset.project_id == project_id,
                            PromptAsset.slot_index == slot_index,
                        )
                        .order_by(PromptAsset.version.desc())
                        .first()
                    )
                    if asset and not asset.user_edited:
                        asset.image_path = result.image_path
                        asset.prompt_text = prompt_text
                    elif asset:
                        asset.image_path = result.image_path

        session.commit()
    finally:
        session.close()

    if slot_indices is None:
        _update_status(project_id, "generated")
    return results


_QA_MAX_RETRIES = 2
_QA_PASS_THRESHOLD = 70
_QA_RETRY_THRESHOLD = 70


def _route_by_confidence(score: float) -> str:
    if score >= _QA_PASS_THRESHOLD:
        return "pass"
    elif score >= 50:
        return "retry_alt_prompt"
    else:
        return "human_review"


def step_qa(project_id: int, adapter_name: str = "gpt_image") -> list:
    """Run QA checks with retry loop. Max 2 retries per slot (3 total attempts)."""
    session = get_session()
    try:
        from pipeline.models.slot_plan import SlotPlan

        slots = session.query(SlotPlan).filter(SlotPlan.project_id == project_id).all()
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

            pass_threshold = _QA_PASS_THRESHOLD if attempt == 0 else _QA_RETRY_THRESHOLD
            if slot_passed and slot_score >= pass_threshold:
                passed_slot = True
                break

            if attempt < _QA_MAX_RETRIES:
                issues = []
                dim_scores = {}
                if records and records[0].details:
                    try:
                        details = json.loads(records[0].details)
                        issues = details.get("issues", [])
                        dim_scores = {
                            k: details.get(k, 0)
                            for k in ("A", "B", "C", "D", "E")
                            if k in details
                        }
                    except (json.JSONDecodeError, TypeError):
                        pass
                logger.info(
                    "QA failed for slot %d (attempt %d/%d, score=%.0f), 改写 prompt 后重新生图",
                    slot_id,
                    attempt + 1,
                    _QA_MAX_RETRIES + 1,
                    slot_score,
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
                            refined = refine_prompt_with_qa(
                                pa.prompt_text, issues, dim_scores
                            )
                            if refined != pa.prompt_text:
                                pa.prompt_text = refined
                                pa.version = (pa.version or 1) + 1
                                pa_session.commit()
                                logger.info(
                                    "Slot %d prompt 已改写为 v%d",
                                    slot_index,
                                    pa.version,
                                )
                    finally:
                        pa_session.close()
                except Exception as exc:
                    logger.warning("Prompt 改写失败 slot %d: %s", slot_id, exc)

                try:
                    try:
                        step_generate(
                            project_id, adapter_name=adapter_name, slot_indices=[slot_index]
                        )
                    except TypeError as exc:
                        if "slot_indices" not in str(exc):
                            raise
                        step_generate(project_id, adapter_name=adapter_name)
                except Exception as exc:
                    logger.warning("Regeneration failed for slot %d: %s", slot_id, exc)
                    break

        if not passed_slot:
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
                        warn_session.commit()
                finally:
                    warn_session.close()
            except Exception as exc:
                logger.warning("无法写入 QA 失败标记 slot %d: %s", slot_id, exc)

    status = "qa_passed" if all_passed else "qa_failed"
    _update_status(project_id, status)
    logger.info("QA %s for project %d", status, project_id)
    return all_records


def step_report(project_id: int) -> dict:
    """Export project report. Sets status='completed'."""
    report = export_project_report(project_id)
    _update_status(project_id, "completed")
    logger.info("Report exported for project %d", project_id)
    return report


def step_deliver(project_id: int) -> str | None:
    """Build delivery package. Returns package path or None if empty."""
    # Gate 4：consistency_profile 5个风格字段全部非空才允许投递
    from pipeline.layers.consistency_system import check_gate4

    gate4 = check_gate4(project_id)
    if not gate4["passed"]:
        raise RuntimeError(
            f"Gate 4 未通过，以下 consistency_profile 字段为空："
            f"{gate4['missing']}，请先完善一致性配置再投递。"
        )
    from pipeline.layers.delivery import build_delivery_package

    delivery_path = build_delivery_package(project_id)
    if not delivery_path or not any(Path(delivery_path).iterdir()):
        logger.warning(
            "step_deliver: empty or missing delivery package for project %d",
            project_id,
        )
        return None
    logger.info("Delivery package built for project %d: %s", project_id, delivery_path)
    if getattr(config, "flywheel_enabled", False):
        from pipeline.flywheel import run_flywheel  # noqa: F811
    return delivery_path


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
        step_generate(project_id, adapter_name)
        step_aplus(project_id)
        step_qa(project_id, adapter_name=adapter_name)
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
