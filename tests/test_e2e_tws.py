"""T16 — TWS Earphone end-to-end validation.

Tests the full pipeline: create project → analyze → plan → generate → QA → report.
External APIs (Keepa, OpenAI Vision) are mocked. Uses a temp SQLite DB.
"""

import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from unittest import mock

import pytest

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config

# ── Temp DB + output dir setup (BEFORE any model import) ────────────────
_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="aip_e2e_")
config.db_path = _tmp_db
config.output_dir = _tmp_out
config.keepa_api_key = "test-keepa-key"
config.openai_api_key = "test-openai-key"

from sqlalchemy import create_engine
from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session

base_mod._engine = create_engine(f"sqlite:///{_tmp_db}")
base_mod._SessionLocal = None
Base.metadata.create_all(base_mod._engine)

from pipeline.models.project import Project
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord

from pipeline.orchestrator import (
    step_init,
    step_analyze,
    step_plan,
    step_generate,
    step_qa,
    step_report,
    run_full_pipeline,
)


# ── Restore config after this module to avoid polluting other test files ──
@pytest.fixture(scope="module", autouse=True)
def _restore_config_after_module():
    yield
    config.keepa_api_key = None
    config.openai_api_key = None


# ── Helpers ──────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
BRIEF_PATH = str(FIXTURES / "tws_brief.json")
BENCHMARK_PATH = str(FIXTURES / "tws_benchmark.json")


def _minimal_png(w: int = 1600, h: int = 1600) -> bytes:
    """Minimal valid white PNG."""

    def _chunk(ct: bytes, data: bytes) -> bytes:
        c = ct + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    row = b"\x00" + b"\xff" * (w * 3)
    raw = b"".join(row for _ in range(h))
    idat = _chunk(b"IDAT", zlib.compress(raw, 1))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _insert_benchmarks(project_id: int) -> None:
    """Insert mock AmazonBenchmark rows from fixture file."""
    benchmarks = json.loads(Path(BENCHMARK_PATH).read_text())
    session = get_session()
    for b in benchmarks:
        session.add(AmazonBenchmark(project_id=project_id, **b))
    session.commit()
    session.close()


def _insert_prompt_assets(project_id: int) -> None:
    """Insert PromptAsset for each slot (1-8) with a mock image_path."""
    session = get_session()
    for slot_idx in range(1, 9):
        img_dir = Path(_tmp_out) / "mock"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / f"e2e_proj{project_id}_slot{slot_idx}.png"
        img_path.write_bytes(_minimal_png())

        pa = PromptAsset(
            project_id=project_id,
            slot_index=slot_idx,
            prompt_text="TWS earphone {{ composition }} {{ subject }}",
            negative_prompt="blurry, watermark",
            model_name="mock",
            version=1,
            image_path=str(img_path),
        )
        session.add(pa)
    session.commit()
    session.close()


def _mock_fetch_asin_detail(asin: str) -> dict:
    return {
        "asin": asin,
        "title": "TWS Earphone Test Product",
        "price": 29.99,
        "rating": 4.5,
        "images": ["https://example.com/img1.jpg"],
    }


def _mock_fetch_category_top(category: str) -> list[dict]:
    return [
        {"asin": "B0COMP00AA", "title": "Top Competitor 1", "rank": 1},
        {"asin": "B0COMP00BB", "title": "Top Competitor 2", "rank": 2},
    ]


def _mock_analyze_competitor(asin: str) -> list[dict]:
    """Mock competitor analysis — also inserts AmazonBenchmark via side effect."""
    # The real function writes to DB; we handle that in the test setup instead.
    return [
        {"competitor_asin": "B0COMP00AA", "score": 88.0, "analysis": "mock analysis"},
    ]


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def project():
    """Create a project from the TWS brief fixture."""
    proj = step_init(BRIEF_PATH)
    return proj


# ── Tests: step-by-step pipeline ─────────────────────────────────────────


class TestStepByStep:
    """Test each orchestrator step individually."""

    def test_step_init(self, project):
        assert project.id is not None
        assert project.name == "TWS Earphone Launch"
        assert project.asin == "B0TWS00001"
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status == "initialized"
        session.close()

    @mock.patch("pipeline.orchestrator.config")
    @mock.patch(
        "pipeline.orchestrator.analyze_competitor_listing",
        side_effect=_mock_analyze_competitor,
    )
    @mock.patch(
        "pipeline.orchestrator.fetch_category_top",
        side_effect=_mock_fetch_category_top,
    )
    @mock.patch(
        "pipeline.orchestrator.fetch_asin_detail",
        side_effect=_mock_fetch_asin_detail,
    )
    def test_step_analyze(self, mock_asin, mock_cat, mock_vision, mock_config, project):
        mock_config.keepa_api_key = "fake-key"
        mock_config.openai_api_key = "fake-key"
        mock_config.parallel_analyze = False
        # Insert benchmarks (simulating what analyze_competitor_listing writes to DB)
        _insert_benchmarks(project.id)

        # Patch the orchestrator imports
        with (
            mock.patch(
                "pipeline.orchestrator.fetch_asin_detail",
                side_effect=_mock_fetch_asin_detail,
            ),
            mock.patch(
                "pipeline.orchestrator.fetch_category_top",
                side_effect=_mock_fetch_category_top,
            ),
            mock.patch(
                "pipeline.orchestrator.analyze_competitor_listing",
                side_effect=_mock_analyze_competitor,
            ),
        ):
            result = step_analyze(project.id)

        assert "asin_detail" in result
        assert result["asin_detail"]["asin"] == "B0TWS00001"
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status == "analyzed"
        session.close()

    def test_step_plan(self, project):
        # Prerequisites: benchmarks must exist
        _insert_benchmarks(project.id)
        slots = step_plan(project.id)
        assert len(slots) == 8
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status == "planned"
        db_slots = (
            session.query(SlotPlan).filter(SlotPlan.project_id == project.id).all()
        )
        assert len(db_slots) == 8
        session.close()

    def test_step_generate(self, project):
        # Prerequisites
        _insert_benchmarks(project.id)
        step_plan(project.id)
        _insert_prompt_assets(project.id)

        results = step_generate(project.id, adapter_name="mock")
        assert len(results) > 0
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status == "generated"
        session.close()

    @mock.patch("pipeline.layers.qa_gate.httpx.post")
    def test_step_qa(self, mock_post, project):
        # Mock the Vision API response for check_text_overlay
        mock_post.return_value = mock.MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": '{"has_text": false}'}}]},
        )
        # Full setup for QA
        _insert_benchmarks(project.id)
        step_plan(project.id)
        _insert_prompt_assets(project.id)
        step_generate(project.id, adapter_name="mock")

        # QA checks need image_path on PromptAsset — already set by _insert_prompt_assets
        records = step_qa(project.id)
        assert len(records) > 0
        # Each slot gets 4 checks
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status in ("qa_passed", "qa_failed")
        session.close()

    @mock.patch("pipeline.layers.qa_gate.httpx.post")
    def test_step_report(self, mock_post, project):
        # Mock the Vision API response for check_text_overlay
        mock_post.return_value = mock.MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": '{"has_text": false}'}}]},
        )
        # Full chain
        _insert_benchmarks(project.id)
        step_plan(project.id)
        _insert_prompt_assets(project.id)
        step_generate(project.id, adapter_name="mock")
        step_qa(project.id)

        report = step_report(project.id)
        assert report["project"]["name"] == "TWS Earphone Launch"
        session = get_session()
        db_proj = session.get(Project, project.id)
        assert db_proj.status == "completed"
        session.close()


# ── Tests: full pipeline (run_full_pipeline) ─────────────────────────────


class TestFullPipeline:
    """Test run_full_pipeline with all external calls mocked."""

    def test_full_pipeline_completes(self):
        """Full pipeline runs to 'completed' with mocked externals."""
        call_count = {"analyze": 0}

        def _patched_analyze(project_id: int) -> dict:
            """Mock step_analyze: insert benchmarks + return mock data."""
            call_count["analyze"] += 1
            _insert_benchmarks(project_id)
            from pipeline.orchestrator import _update_status

            _update_status(project_id, "analyzed")
            return {
                "asin_detail": _mock_fetch_asin_detail("B0TWS00001"),
                "category_top": _mock_fetch_category_top("TWS earphone"),
                "competitor_analysis": _mock_analyze_competitor("B0TWS00001"),
            }

        def _patched_generate(project_id: int, adapter_name: str = "mock") -> dict:
            """Mock step_generate: insert PromptAssets + call real generate."""
            _insert_prompt_assets(project_id)
            # Now call the real generate logic
            from pipeline.layers.prompt_engine import generate_slot_prompts
            from pipeline.adapters.registry import get_adapter
            from pipeline.orchestrator import _update_status

            prompts = generate_slot_prompts(project_id)
            adapter = get_adapter(adapter_name)
            results = {}
            for slot_label, prompt_text in prompts.items():
                result = adapter.generate(prompt_text)
                results[slot_label] = result
            _update_status(project_id, "generated")
            return results

        _vision_resp = mock.MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": '{"has_text": false}'}}]},
        )
        with (
            mock.patch(
                "pipeline.orchestrator.step_analyze", side_effect=_patched_analyze
            ),
            mock.patch(
                "pipeline.orchestrator.step_generate", side_effect=_patched_generate
            ),
            mock.patch("pipeline.layers.qa_gate.httpx.post", return_value=_vision_resp),
        ):
            result = run_full_pipeline(BRIEF_PATH, adapter_name="mock")

        assert result["status"] == "completed"
        assert result["project_id"] is not None
        assert "report" in result
        assert result["report"]["project"]["name"] == "TWS Earphone Launch"

        session = get_session()
        proj = session.get(Project, result["project_id"])
        assert proj.status == "completed"
        slots = session.query(SlotPlan).filter(SlotPlan.project_id == proj.id).count()
        assert slots == 8
        assets = (
            session.query(PromptAsset).filter(PromptAsset.project_id == proj.id).count()
        )
        assert assets >= 8
        qa_recs = (
            session.query(QARecord)
            .join(PromptAsset, QARecord.prompt_asset_id == PromptAsset.id)
            .filter(PromptAsset.project_id == proj.id)
            .count()
        )
        assert qa_recs > 0
        session.close()

    def test_full_pipeline_db_records_complete(self):
        """Verify every stage produces expected DB artifacts."""

        def _patched_analyze(project_id: int) -> dict:
            _insert_benchmarks(project_id)
            from pipeline.orchestrator import _update_status

            _update_status(project_id, "analyzed")
            return {"asin_detail": {}, "category_top": [], "competitor_analysis": []}

        def _patched_generate(project_id: int, adapter_name: str = "mock") -> dict:
            _insert_prompt_assets(project_id)
            from pipeline.layers.prompt_engine import generate_slot_prompts
            from pipeline.adapters.registry import get_adapter
            from pipeline.orchestrator import _update_status

            prompts = generate_slot_prompts(project_id)
            adapter = get_adapter(adapter_name)
            results = {}
            for label, text in prompts.items():
                results[label] = adapter.generate(text)
            _update_status(project_id, "generated")
            return results

        _vision_resp = mock.MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": '{"has_text": false}'}}]},
        )
        with (
            mock.patch(
                "pipeline.orchestrator.step_analyze", side_effect=_patched_analyze
            ),
            mock.patch(
                "pipeline.orchestrator.step_generate", side_effect=_patched_generate
            ),
            mock.patch("pipeline.layers.qa_gate.httpx.post", return_value=_vision_resp),
        ):
            result = run_full_pipeline(BRIEF_PATH, adapter_name="mock")

        pid = result["project_id"]
        session = get_session()

        # Project exists with final status
        proj = session.get(Project, pid)
        assert proj is not None
        assert proj.status == "completed"

        # 8 SlotPlans
        sp_count = session.query(SlotPlan).filter(SlotPlan.project_id == pid).count()
        assert sp_count == 8

        # 8 PromptAssets with image_path set (step_plan seeds placeholders without image_path)
        pa_list = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == pid, PromptAsset.image_path.isnot(None))
            .all()
        )
        assert len(pa_list) >= 8

        # QA records exist for each slot
        qa_count = (
            session.query(QARecord)
            .join(PromptAsset, QARecord.prompt_asset_id == PromptAsset.id)
            .filter(PromptAsset.project_id == pid)
            .count()
        )
        assert qa_count >= 8  # at least 1 check per slot

        session.close()
