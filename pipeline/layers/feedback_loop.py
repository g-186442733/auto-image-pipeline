"""Feedback loop: A/B test recording, delivery results, category insights, project reports."""

from __future__ import annotations

import json
from collections import Counter

from pipeline.models.base import Base, get_session
from pipeline.models.ab_test import ABTest
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.qa_record import QARecord
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.brand import BrandProfile
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.feedback_loop")

__all__ = [
    "record_ab_test",
    "record_delivery_result",
    "get_category_insights",
    "export_project_report",
]


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

        brand = (
            session.query(BrandProfile)
            .filter(BrandProfile.project_id == project_id)
            .first()
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
