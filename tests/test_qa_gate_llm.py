import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from pipeline.config import config


def _make_png(tmp_path, width=2000, height=2000):
    from PIL import Image

    p = tmp_path / "test.png"
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    img.save(str(p), "PNG")
    return str(p)


def _make_mock_httpx_response(response_text: str):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"choices": [{"message": {"content": response_text}}]}
    return mock_resp


def _make_white_bg_product(tmp_path, box, filename="white_product.png"):
    from PIL import Image, ImageDraw

    p = tmp_path / filename
    img = Image.new("RGB", (2000, 2000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle(box, fill=(80, 80, 80))
    img.save(str(p), "PNG")
    return str(p)


def _dimensions_for_score(score: int) -> dict:
    maxima = {
        "A1": 10,
        "A2": 8,
        "A3": 7,
        "B1": 8,
        "B2": 7,
        "C1": 5,
        "C2": 5,
        "C3": 5,
        "C4": 4,
        "C5": 5,
        "D1": 25,
        "D2": 0,
        "E1": 5,
        "E2": 5,
    }
    remaining = score
    dims = {}
    for key, max_value in maxima.items():
        value = min(max_value, remaining)
        dims[key] = value
        remaining -= value
    return dims


def _llm_response(
    *,
    passed: bool,
    score: int,
    issues: list[str] | None = None,
    reasoning: str = "ok",
    contains_cjk_text: bool = False,
    dimensions: dict | None = None,
) -> str:
    return json.dumps(
        {
            "pass": passed,
            "score": score,
            "dimensions": dimensions or _dimensions_for_score(score),
            "contains_cjk_text": contains_cjk_text,
            "issues": issues or [],
            "reasoning": reasoning,
        }
    )


class TestLlmQaEvaluatePass:
    def test_returns_pass_when_score_above_70(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = _llm_response(passed=True, score=85, reasoning="Good image")
        mock_resp = _make_mock_httpx_response(response)

        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="Hero shot")

        assert result["pass"] is True
        assert result["score"] == 85
        assert result["issues"] == []


class TestLlmQaEvaluateFail:
    def test_returns_fail_when_score_below_70(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = _llm_response(
            passed=False,
            score=40,
            issues=["Bad lighting"],
            reasoning="Dark",
        )
        mock_resp = _make_mock_httpx_response(response)

        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="Hero shot")

        assert result["pass"] is False
        assert result["score"] == 40
        assert "Bad lighting" in result["issues"]


class TestLlmQaEvaluateApiError:
    def test_returns_retryable_failure_on_empty_api_key(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)

        with patch.object(config, "api_key", ""):
            result = llm_qa_evaluate(image_path)

        assert result["pass"] is False
        assert result["score"] == 0
        assert result["issues"] == ["LLM evaluation unavailable — retry required"]

    def test_returns_safe_default_on_malformed_json(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        mock_resp = _make_mock_httpx_response("not valid json at all")

        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path)

        assert result["pass"] is False
        assert result["score"] == 0


class TestLegacyStillCallable:
    def test_run_qa_checks_legacy_exists_and_callable(self):
        from pipeline.layers.qa_gate import run_qa_checks_legacy

        assert callable(run_qa_checks_legacy)


class TestNewRunQaChecksReturnsQARecord:
    def test_returns_qa_record_with_llm_qa_check_type(self, tmp_path):
        from pipeline.layers.qa_gate import run_qa_checks
        from pipeline.models.qa_record import QARecord

        image_path = _make_png(tmp_path)
        response = _llm_response(passed=True, score=90, reasoning="Great")
        mock_resp = _make_mock_httpx_response(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 0
        mock_session.get.return_value = mock_slot_plan

        mock_asset = MagicMock()
        mock_asset.id = 10
        mock_asset.image_path = image_path
        mock_asset.model_name = "gpt_image"
        mock_asset.visual_tags = None
        mock_asset.status = None
        mock_session.query.return_value.filter_by.return_value.filter.return_value.order_by.return_value.first.return_value = mock_asset

        mock_brief = MagicMock()
        mock_brief.brief_json = '{"goal": "hero"}'
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_brief
        )

        mock_project = MagicMock()
        mock_project.notes = None
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        mock_rec = MagicMock(spec=QARecord)
        mock_rec.passed = 1
        mock_rec.score = 90.0
        mock_rec.check_type = "llm_qa"

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            with patch(
                "pipeline.layers.qa_gate.QARecord", return_value=mock_rec
            ) as MockQARecord:
                records = run_qa_checks(1)

        assert len(records) == 1
        call_kwargs = MockQARecord.call_args[1]
        assert call_kwargs["check_type"] == "llm_qa"
        assert call_kwargs["passed"] == 1
        assert call_kwargs["score"] == 90.0

    def test_listing_int_hero_safe_frame_failure_caps_score(self, tmp_path):
        from pipeline.layers.qa_gate import run_qa_checks

        image_path = _make_white_bg_product(
            tmp_path,
            (400, 160, 1600, 1985),
            filename="edge_hero.png",
        )
        response = _llm_response(passed=True, score=95, reasoning="Great")
        mock_resp = _make_mock_httpx_response(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.id = 1
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 0
        mock_slot_plan.intent_tag = "INT_HERO"
        mock_slot_plan.tenant_id = None

        mock_asset = MagicMock()
        mock_asset.id = 10
        mock_asset.image_path = image_path
        mock_session.query.return_value.filter_by.return_value.filter.return_value.order_by.return_value.first.return_value = mock_asset

        mock_brief = MagicMock()
        mock_brief.brief_json = '{"goal": "hero"}'
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_brief
        )

        mock_project = MagicMock()
        mock_project.notes = None
        mock_project.customer_brief = "{}"
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            records = run_qa_checks(1)

        assert records[0].passed == 0
        assert records[0].score == 59.0
        details = json.loads(records[0].details)
        assert details["safe_frame_failed"] is True
        assert details["safe_frame"]["min_margin_ratio"] < 0.05
        assert any("safe-frame failure" in issue for issue in details["issues"])


class TestRunQaChecksDeliveryStatus:
    def test_product_fact_missing_d_dimensions_forces_failed_when_repair_unavailable(self, tmp_path):
        from pipeline.layers.qa_gate import run_qa_checks

        image_path = _make_png(tmp_path)
        response = json.dumps(
            {
                "pass": True,
                "score": 94,
                "dimensions": {"A1": 10, "A2": 8, "A3": 7, "B1": 8, "B2": 7},
                "issues": [],
                "reasoning": "Looks good",
            }
        )
        mock_resp = _make_mock_httpx_response(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.id = 1
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 1
        mock_slot_plan.intent_tag = "INT_HERO"
        mock_slot_plan.tenant_id = None

        mock_asset = MagicMock()
        mock_asset.id = 10
        mock_asset.image_path = image_path
        mock_asset.model_name = "gpt_image"
        mock_asset.visual_tags = None
        mock_asset.status = None

        mock_brief = MagicMock()
        mock_brief.brief_json = '{"goal": "hero"}'

        mock_project = MagicMock()
        mock_project.notes = None
        mock_project.customer_brief = json.dumps({"reference_assets": {"white_bg": [image_path]}})

        def query_side_effect(model):
            q = MagicMock()
            if getattr(model, "__name__", "") == "PromptAsset":
                q.filter_by.return_value.filter.return_value.order_by.return_value.first.return_value = mock_asset
                q.filter_by.return_value.order_by.return_value.first.return_value = mock_asset
            else:
                q.filter_by.return_value.first.return_value = mock_brief
            return q

        mock_session.query.side_effect = query_side_effect
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
            patch("pipeline.layers.qa_gate._repair_consistency_dimensions", return_value={}),
        ):
            records = run_qa_checks(1)

        assert records[0].passed == 0
        assert records[0].score == 0.0
        assert mock_asset.status == "failed"
        assert "delivery_status" in records[0].details

    def test_silhouette_mode_allows_lower_d_score_for_product_fact(self, tmp_path):
        from pipeline.layers.qa_gate import run_qa_checks

        image_path = _make_png(tmp_path)
        response = _llm_response(
            passed=True,
            score=82,
            dimensions={
                "A1": 10,
                "A2": 8,
                "A3": 7,
                "B1": 8,
                "B2": 7,
                "C1": 5,
                "C2": 5,
                "C3": 5,
                "C4": 4,
                "C5": 5,
                "D1": 11,
                "D2": 0,
                "E1": 5,
                "E2": 4,
            },
            reasoning="Shape and material match, exact logo ignored",
        )
        mock_resp = _make_mock_httpx_response(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.id = 1
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 1
        mock_slot_plan.intent_tag = "INT_HERO"
        mock_slot_plan.tenant_id = None

        mock_asset = MagicMock()
        mock_asset.id = 10
        mock_asset.image_path = image_path
        mock_asset.model_name = "gemini_image"
        mock_asset.visual_tags = None
        mock_asset.status = None

        mock_brief = MagicMock()
        mock_brief.brief_json = '{"goal": "hero"}'

        mock_project = MagicMock()
        mock_project.notes = None
        mock_project.customer_brief = json.dumps(
            {
                "reference_identity_mode": "silhouette",
                "reference_assets": {"white_bg": [image_path]},
            }
        )

        def query_side_effect(model):
            q = MagicMock()
            if getattr(model, "__name__", "") == "PromptAsset":
                q.filter_by.return_value.filter.return_value.order_by.return_value.first.return_value = mock_asset
                q.filter_by.return_value.order_by.return_value.first.return_value = mock_asset
            else:
                q.filter_by.return_value.first.return_value = mock_brief
            return q

        mock_session.query.side_effect = query_side_effect
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            records = run_qa_checks(1)

        assert records[0].passed == 1
        assert records[0].score == 84.0
        assert mock_asset.status == "final"
        details = json.loads(records[0].details)
        assert details["reference_identity_mode"] == "silhouette"
        assert details["delivery_status"] == "final"
        assert details["consistency_threshold"] == 10

    def test_product_fact_missing_d_dimensions_uses_consistency_repair(self, tmp_path):
        from pipeline.layers.qa_gate import run_qa_checks

        image_path = _make_png(tmp_path)
        response = json.dumps(
            {
                "pass": False,
                "score": 68,
                "dimensions": {"A1": 10, "A2": 8, "A3": 7, "B1": 8, "B2": 7},
                "issues": [],
                "reasoning": "Main QA response was truncated before D dimensions",
            }
        )
        mock_resp = _make_mock_httpx_response(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.id = 1
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 1
        mock_slot_plan.intent_tag = "INT_HERO"
        mock_slot_plan.tenant_id = None

        mock_asset = MagicMock()
        mock_asset.id = 10
        mock_asset.image_path = image_path
        mock_asset.model_name = "gpt_image"
        mock_asset.visual_tags = None
        mock_asset.status = None

        mock_brief = MagicMock()
        mock_brief.brief_json = '{"goal": "hero"}'

        mock_project = MagicMock()
        mock_project.notes = None
        mock_project.customer_brief = json.dumps({"reference_assets": {"white_bg": [image_path], "multiangle": [image_path]}})

        def query_side_effect(model):
            q = MagicMock()
            if getattr(model, "__name__", "") == "PromptAsset":
                q.filter_by.return_value.filter.return_value.order_by.return_value.first.return_value = mock_asset
                q.filter_by.return_value.order_by.return_value.first.return_value = mock_asset
            else:
                q.filter_by.return_value.first.return_value = mock_brief
            return q

        mock_session.query.side_effect = query_side_effect
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
            patch(
                "pipeline.layers.qa_gate._repair_consistency_dimensions",
                return_value={"D1": 16, "D2": 6, "D_repair_reasoning": "产品外观与参考图一致"},
            ),
        ):
            records = run_qa_checks(1)

        assert records[0].passed == 1
        assert records[0].score == 70.0
        assert mock_asset.status == "final"
        details = json.loads(records[0].details)
        assert details["D1"] == 16
        assert details["D2"] == 6
        assert details["D"] == 22
        assert details["delivery_status"] == "final"
        assert details["consistency_repair"]["D_repair_reasoning"] == "产品外观与参考图一致"


class TestStepQaRetry:
    def test_retries_on_failure_up_to_max(self):
        from pipeline.orchestrator import step_qa, _QA_MAX_RETRIES

        assert _QA_MAX_RETRIES == 2

        mock_session = MagicMock()
        mock_slot = MagicMock()
        mock_slot.id = 1
        mock_slot.slot_index = 1
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_slot
        ]

        fail_record = MagicMock()
        fail_record.passed = 0
        fail_record.score = 30.0
        fail_record.details = json.dumps({"issues": ["bad"], "reasoning": "fail"})

        call_count = {"qa": 0, "gen": 0}

        def mock_qa(slot_id):
            call_count["qa"] += 1
            return [fail_record]

        def mock_gen(pid, adapter_name="gpt_image", slot_indices=None, pipeline_run_id=None):
            call_count["gen"] += 1

        with (
            patch("pipeline.orchestrator.get_session", return_value=mock_session),
            patch("pipeline.orchestrator.run_qa_checks", side_effect=mock_qa),
            patch("pipeline.orchestrator.step_generate", side_effect=mock_gen),
            patch("pipeline.orchestrator._update_status"),
        ):
            records = step_qa(project_id=1)

        assert call_count["qa"] == 3
        assert call_count["gen"] == 2

    def test_retries_on_angle_mismatch_even_when_score_passes(self):
        from pipeline.orchestrator import step_qa

        mock_session = MagicMock()
        mock_slot = MagicMock()
        mock_slot.id = 1
        mock_slot.slot_index = 4
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_slot]
        mock_session.query.return_value = mock_query

        mismatch_record = MagicMock()
        mismatch_record.passed = 1
        mismatch_record.score = 99.0
        mismatch_record.details = json.dumps(
            {
                "issues": [],
                "reasoning": "good but wrong angle",
                "target_angle": "macro close-up",
                "actual_angle": "3/4角",
                "angle_matches_target": False,
            }
        )
        match_record = MagicMock()
        match_record.passed = 1
        match_record.score = 98.0
        match_record.details = json.dumps(
            {
                "issues": [],
                "reasoning": "angle fixed",
                "target_angle": "macro close-up",
                "actual_angle": "近景",
                "angle_matches_target": True,
            }
        )
        records_by_attempt = [mismatch_record, match_record]
        call_count = {"qa": 0, "gen": 0}

        def mock_qa(slot_id):
            record = records_by_attempt[min(call_count["qa"], len(records_by_attempt) - 1)]
            call_count["qa"] += 1
            return [record]

        def mock_gen(pid, adapter_name="gpt_image", slot_indices=None, pipeline_run_id=None):
            call_count["gen"] += 1
            assert slot_indices == [4]

        with (
            patch("pipeline.orchestrator.get_session", return_value=mock_session),
            patch("pipeline.orchestrator.run_qa_checks", side_effect=mock_qa),
            patch("pipeline.orchestrator.step_generate", side_effect=mock_gen),
            patch("pipeline.orchestrator._update_status"),
        ):
            records = step_qa(project_id=1, pipeline_run_id=58)

        assert call_count["qa"] == 2
        assert call_count["gen"] == 1
        assert records[-1].details == match_record.details


class TestLlmQaEvaluateLanguagePolicy:
    def test_cjk_text_detection_forces_fail_even_with_high_score(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = _llm_response(
            passed=True,
            score=96,
            contains_cjk_text=True,
            reasoning="Image contains Chinese label text",
        )
        mock_resp = _make_mock_httpx_response(response)

        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="Amazon US infographic", intent_tag="INT_INFOGRAPHIC")

        assert result["pass"] is False
        assert result["score"] == 0
        assert result["contains_cjk_text"] is True
        assert "Chinese/CJK" in result["issues"][-1]


class TestLlmQaEvaluateBoundary:
    def test_score_70_is_pass(self, tmp_path):
        """score=70 is exactly the pass threshold."""
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = _llm_response(passed=True, score=70, reasoning="Borderline OK")
        mock_resp = _make_mock_httpx_response(response)
        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="test")
        assert result["pass"] is True
        assert result["score"] == 70

    def test_score_69_is_fail(self, tmp_path):
        """score=69 is just below the pass threshold."""
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = _llm_response(
            passed=False,
            score=69,
            issues=["slightly off"],
            reasoning="close but no",
        )
        mock_resp = _make_mock_httpx_response(response)
        with (
            patch.object(config, "api_key", "fake-key"),
            patch("pipeline.layers.qa_gate.httpx.post", return_value=mock_resp),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="test")
        assert result["pass"] is False
        assert result["score"] == 69


class TestStepQaRetryPass:
    def test_first_fail_second_pass_returns_pass(self):
        """First attempt fails, second attempt passes → final PASS."""
        from pipeline.orchestrator import step_qa

        mock_session = MagicMock()
        mock_slot = MagicMock()
        mock_slot.id = 1
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_slot
        ]

        fail_record = MagicMock()
        fail_record.passed = 0
        fail_record.score = 30.0
        fail_record.details = json.dumps({"issues": ["bad"], "reasoning": "fail"})

        pass_record = MagicMock()
        pass_record.passed = 1
        pass_record.score = 85.0
        pass_record.details = json.dumps({"issues": [], "reasoning": "ok"})

        call_count = {"qa": 0}

        def mock_qa(slot_id):
            call_count["qa"] += 1
            return [fail_record] if call_count["qa"] == 1 else [pass_record]

        with (
            patch("pipeline.orchestrator.get_session", return_value=mock_session),
            patch("pipeline.orchestrator.run_qa_checks", side_effect=mock_qa),
            patch("pipeline.orchestrator.step_generate"),
            patch("pipeline.orchestrator._update_status"),
        ):
            records = step_qa(project_id=1)

        assert call_count["qa"] == 2
        assert records[-1].passed == 1
