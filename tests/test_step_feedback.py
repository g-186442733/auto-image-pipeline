import logging
from unittest.mock import MagicMock, patch

import pytest


@patch("pipeline.layers.feedback_loop.update_brand_profile_from_results")
@patch("pipeline.orchestrator.get_session")
def test_step_feedback_calls_update_when_brand_exists(mock_get_session, mock_update):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_brand = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.return_value = (
        mock_brand
    )

    from pipeline.orchestrator import step_feedback

    step_feedback(1)

    mock_update.assert_called_once_with(1)
    mock_session.close.assert_called_once()


@patch("pipeline.layers.feedback_loop.update_brand_profile_from_results")
@patch("pipeline.orchestrator.get_session")
def test_step_feedback_warns_when_no_brand(mock_get_session, mock_update, caplog):
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    from pipeline.orchestrator import step_feedback

    with caplog.at_level(logging.WARNING, logger="aip.orchestrator"):
        step_feedback(99)

    assert "No BrandProfile found for project 99" in caplog.text
    mock_update.assert_not_called()
    mock_session.close.assert_called_once()
