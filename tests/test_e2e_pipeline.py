"""E2E integration tests for the full image pipeline.

Covers: brief → plan → prompt → deliver → feedback,
plus a degraded-mode (no API key) full-chain test.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config  # noqa: E402

_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="e2e_pipeline_")
config.db_path = _tmp_db
config.output_dir = _tmp_out

from pipeline.models import base as base_mod  # noqa: E402
from pipeline.models.base import Base, get_session  # noqa: E402

# Import all models before create_all so their tables are registered
from pipeline.models.ab_test_result import ABTestResult  # noqa: E402
from pipeline.models.benchmark import AmazonBenchmark  # noqa: E402
from pipeline.models.brand_profile import BrandProfile  # noqa: E402
from pipeline.models.competitor_listing import CompetitorListing  # noqa: E402
from pipeline.models.image_brief import ImageBrief  # noqa: E402
from pipeline.models.project import Project  # noqa: E402
from pipeline.models.qa_entry import QAEntry  # noqa: E402
from pipeline.models.review_cluster import ReviewCluster  # noqa: E402

base_mod._engine = create_engine(f"sqlite:///{_tmp_db}", echo=False)
base_mod._SessionLocal = None
Base.metadata.create_all(base_mod._engine)

from pipeline.layers.brief_generator import generate_brief  # noqa: E402
from pipeline.layers.delivery import build_delivery_package  # noqa: E402
from pipeline.layers.feedback_loop import (  # noqa: E402
    export_conclusions,
    record_ab_result,
)
from pipeline.layers.prompt_engine import build_prompt  # noqa: E402
from pipeline.layers.slot_planner import generate_slot_plan  # noqa: E402

# ---------------------------------------------------------------------------

_SAMPLE_BRIEF_JSON = json.dumps(
    {
        "hero_angle": "45-degree top-down",
        "lighting": "soft studio",
        "background": "white seamless",
        "props": ["lifestyle context"],
        "tags": ["hero", "lifestyle"],
    }
)


def _seed_project(session) -> int:
    proj = Project(
        name="E2E Test Product", asin="B000TEST01", category="Home", status="active"
    )
    session.add(proj)
    session.flush()
    pid = proj.id

    session.add(
        CompetitorListing(
            asin="B000COMP01",
            title="Competitor Widget",
            bullet_points="Great quality\nFast shipping",
            description="A competitor product for testing.",
            project_id=pid,
        )
    )
    session.add(
        ReviewCluster(
            asin="B000TEST01",
            cluster_label="quality",
            sentiment="positive",
            count=42,
            representative_reviews="Love this product",
            project_id=pid,
        )
    )
    session.add(
        QAEntry(
            asin="B000TEST01",
            question="Is it durable?",
            answer="Yes, very durable.",
            frequency=10,
            category="durability",
            project_id=pid,
        )
    )

    for idx in range(8):
        session.add(
            AmazonBenchmark(
                project_id=pid,
                competitor_asin="B000COMP01",
                slot_index=idx,
                image_url=f"https://example.com/img_{idx}.jpg",
                analysis=f"Benchmark analysis for slot {idx}",
                score=0.8,
            )
        )

    for idx in range(8):
        session.add(
            ImageBrief(
                project_id=pid,
                slot_index=idx,
                brief_json=_SAMPLE_BRIEF_JSON,
                source_analysis_ids="[]",
            )
        )

    session.add(
        BrandProfile(
            project_id=pid,
            brand_tone="professional",
            color_system="#FFFFFF,#000000",
            font_preference="Helvetica",
            guidelines="{}",
        )
    )

    session.commit()
    return pid


@pytest.fixture(scope="module")
def project_id():
    s = get_session()
    try:
        pid = _seed_project(s)
    finally:
        s.close()
    return pid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateBrief:
    def test_returns_image_brief(self, project_id):
        s = get_session()
        try:
            comp = s.query(CompetitorListing).filter_by(project_id=project_id).first()
            clusters = s.query(ReviewCluster).filter_by(project_id=project_id).all()
            qa = s.query(QAEntry).filter_by(project_id=project_id).all()
        finally:
            s.close()

        brief = generate_brief(project_id, comp, clusters, qa)
        assert isinstance(brief, list)
        assert len(brief) >= 1
        assert isinstance(brief[0], ImageBrief)
        assert brief[0].project_id == project_id
        parsed = json.loads(brief[0].brief_json)
        assert isinstance(parsed, dict)


class TestSlotPlanner:
    def test_returns_eight_plans(self, project_id):
        plans = generate_slot_plan(project_id)
        assert isinstance(plans, list)
        assert len(plans) == 8
        indices = {p.slot_index for p in plans}
        assert indices == set(range(1, 9))


class TestPromptEngine:
    def test_build_prompt_slot_zero(self, project_id):
        prompt = build_prompt(project_id, slot_index=0)
        assert isinstance(prompt, str)
        assert len(prompt) > 10


class TestDelivery:
    def test_build_delivery_creates_manifest(self, project_id):
        delivery_dir = build_delivery_package(project_id)
        assert os.path.isdir(delivery_dir)
        manifest_path = os.path.join(delivery_dir, "manifest.json")
        assert os.path.isfile(manifest_path)
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert isinstance(manifest, dict)
        assert manifest["project_id"] == project_id


class TestFeedbackLoop:
    def test_record_and_export(self, project_id):
        for slot_idx in range(3):
            record_ab_result(
                project_id, slot_idx, variant="A", score=0.75 + slot_idx * 0.05
            )
            record_ab_result(
                project_id, slot_idx, variant="B", score=0.65 + slot_idx * 0.05
            )

        conclusions = export_conclusions(project_id)
        assert isinstance(conclusions, dict)
        assert conclusions["project_id"] == project_id
        assert conclusions["total_tests"] >= 6


class TestDegradedFullChain:
    def test_full_chain_no_api_key(self):
        old_key = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            s = get_session()
            try:
                pid = _seed_project(s)
            finally:
                s.close()

            # 1. Brief (falls back to _DEFAULT_BRIEF)
            s = get_session()
            try:
                comp = s.query(CompetitorListing).filter_by(project_id=pid).first()
                clusters = s.query(ReviewCluster).filter_by(project_id=pid).all()
                qa = s.query(QAEntry).filter_by(project_id=pid).all()
            finally:
                s.close()

            brief = generate_brief(pid, comp, clusters, qa)
            assert isinstance(brief, list)
            assert len(brief) >= 1

            # 2. Slot plan
            plans = generate_slot_plan(pid)
            assert len(plans) == 8

            # 3. Prompt
            prompt = build_prompt(pid, slot_index=0)
            assert len(prompt) > 0

            # 4. Delivery
            delivery_dir = build_delivery_package(pid)
            assert os.path.isdir(delivery_dir)

            # 5. Feedback
            record_ab_result(pid, 0, "A", 0.9)
            conclusions = export_conclusions(pid)
            assert conclusions["project_id"] == pid

        finally:
            if old_key is not None:
                os.environ["GOOGLE_API_KEY"] = old_key
