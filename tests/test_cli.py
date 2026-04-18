"""Tests for the 4 new CLI commands: brief, prompt, deliver, feedback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from pipeline.__main__ import cli


@click.command()
def _dummy():
    pass


runner = CliRunner()


# ── brief ────────────────────────────────────────────────────────────────


class TestBriefCommand:
    def test_brief_success(self):
        mock_brief = MagicMock()
        mock_brief.id = 42
        mock_brief.slot_index = 0
        with (
            patch("pipeline.__main__.get_session") as mock_gs,
            patch("pipeline.__main__.generate_brief", return_value=mock_brief),
        ):
            sess = MagicMock()
            sess.query.return_value.filter.return_value.all.return_value = [MagicMock()]
            mock_gs.return_value = sess
            result = runner.invoke(cli, ["brief", "1"])
            assert result.exit_code == 0
            assert "Brief generated" in result.output

    def test_brief_error(self):
        with patch(
            "pipeline.__main__.get_session", side_effect=RuntimeError("db down")
        ):
            result = runner.invoke(cli, ["brief", "1"])
            assert result.exit_code == 1
            assert "Error" in result.output or "Error" in (
                result.output + (result.stderr or "")
            )


# ── prompt ───────────────────────────────────────────────────────────────


class TestPromptCommand:
    def test_prompt_success(self):
        with patch("pipeline.__main__.build_prompt", return_value="a]test prompt"):
            result = runner.invoke(cli, ["prompt", "1"])
            assert result.exit_code == 0
            assert "Prompt built" in result.output

    def test_prompt_with_slot_index(self):
        with patch(
            "pipeline.__main__.build_prompt", return_value="slot prompt"
        ) as mock_bp:
            result = runner.invoke(cli, ["prompt", "1", "--slot-index", "3"])
            assert result.exit_code == 0
            mock_bp.assert_called_once_with(1, 3)

    def test_prompt_error(self):
        with patch(
            "pipeline.__main__.build_prompt", side_effect=ValueError("no brief")
        ):
            result = runner.invoke(cli, ["prompt", "1"])
            assert result.exit_code == 1


# ── deliver ──────────────────────────────────────────────────────────────


class TestDeliverCommand:
    def test_deliver_success(self):
        with patch("pipeline.__main__.build_delivery_package", return_value="/tmp/out"):
            result = runner.invoke(cli, ["deliver", "1"])
            assert result.exit_code == 0
            assert "/tmp/out" in result.output

    def test_deliver_error(self):
        with patch(
            "pipeline.__main__.build_delivery_package",
            side_effect=FileNotFoundError("missing"),
        ):
            result = runner.invoke(cli, ["deliver", "1"])
            assert result.exit_code == 1


# ── feedback ─────────────────────────────────────────────────────────────


class TestFeedbackCommand:
    def test_feedback_success(self):
        with patch("pipeline.__main__.export_conclusions", return_value={"count": 5}):
            result = runner.invoke(cli, ["feedback", "1"])
            assert result.exit_code == 0
            assert "Feedback exported" in result.output

    def test_feedback_error(self):
        with patch(
            "pipeline.__main__.export_conclusions", side_effect=RuntimeError("fail")
        ):
            result = runner.invoke(cli, ["feedback", "1"])
            assert result.exit_code == 1
