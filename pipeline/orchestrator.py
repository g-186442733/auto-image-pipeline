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
from pipeline.layers.input_layer import create_project
from pipeline.layers.amazon_data import fetch_asin_detail, fetch_category_top
from pipeline.layers.vision_analyzer import analyze_competitor_listing
from pipeline.layers.slot_planner import generate_slot_plan
from pipeline.layers.prompt_engine import generate_slot_prompts
from pipeline.layers.qa_gate import run_qa_checks
from pipeline.layers.feedback_loop import export_project_report
from pipeline.layers.price_analyzer import analyze_price
from pipeline.layers.promo_analyzer import analyze_promo
from pipeline.adapters.registry import get_adapter
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.orchestrator")


def _call_vision(image_url: str) -> dict:
    """Call vision analyzer for a single image URL. Returns analysis dict."""
    from pipeline.layers.vision_analyzer import analyze_image

    return analyze_image(image_url)


def _update_status(project_id: int, status: str) -> None:
    """Update project status in DB."""
    session = get_session()
    try:
        proj = session.get(Project, project_id)
        if proj:
            proj.status = status
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


def step_analyze(project_id: int) -> dict:
    """Fetch Amazon data and analyze competitors. Sets status='analyzed'."""
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

        # --- Phase 1: fetch Amazon data (parallel or sequential) ---
        asin_detail = None
        category_top = None
        if parallel:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_asin = pool.submit(fetch_asin_detail, proj.asin)
                fut_cat = pool.submit(fetch_category_top, proj.category)
                try:
                    asin_detail = fut_asin.result()
                except Exception as e:
                    logger.error(
                        "fetch_asin_detail failed for project %d: %s", project_id, e
                    )
                try:
                    category_top = fut_cat.result()
                except Exception as e:
                    logger.error(
                        "fetch_category_top failed for project %d: %s", project_id, e
                    )
        else:
            try:
                asin_detail = fetch_asin_detail(proj.asin)
            except Exception as e:
                logger.error(
                    "fetch_asin_detail failed for project %d: %s", project_id, e
                )
            try:
                category_top = fetch_category_top(proj.category)
            except Exception as e:
                logger.error(
                    "fetch_category_top failed for project %d: %s", project_id, e
                )

        # 持久化竞品主 listing（CompetitorListing）
        if asin_detail is not None:
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
            else:
                cl = CompetitorListing(
                    project_id=project_id,
                    asin=proj.asin,
                    title=asin_detail.get("title"),
                )
                session.add(cl)
            session.commit()
            logger.info(
                "Upserted CompetitorListing for project %d asin %s",
                project_id,
                proj.asin,
            )

        # 预初始化变量，防止 try 块失败时未定义
        listing_result = None
        review_clusters = None
        qa_entries = None

        # --- Phase 2: analyzer trio (parallel or sequential) ---
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
                except Exception as exc:
                    logger.warning(
                        "listing_analyzer failed for project %d: %s", project_id, exc
                    )

                try:
                    review_clusters = fut_reviews.result()
                except Exception as exc:
                    logger.warning(
                        "review_analyzer failed for project %d: %s", project_id, exc
                    )

                try:
                    qa_entries = fut_qa.result()
                except Exception as exc:
                    logger.warning(
                        "qa_analyzer failed for project %d: %s", project_id, exc
                    )
        else:
            try:
                listing_result = _run_listing(proj.asin, asin_detail)
            except Exception as exc:
                logger.warning(
                    "listing_analyzer failed for project %d: %s", project_id, exc
                )
            try:
                review_clusters = _run_reviews(proj.asin)
            except Exception as exc:
                logger.warning(
                    "review_analyzer failed for project %d: %s", project_id, exc
                )
            try:
                qa_entries = _run_qa(proj.asin)
            except Exception as exc:
                logger.warning("qa_analyzer failed for project %d: %s", project_id, exc)

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
        try:
            from pipeline.models.price_analysis import PriceAnalysis

            session.query(PriceAnalysis).filter(
                PriceAnalysis.project_id == project_id,
            ).delete()
            pa = analyze_price(proj.asin, asin_detail, category_top)
            pa.project_id = project_id
            session.add(pa)
            session.commit()
            logger.info("price_analyzer complete for project %d", project_id)
        except Exception as exc:
            logger.warning("price_analyzer failed for project %d: %s", project_id, exc)

        try:
            from pipeline.models.promo_analysis import PromoAnalysis

            session.query(PromoAnalysis).filter(
                PromoAnalysis.project_id == project_id,
            ).delete()
            pra = analyze_promo(proj.asin, asin_detail or {})
            pra.project_id = project_id
            session.add(pra)
            session.commit()
            logger.info("promo_analyzer complete for project %d", project_id)
        except Exception as exc:
            logger.warning("promo_analyzer failed for project %d: %s", project_id, exc)

        # brief_generator (depends on all Phase 2 results)
        try:
            from pipeline.layers.brief_generator import generate_brief
            from pipeline.models.image_brief import ImageBrief

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

            if cl_for_brief is not None:
                session.query(ImageBrief).filter(
                    ImageBrief.project_id == project_id,
                ).delete()
                session.commit()

                briefs = generate_brief(
                    project_id=project_id,
                    competitor_listing=cl_for_brief,
                    review_clusters=review_clusters or [],
                    qa_entries=qa_entries or [],
                    session=session,
                )
                logger.info(
                    "brief_generator complete for project %d: %d slots",
                    project_id,
                    len(briefs),
                )
            else:
                logger.warning(
                    "brief_generator skipped: no CompetitorListing for project %d",
                    project_id,
                )
        except Exception as exc:
            logger.warning("brief_generator failed for project %d: %s", project_id, exc)

        # Persist benchmarks to DB so step_plan() can query them
        _bm_cols = {c.key for c in AmazonBenchmark.__table__.columns} - {
            "id",
            "created_at",
        }
        persisted = 0
        for bm in category_top or []:
            if isinstance(bm, dict):
                filtered = {k: v for k, v in bm.items() if k in _bm_cols}
                filtered["project_id"] = project_id
                if not filtered.get("competitor_asin"):
                    continue
                bm = AmazonBenchmark(**filtered)
            else:
                bm.project_id = project_id
            session.add(bm)
            persisted += 1
        session.commit()
        logger.info("Persisted %d benchmarks for project %d", persisted, project_id)

        # --- Phase 3: Vision analysis (parallel or sequential) ---
        vision_analyzed = 0
        benchmarks = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == project_id)
            .all()
        )
        bms_with_images = [bm for bm in benchmarks if bm.image_url]

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
                        vision_analyzed += 1
                    except Exception as exc:
                        logger.warning(
                            "Vision analysis failed for benchmark %d: %s", bm.id, exc
                        )
        else:
            for bm in bms_with_images:
                try:
                    result = _call_vision(bm.image_url)
                    bm.analysis = json.dumps(result)
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

        competitor_analysis = analyze_competitor_listing(proj.asin)
    finally:
        session.close()

    _update_status(project_id, "analyzed")
    logger.info("Analysis complete for project %d", project_id)
    return {
        "asin_detail": asin_detail,
        "category_top": category_top,
        "competitor_analysis": competitor_analysis,
        "vision_analyzed": vision_analyzed,
    }


def step_plan(project_id: int, analysis_results: dict | None = None) -> list:
    """Generate slot plan + seed PromptAssets. Sets status='planned'."""
    if analysis_results:
        logger.info(
            "step_plan received analysis_results keys: %s",
            list(analysis_results.keys()),
        )
    slots = generate_slot_plan(project_id)

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
            )
        except ValueError as exc:
            logger.warning(
                "Could not seed PromptAsset for slot %d: %s", slot.slot_index, exc
            )

    _update_status(project_id, "planned")
    logger.info("Slot plan generated for project %d: %d slots", project_id, len(slots))
    return slots


def step_generate(project_id: int, adapter_name: str = "gpt_image") -> dict[str, str]:
    """Generate prompts and run image adapter. Sets status='generated'."""
    from pipeline.models.prompt_asset import PromptAsset
    from pipeline.models.slot_plan import SlotPlan

    prompts = generate_slot_prompts(project_id)
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

        results = {}
        for slot_label, prompt_text in prompts.items():
            result = adapter.generate(prompt_text)
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
                    if asset:
                        asset.image_path = result.image_path

        session.commit()
    finally:
        session.close()

    _update_status(project_id, "generated")
    return results


_QA_MAX_RETRIES = 2
_QA_PASS_THRESHOLD = 70


def step_qa(project_id: int, adapter_name: str = "mock") -> list:
    """Run QA checks with retry loop. Max 2 retries per slot (3 total attempts)."""
    session = get_session()
    try:
        from pipeline.models.slot_plan import SlotPlan

        slots = session.query(SlotPlan).filter(SlotPlan.project_id == project_id).all()
        slot_ids = [s.id for s in slots]
    finally:
        session.close()

    all_records = []
    all_passed = True
    for slot_id in slot_ids:
        passed_slot = False
        for attempt in range(_QA_MAX_RETRIES + 1):
            records = run_qa_checks(slot_id)
            all_records.extend(records)

            slot_score = records[0].score if records else 0
            slot_passed = records[0].passed if records else False

            if slot_passed and slot_score >= _QA_PASS_THRESHOLD:
                passed_slot = True
                break

            if attempt < _QA_MAX_RETRIES:
                feedback = ""
                if records and records[0].details:
                    try:
                        details = json.loads(records[0].details)
                        feedback = "; ".join(details.get("issues", []))
                    except (json.JSONDecodeError, TypeError):
                        feedback = records[0].details
                logger.info(
                    "QA failed for slot %d (attempt %d/%d, score=%.0f), regenerating. Feedback: %s",
                    slot_id,
                    attempt + 1,
                    _QA_MAX_RETRIES + 1,
                    slot_score,
                    feedback,
                )
                try:
                    step_generate(project_id, adapter_name=adapter_name)
                except Exception as exc:
                    logger.warning("Regeneration failed for slot %d: %s", slot_id, exc)
                    break

        if not passed_slot:
            logger.warning(
                "QA failed for slot %d after %d attempts; continuing pipeline",
                slot_id,
                _QA_MAX_RETRIES + 1,
            )
            all_passed = False

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
    from pipeline.layers.delivery import build_delivery_package

    delivery_path = build_delivery_package(project_id)
    if not delivery_path or not any(Path(delivery_path).iterdir()):
        logger.warning(
            "step_deliver: empty or missing delivery package for project %d",
            project_id,
        )
        return None
    logger.info("Delivery package built for project %d: %s", project_id, delivery_path)
    return delivery_path


def step_feedback(project_id: int, session=None) -> None:
    """Run feedback loop to update BrandProfile from pipeline results.

    Skips silently if no BrandProfile exists for the project.
    """
    from pipeline.layers.feedback_loop import update_brand_profile_from_results
    from pipeline.models.brand import BrandProfile

    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        brand = session.query(BrandProfile).filter_by(project_id=project_id).first()
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
        step_plan(project_id, analysis_results=analysis_results)
        step_generate(project_id, adapter_name)
        step_qa(project_id, adapter_name=adapter_name)
        report = step_report(project_id)
        delivery_path = step_deliver(project_id)
        step_feedback(project_id)
        return {
            "project_id": project_id,
            "status": "completed",
            "report": report,
            "delivery_path": delivery_path,
        }
    except Exception:
        _update_status(project_id, "failed")
        raise
