"""Feedback loop: A/B test recording, delivery results, category insights, project reports."""

from __future__ import annotations

import json
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.models.base import Base, get_session
from pipeline.models.ab_test import ABTest
from pipeline.models.ab_test_result import ABTestResult
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.qa_record import QARecord
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.product_profile import ProductProfile
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.feedback_loop")

__all__ = [
    "record_ab_test",
    "record_ab_result",
    "record_delivery_result",
    "get_category_insights",
    "update_brand_profile_from_results",
    "update_brand_elastic_from_flywheel",
    "export_conclusions",
    "export_project_report",
    "sync_qa_statuses",
]

_ELASTIC_FIELDS = (
    "photo_style",
    "model_type",
    "scene_preference",
    "composition_preference",
    "material_texture",
)


def record_ab_test(
    project_id: int,
    slot_index: int,
    variant_a_id: int,
    variant_b_id: int,
    winner: str | None = None,
    metric: str = "CTR",
    score_a: float | None = None,
    score_b: float | None = None,
    notes: str = "",
) -> ABTest:
    """Record an A/B test between two prompt asset variants.

    Validates that both variant IDs exist as PromptAsset rows.
    Returns the created ABTest row.

    Raises:
        ValueError: E_FEEDBACK_001 if variant PromptAsset not found.
    """
    session = get_session()
    try:
        for label, vid in [
            ("variant_a_id", variant_a_id),
            ("variant_b_id", variant_b_id),
        ]:
            asset = session.get(PromptAsset, vid)
            if asset is None:
                raise ValueError(
                    f"E_FEEDBACK_001: PromptAsset with id={vid} ({label}) not found."
                )

        ab = ABTest(
            project_id=project_id,
            slot_index=slot_index,
            variant_a_id=variant_a_id,
            variant_b_id=variant_b_id,
            winner=winner,
            metric=metric,
            score_a=score_a,
            score_b=score_b,
            notes=notes,
        )
        session.add(ab)
        session.commit()
        session.refresh(ab)
        session.expunge(ab)
        logger.info(
            "Recorded AB test id=%s for project=%s slot=%s",
            ab.id,
            project_id,
            slot_index,
        )
        return ab
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def record_delivery_result(project_id: int, slot_index: int, result: dict) -> None:
    """Store delivery feedback as an ABTest record with metric='DELIVERY'.

    The result dict is serialised to JSON and stored in the notes field.
    """
    session = get_session()
    try:
        ab = ABTest(
            project_id=project_id,
            slot_index=slot_index,
            variant_a_id=None,
            variant_b_id=None,
            metric="DELIVERY",
            notes=json.dumps(result, ensure_ascii=False),
        )
        session.add(ab)
        session.commit()
        logger.info(
            "Recorded delivery result for project=%s slot=%s", project_id, slot_index
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_category_insights(category: str) -> dict:
    """Aggregate insights for a product category.

    Returns dict with keys:
        avg_qa_pass_rate, top_intent_tags, ab_win_patterns, project_count.
    """
    session = get_session()
    try:
        projects = session.query(Project).filter(Project.category == category).all()
        project_ids = [p.id for p in projects]

        if not project_ids:
            return {
                "avg_qa_pass_rate": 0.0,
                "top_intent_tags": [],
                "ab_win_patterns": {},
                "project_count": 0,
            }

        assets = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id.in_(project_ids))
            .all()
        )
        asset_ids = [a.id for a in assets]

        qa_pass_rate = 0.0
        if asset_ids:
            records = (
                session.query(QARecord)
                .filter(QARecord.prompt_asset_id.in_(asset_ids))
                .all()
            )
            if records:
                qa_pass_rate = sum(r.passed for r in records) / len(records)

        slots = (
            session.query(SlotPlan).filter(SlotPlan.project_id.in_(project_ids)).all()
        )
        tag_counter: Counter[str] = Counter()
        for s in slots:
            if s.intent_tag:
                tag_counter[s.intent_tag] += 1
        top_intent_tags = [tag for tag, _ in tag_counter.most_common(10)]

        ab_tests = (
            session.query(ABTest)
            .filter(ABTest.project_id.in_(project_ids), ABTest.metric != "DELIVERY")
            .all()
        )
        win_counter: Counter[str] = Counter()
        for t in ab_tests:
            if t.winner:
                win_counter[t.winner] += 1

        return {
            "avg_qa_pass_rate": round(qa_pass_rate, 4),
            "top_intent_tags": top_intent_tags,
            "ab_win_patterns": dict(win_counter),
            "project_count": len(project_ids),
        }
    finally:
        session.close()


def export_project_report(project_id: int) -> dict:
    """Export a comprehensive report for a project.

    Raises:
        ValueError: E_FEEDBACK_002 if project not found.
    """
    session = get_session()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"E_FEEDBACK_002: Project with id={project_id} not found.")

        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        brand = None
        if pp and pp.brand_profile_id:
            brand = (
                session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
            )
        benchmarks = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == project_id)
            .all()
        )
        slot_plans = (
            session.query(SlotPlan).filter(SlotPlan.project_id == project_id).all()
        )
        assets = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == project_id)
            .all()
        )
        asset_ids = [a.id for a in assets]
        qa_records = (
            session.query(QARecord)
            .filter(QARecord.prompt_asset_id.in_(asset_ids))
            .all()
            if asset_ids
            else []
        )
        ab_tests = session.query(ABTest).filter(ABTest.project_id == project_id).all()

        def _row_to_dict(row: Base) -> dict:
            d = {}
            for c in row.__table__.columns:
                v = getattr(row, c.name)
                if hasattr(v, "isoformat"):
                    v = v.isoformat()
                d[c.name] = v
            return d

        report = {
            "project": _row_to_dict(project),
            "brand_profile": _row_to_dict(brand) if brand else None,
            "benchmarks": [_row_to_dict(b) for b in benchmarks],
            "slot_plans": [_row_to_dict(s) for s in slot_plans],
            "prompt_assets": [_row_to_dict(a) for a in assets],
            "qa_records": [_row_to_dict(q) for q in qa_records],
            "ab_tests": [_row_to_dict(t) for t in ab_tests],
        }
        logger.info("Exported report for project=%s (%s)", project_id, project.name)
        return report
    finally:
        session.close()


def record_ab_result(
    project_id: int,
    slot_index: int,
    variant: str,
    score: float,
    session: Optional[Session] = None,
) -> ABTestResult:
    """Persist a single A/B test result row.

    Uses the owns_session pattern so callers can optionally pass their own
    session for batching.
    """
    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        row = ABTestResult(
            project_id=project_id,
            slot_index=slot_index,
            variant=variant,
            score=score,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        logger.info(
            "Recorded ABTestResult id=%s project=%s variant=%s score=%s",
            row.id,
            project_id,
            variant,
            score,
        )
        return row
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def update_brand_profile_from_results(
    project_id: int, session: Optional[Session] = None
) -> BrandProfile | None:
    """Average ABTestResult scores by variant and store conclusion in BrandProfile.ab_conclusions.

    Lookup path: project → ProductProfile → BrandProfile (project_id 字段已废弃).
    Returns the updated BrandProfile or None if no brand profile exists.
    """
    from pipeline.models.product_profile import ProductProfile

    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        results = (
            session.query(ABTestResult)
            .filter(ABTestResult.project_id == project_id)
            .all()
        )

        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        brand: BrandProfile | None = None
        if pp and pp.brand_profile_id:
            brand = (
                session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
            )

        if not results:
            return brand

        variant_scores: dict[str, list[float]] = {}
        for r in results:
            variant_scores.setdefault(r.variant, []).append(r.score)

        averages = {v: sum(s) / len(s) for v, s in variant_scores.items()}
        best = max(averages, key=averages.get)  # type: ignore[arg-type]

        conclusion = json.dumps(
            {"variant_averages": averages, "best_variant": best},
            ensure_ascii=False,
        )

        if brand is None:
            logger.warning("No BrandProfile for project=%s; cannot update.", project_id)
            return None

        brand.ab_conclusions = conclusion
        session.commit()
        session.refresh(brand)
        logger.info(
            "Updated BrandProfile id=%s ab_conclusions with best_variant=%s",
            brand.id,
            best,
        )
        update_brand_elastic_from_flywheel(project_id, session=session)
        return brand
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def update_brand_elastic_from_flywheel(
    project_id: int, session: Optional[Session] = None
) -> BrandProfile | None:
    """用飞轮好图的 visual_tags 众数回写 BrandProfile 的 ELASTIC 字段。

    查询该项目所有已入飞轮的 PromptAsset.visual_tags（JSON），对每个 ELASTIC 字段
    取出现次数最多的值写回 BrandProfile。若某字段在所有 visual_tags 中均无数据则跳过。
    """
    from pipeline.models.flywheel_example import FlywheelExample

    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        brand: BrandProfile | None = None
        if pp and pp.brand_profile_id:
            brand = (
                session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
            )
        if brand is None:
            return None

        flywheel_asset_ids = [
            row.prompt_asset_id
            for row in session.query(FlywheelExample.prompt_asset_id)
            .filter(FlywheelExample.project_id == project_id)
            .all()
        ]
        if not flywheel_asset_ids:
            return brand

        assets_with_tags = (
            session.query(PromptAsset)
            .filter(
                PromptAsset.id.in_(flywheel_asset_ids),
                PromptAsset.visual_tags.isnot(None),
            )
            .all()
        )

        field_counters: dict[str, Counter] = {f: Counter() for f in _ELASTIC_FIELDS}
        for asset in assets_with_tags:
            try:
                tags: dict = json.loads(asset.visual_tags)
            except (json.JSONDecodeError, TypeError):
                continue
            for field in _ELASTIC_FIELDS:
                value = tags.get(field)
                if value:
                    field_counters[field][str(value)] += 1

        updated_fields = []
        for field, counter in field_counters.items():
            if not counter:
                continue
            most_common_value = counter.most_common(1)[0][0]
            setattr(brand, field, most_common_value)
            updated_fields.append(field)

        if updated_fields:
            session.commit()
            session.refresh(brand)
            logger.info(
                "ELASTIC 字段已更新 BrandProfile id=%s fields=%s",
                brand.id,
                updated_fields,
            )
        return brand
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def export_conclusions(project_id: int, session: Optional[Session] = None) -> dict:
    """Export a summary dict of A/B test conclusions for *project_id*.

    Returns dict with keys: project_id, total_tests, best_variant, avg_score, results.
    """
    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        results = (
            session.query(ABTestResult)
            .filter(ABTestResult.project_id == project_id)
            .all()
        )

        if not results:
            return {
                "project_id": project_id,
                "total_tests": 0,
                "best_variant": None,
                "avg_score": 0.0,
                "results": [],
            }

        variant_scores: dict[str, list[float]] = {}
        for r in results:
            variant_scores.setdefault(r.variant, []).append(r.score)

        averages = {v: sum(s) / len(s) for v, s in variant_scores.items()}
        best = max(averages, key=averages.get)  # type: ignore[arg-type]
        overall_avg = sum(r.score for r in results) / len(results)

        return {
            "project_id": project_id,
            "total_tests": len(results),
            "best_variant": best,
            "avg_score": round(overall_avg, 4),
            "results": [
                {
                    "id": r.id,
                    "slot_index": r.slot_index,
                    "variant": r.variant,
                    "score": r.score,
                }
                for r in results
            ],
        }
    finally:
        if owns_session:
            session.close()


def sync_qa_statuses(project_id: int, session: Optional[Session] = None) -> None:
    from pipeline.models.aplus_content import APlusContent

    owns_session = False
    if session is None:
        session = get_session()
        owns_session = True
    try:
        assets = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == project_id)
            .all()
        )
        for asset in assets:
            passed_rec = (
                session.query(QARecord)
                .filter(
                    QARecord.prompt_asset_id == asset.id,
                    QARecord.passed == 1,
                )
                .first()
            )
            if asset.status not in {"final", "concept_only", "failed"}:
                asset.status = "qa_passed" if passed_rec is not None else "qa_failed"

        aplus_list = (
            session.query(APlusContent)
            .filter(APlusContent.project_id == project_id)
            .all()
        )
        for ac in aplus_list:
            if ac.qa_passed is None:
                ac.qa_passed = False

        proj = session.get(Project, project_id)
        if proj is not None:
            proj.status = "delivered"

        session.commit()
        logger.info("sync_qa_statuses 完成 project=%d", project_id)
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
