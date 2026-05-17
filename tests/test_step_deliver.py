import logging
from unittest.mock import MagicMock, patch

import pytest


@patch("pipeline.layers.delivery.build_delivery_package")
def test_step_deliver_calls_build(mock_build, tmp_path):
    (tmp_path / "file.txt").write_text("data")
    mock_build.return_value = str(tmp_path)

    from pipeline.orchestrator import step_deliver

    result = step_deliver(1)
    mock_build.assert_called_once_with(1)
    assert result == str(tmp_path)


@patch("pipeline.layers.delivery.build_delivery_package")
def test_step_deliver_empty_string_warns(mock_build, caplog):
    mock_build.return_value = ""

    from pipeline.orchestrator import step_deliver

    with caplog.at_level(logging.WARNING, logger="aip.orchestrator"):
        result = step_deliver(99)

    assert result is None
    assert "empty or missing delivery package" in caplog.text


@patch("pipeline.layers.delivery.build_delivery_package")
def test_step_deliver_empty_dir_warns(mock_build, tmp_path, caplog):
    mock_build.return_value = str(tmp_path)

    from pipeline.orchestrator import step_deliver

    with caplog.at_level(logging.WARNING, logger="aip.orchestrator"):
        result = step_deliver(42)

    assert result is None
    assert "empty or missing delivery package" in caplog.text
