from __future__ import annotations

import json
from typing import Optional

from pipeline.models.base import get_session
from pipeline.models.project import Project
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.reference_pack import ReferencePack

__all__ = ["build_reference_pack", "get_reference_pack"]


def build_reference_pack(project_id: int) -> ReferencePack:
    session = get_session()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"E_REFPACK_001: project {project_id} not found")

        product_truth = _build_product_truth(project)
        brand_rules = _build_brand_rules(session, project_id)
        winning_examples = _build_winning_examples(session, project_id)
        competitor_baseline = _build_competitor_baseline(session, project_id)
        negative_cases = _build_negative_cases(session, project_id)
        angle_matrix = _build_angle_matrix(
            product_truth, brand_rules, winning_examples, competitor_baseline
        )

        rp = (
            session.query(ReferencePack)
            .filter(ReferencePack.project_id == project_id)
            .first()
        )
        if rp is None:
            rp = ReferencePack(project_id=project_id)
            session.add(rp)

        rp.product_truth = json.dumps(product_truth, ensure_ascii=False)
        rp.brand_rules = json.dumps(brand_rules, ensure_ascii=False)
        rp.winning_examples = json.dumps(winning_examples, ensure_ascii=False)
        rp.competitor_baseline = json.dumps(competitor_baseline, ensure_ascii=False)
        rp.negative_cases = json.dumps(negative_cases, ensure_ascii=False)
        rp.angle_matrix = json.dumps(angle_matrix, ensure_ascii=False)

        session.commit()
        session.refresh(rp)
        session.expunge(rp)
        return rp
    finally:
        session.close()


def get_reference_pack(project_id: int) -> Optional[ReferencePack]:
    session = get_session()
    try:
        rp = (
            session.query(ReferencePack)
            .filter(ReferencePack.project_id == project_id)
            .first()
        )
        if rp is not None:
            session.expunge(rp)
        return rp
    finally:
        session.close()


def _build_product_truth(project: Project) -> dict:
    brief = {}
    if project.customer_brief:
        try:
            brief = json.loads(project.customer_brief)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "name": project.name or "",
        "asin": project.asin or "",
        "category": project.category or "",
        "customer_brief_summary": brief,
    }


def _build_brand_rules(session, project_id: int) -> dict:
    bp = session.query(BrandProfile).filter_by(project_id=project_id).first()
    if bp is None:
        return {"tone": "", "color_system": "", "photo_style": ""}
    return {
        "tone": bp.brand_tone or "",
        "color_system": bp.color_system or "",
        "font_preference": bp.font_preference or "",
        "photo_style": bp.photo_style or "",
        "model_type": bp.model_type or "",
        "scene_preference": bp.scene_preference or "",
        "composition_preference": bp.composition_preference or "",
        "material_texture": bp.material_texture or "",
    }


def _build_winning_examples(session, project_id: int) -> list[dict]:
    clusters = (
        session.query(ReviewCluster)
        .filter(
            ReviewCluster.project_id == project_id,
            ReviewCluster.sentiment == "positive",
        )
        .order_by(ReviewCluster.count.desc())
        .all()
    )
    return [
        {
            "label": rc.cluster_label or "",
            "count": rc.count or 0,
            "representative": rc.representative_reviews or "",
        }
        for rc in clusters
    ] or [{"label": "none", "count": 0, "representative": ""}]


def _build_competitor_baseline(session, project_id: int) -> list[dict]:
    benchmarks = (
        session.query(AmazonBenchmark)
        .filter(AmazonBenchmark.project_id == project_id)
        .all()
    )
    competitors = (
        session.query(CompetitorListing)
        .filter(CompetitorListing.project_id == project_id)
        .all()
    )
    result = []
    for bm in benchmarks:
        result.append(
            {
                "asin": bm.competitor_asin or "",
                "slot_index": bm.slot_index,
                "score": bm.score,
                "analysis": bm.analysis or "",
            }
        )
    for comp in competitors:
        result.append(
            {
                "asin": comp.asin or "",
                "title": comp.title or "",
                "selling_points": comp.bullet_points or "",
            }
        )
    return result or [{"asin": "", "analysis": "no competitor data"}]


def _build_negative_cases(session, project_id: int) -> list[dict]:
    clusters = (
        session.query(ReviewCluster)
        .filter(
            ReviewCluster.project_id == project_id,
            ReviewCluster.sentiment == "negative",
        )
        .all()
    )
    return [
        {
            "issue": rc.cluster_label or "",
            "count": rc.count or 0,
            "representative": rc.representative_reviews or "",
        }
        for rc in clusters
    ] or [{"issue": "none", "count": 0, "representative": ""}]


def _build_angle_matrix(
    product_truth: dict,
    brand_rules: dict,
    winning_examples: list,
    competitor_baseline: list,
) -> dict:
    angles = []
    if product_truth.get("category"):
        angles.append(f"category:{product_truth['category']}")
    if brand_rules.get("tone"):
        angles.append(f"tone:{brand_rules['tone']}")
    for we in winning_examples:
        if we.get("label") and we["label"] != "none":
            angles.append(f"strength:{we['label']}")
    for cb in competitor_baseline:
        if cb.get("asin"):
            angles.append(f"vs:{cb['asin']}")
    return {"angles": angles or ["default"]}
