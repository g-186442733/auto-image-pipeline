import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


def _make_png(tmp_path, width=2000, height=2000):
    from PIL import Image

    p = tmp_path / "test.png"
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    img.save(str(p), "PNG")
    return str(p)


def _setup_mock_genai(response_text: str):
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_model.generate_content.return_value = mock_response
    mock_genai.GenerativeModel.return_value = mock_model
    return mock_genai


class TestLlmQaEvaluatePass:
    def test_returns_pass_when_score_above_70(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = json.dumps(
            {"pass": True, "score": 85, "issues": [], "reasoning": "Good image"}
        )
        mock_genai = _setup_mock_genai(response)

        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="Hero shot")

        assert result["pass"] is True
        assert result["score"] == 85
        assert result["issues"] == []


class TestLlmQaEvaluateFail:
    def test_returns_fail_when_score_below_70(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        response = json.dumps(
            {
                "pass": False,
                "score": 40,
                "issues": ["Bad lighting"],
                "reasoning": "Dark",
            }
        )
        mock_genai = _setup_mock_genai(response)

        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
        ):
            result = llm_qa_evaluate(image_path, goal_brief="Hero shot")

        assert result["pass"] is False
        assert result["score"] == 40
        assert "Bad lighting" in result["issues"]


class TestLlmQaEvaluateApiError:
    def test_returns_safe_default_on_empty_api_key(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)

        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            result = llm_qa_evaluate(image_path)

        assert result["pass"] is False
        assert result["score"] == 0
        assert len(result["issues"]) > 0

    def test_returns_safe_default_on_malformed_json(self, tmp_path):
        from pipeline.layers.qa_gate import llm_qa_evaluate

        image_path = _make_png(tmp_path)
        mock_genai = _setup_mock_genai("not valid json at all")

        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
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
        response = json.dumps(
            {"pass": True, "score": 90, "issues": [], "reasoning": "Great"}
        )
        mock_genai = _setup_mock_genai(response)

        mock_session = MagicMock()
        mock_slot_plan = MagicMock()
        mock_slot_plan.project_id = 1
        mock_slot_plan.slot_index = 0
        mock_session.get.return_value = mock_slot_plan

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
        mock_session.get.side_effect = [mock_slot_plan, mock_project]

        mock_rec = MagicMock(spec=QARecord)
        mock_rec.passed = 1
        mock_rec.score = 90.0
        mock_rec.check_type = "llm_qa"

        with (
            patch("pipeline.layers.qa_gate.get_session", return_value=mock_session),
            patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}),
            patch("pipeline.layers.qa_gate._get_genai", return_value=mock_genai),
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


class TestStepQaRetry:
    def test_retries_on_failure_up_to_max(self):
        from pipeline.orchestrator import step_qa, _QA_MAX_RETRIES

        assert _QA_MAX_RETRIES == 2

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

        call_count = {"qa": 0, "gen": 0}

        def mock_qa(slot_id):
            call_count["qa"] += 1
            return [fail_record]

        def mock_gen(pid, adapter_name="gpt_image"):
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
