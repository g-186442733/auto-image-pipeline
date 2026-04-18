"""Task 7 — Data flow tests for orchestrator.

Tests:
1. step_analyze handles dict benchmarks (no AttributeError)
2. run_full_pipeline passes step_analyze result to step_plan
3. step_plan accepts analysis_results parameter
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


def _make_in_memory_db():
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")


# ===========================================================================
# T7-1: step_analyze must handle dict benchmarks without AttributeError
# ===========================================================================


class TestDictBenchmarkHandling:
    """fetch_category_top may return dicts; orchestrator must convert to ORM."""

    def test_step_analyze_with_dict_benchmarks(self):
        """step_analyze should not raise AttributeError when
        fetch_category_top returns list[dict] instead of list[AmazonBenchmark]."""
        _make_in_memory_db()

        from pipeline.config import config

        config.keepa_api_key = "test-key"
        config.openai_api_key = "test-key"

        from pipeline.models.base import get_session
        from pipeline.models.project import Project
        from pipeline.orchestrator import step_analyze

        session = get_session()
        proj = Project(
            name="test", asin="B0TESTTEST", category="TestCat", status="initialized"
        )
        session.add(proj)
        session.commit()
        pid = proj.id
        session.close()

        mock_asin = {"title": "Test", "price": 9.99}
        mock_cats = [
            {"competitor_asin": "B0COMP00AA", "slot_index": 0},
            {"competitor_asin": "B0COMP00BB", "slot_index": 1},
        ]
        mock_analysis = [{"score": 88}]

        with (
            mock.patch(
                "pipeline.orchestrator.fetch_asin_detail", return_value=mock_asin
            ),
            mock.patch(
                "pipeline.orchestrator.fetch_category_top", return_value=mock_cats
            ),
            mock.patch(
                "pipeline.orchestrator.analyze_competitor_listing",
                return_value=mock_analysis,
            ),
        ):
            # This should NOT raise AttributeError
            result = step_analyze(pid)

        assert "asin_detail" in result
        assert "category_top" in result

        # Verify benchmarks were actually persisted as ORM objects
        from pipeline.models.benchmark import AmazonBenchmark

        session = get_session()
        count = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == pid)
            .count()
        )
        assert count == 2, f"Expected 2 benchmarks persisted, got {count}"
        session.close()


# ===========================================================================
# T7-2: run_full_pipeline must pass analyze results to step_plan
# ===========================================================================


class TestAnalyzeResultPassthrough:
    """step_analyze() return value must reach step_plan()."""

    def test_step_plan_receives_analysis_results(self):
        """run_full_pipeline should capture step_analyze result and pass to step_plan."""
        _make_in_memory_db()

        from pipeline.config import config

        config.keepa_api_key = "test-key"
        config.openai_api_key = "test-key"

        received = {}

        def _mock_init(brief_path):
            from pipeline.models.base import get_session
            from pipeline.models.project import Project

            session = get_session()
            proj = Project(
                name="test", asin="B0TESTTEST", category="TestCat", status="initialized"
            )
            session.add(proj)
            session.commit()
            session.refresh(proj)
            session.expunge(proj)
            session.close()
            return proj

        def _mock_analyze(project_id):
            # Insert benchmarks so step_plan works
            from pipeline.models.base import get_session
            from pipeline.models.benchmark import AmazonBenchmark

            session = get_session()
            for i in range(3):
                session.add(
                    AmazonBenchmark(
                        project_id=project_id,
                        competitor_asin=f"B0MOCK000{i}",
                        slot_index=i,
                    )
                )
            session.commit()
            session.close()

            from pipeline.orchestrator import _update_status

            _update_status(project_id, "analyzed")
            return {
                "asin_detail": {"title": "Test"},
                "category_top": [{"asin": "B0MOCK0000"}],
                "competitor_analysis": [{"score": 90}],
            }

        def _spy_step_plan(project_id, analysis_results=None):
            received["analysis_results"] = analysis_results
            # Call real step_plan
            from pipeline.layers.slot_planner import generate_slot_plan
            from pipeline.orchestrator import _update_status

            slots = generate_slot_plan(project_id)
            _update_status(project_id, "planned")
            return slots

        def _mock_generate(project_id, adapter_name="mock"):
            from pipeline.orchestrator import _update_status

            _update_status(project_id, "generated")
            return {}

        def _mock_qa(project_id, adapter_name="mock", **kwargs):
            from pipeline.orchestrator import _update_status

            _update_status(project_id, "qa_passed")
            return []

        def _mock_report(project_id):
            from pipeline.orchestrator import _update_status

            _update_status(project_id, "completed")
            return {"project": {"name": "test"}}

        # Create a minimal brief file
        brief = {"name": "test", "asin": "B0TESTTEST", "category": "TestCat"}
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(brief, tmp)
        tmp.close()

        try:
            with (
                mock.patch("pipeline.orchestrator.step_init", side_effect=_mock_init),
                mock.patch(
                    "pipeline.orchestrator.step_analyze", side_effect=_mock_analyze
                ),
                mock.patch(
                    "pipeline.orchestrator.step_plan", side_effect=_spy_step_plan
                ),
                mock.patch(
                    "pipeline.orchestrator.step_generate", side_effect=_mock_generate
                ),
                mock.patch("pipeline.orchestrator.step_qa", side_effect=_mock_qa),
                mock.patch(
                    "pipeline.orchestrator.step_report", side_effect=_mock_report
                ),
            ):
                from pipeline.orchestrator import run_full_pipeline

                run_full_pipeline(tmp.name)
        finally:
            os.unlink(tmp.name)

        # The key assertion: step_plan must have received analysis_results
        assert "analysis_results" in received, "step_plan was never called"
        assert received["analysis_results"] is not None, (
            "step_plan should receive analysis_results from step_analyze, got None"
        )
        assert "asin_detail" in received["analysis_results"]


# ===========================================================================
# T7-3: step_plan signature accepts analysis_results
# ===========================================================================


class TestStepPlanSignature:
    """step_plan must accept optional analysis_results kwarg."""

    def test_step_plan_accepts_analysis_results_kwarg(self):
        """step_plan(project_id, analysis_results=...) must not raise TypeError."""
        _make_in_memory_db()

        from pipeline.models.base import get_session
        from pipeline.models.project import Project
        from pipeline.models.benchmark import AmazonBenchmark
        from pipeline.orchestrator import step_plan

        session = get_session()
        proj = Project(
            name="test", asin="B0TESTTEST", category="TestCat", status="analyzed"
        )
        session.add(proj)
        session.commit()
        pid = proj.id
        for i in range(3):
            session.add(
                AmazonBenchmark(
                    project_id=pid, competitor_asin=f"B0MOCK000{i}", slot_index=i
                )
            )
        session.commit()
        session.close()

        # This should NOT raise TypeError
        slots = step_plan(pid, analysis_results={"asin_detail": {"title": "Test"}})
        assert len(slots) == 8

    def test_step_plan_works_without_analysis_results(self):
        """Backward compat: step_plan(project_id) must still work."""
        _make_in_memory_db()

        from pipeline.models.base import get_session
        from pipeline.models.project import Project
        from pipeline.models.benchmark import AmazonBenchmark
        from pipeline.orchestrator import step_plan

        session = get_session()
        proj = Project(
            name="test2", asin="B0TESTTEST", category="TestCat", status="analyzed"
        )
        session.add(proj)
        session.commit()
        pid = proj.id
        for i in range(3):
            session.add(
                AmazonBenchmark(
                    project_id=pid, competitor_asin=f"B0MOCK100{i}", slot_index=i
                )
            )
        session.commit()
        session.close()

        slots = step_plan(pid)
        assert len(slots) == 8
