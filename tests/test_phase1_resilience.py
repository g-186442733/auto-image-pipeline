"""Tests for Phase 1 Amazon fetch resilience in step_analyze."""

import logging
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_session(
    project_id: int = 1, asin: str = "B001", category: str = "tools"
):
    """构造一个标准的 mock session，返回带 asin/category 的 Project。"""
    mock_session = MagicMock()
    mock_proj = MagicMock()
    mock_proj.id = project_id
    mock_proj.asin = asin
    mock_proj.category = category
    mock_session.get.return_value = mock_proj
    # query(...).filter(...).first() → None（无竞品 listing）
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_session.query.return_value.filter.return_value.all.return_value = []
    mock_session.query.return_value.filter.return_value.delete.return_value = 0
    return mock_session, mock_proj


@patch("pipeline.orchestrator._update_status")
@patch("pipeline.orchestrator.analyze_competitor_listing")
@patch("pipeline.orchestrator.fetch_category_top")
@patch("pipeline.orchestrator.fetch_asin_detail")
@patch("pipeline.orchestrator.get_session")
def test_fetch_asin_detail_raises_step_completes(
    mock_get_session,
    mock_fetch_asin,
    mock_fetch_cat,
    mock_analyze_competitor,
    mock_update_status,
    caplog,
):
    """fetch_asin_detail 抛出异常时，step_analyze 仍应完成，并记录 error 日志。"""
    mock_session, mock_proj = _make_mock_session(project_id=1)
    mock_get_session.return_value = mock_session

    mock_fetch_asin.side_effect = RuntimeError("Keepa timeout")
    mock_fetch_cat.return_value = []
    mock_analyze_competitor.return_value = {}

    from pipeline.orchestrator import step_analyze

    with caplog.at_level(logging.ERROR, logger="aip.orchestrator"):
        result = step_analyze(1)

    # 步骤应完成，返回 dict
    assert isinstance(result, dict)
    # asin_detail 应为 None
    assert result["asin_detail"] is None
    # 日志中应包含错误信息
    assert "fetch_asin_detail failed for project 1" in caplog.text
    assert "Keepa timeout" in caplog.text
    # status 应更新为 analyzed
    mock_update_status.assert_called_with(1, "analyzed")


@patch("pipeline.orchestrator._update_status")
@patch("pipeline.orchestrator.analyze_competitor_listing")
@patch("pipeline.orchestrator.fetch_category_top")
@patch("pipeline.orchestrator.fetch_asin_detail")
@patch("pipeline.orchestrator.get_session")
def test_both_fetches_raise_phase2_still_executes(
    mock_get_session,
    mock_fetch_asin,
    mock_fetch_cat,
    mock_analyze_competitor,
    mock_update_status,
    caplog,
):
    """fetch_asin_detail 和 fetch_category_top 均抛出异常时，Phase 2 仍执行，步骤完成。"""
    mock_session, mock_proj = _make_mock_session(project_id=2)
    mock_get_session.return_value = mock_session

    mock_fetch_asin.side_effect = ConnectionError("network error")
    mock_fetch_cat.side_effect = TimeoutError("category timeout")
    mock_analyze_competitor.return_value = {}

    from pipeline.orchestrator import step_analyze

    with caplog.at_level(logging.ERROR, logger="aip.orchestrator"):
        result = step_analyze(2)

    # 步骤应完成
    assert isinstance(result, dict)
    assert result["asin_detail"] is None
    assert result["category_top"] is None

    # 两个 error 都应记录
    assert "fetch_asin_detail failed for project 2" in caplog.text
    assert "fetch_category_top failed for project 2" in caplog.text

    # 最终状态应为 analyzed（Phase 2 完成）
    mock_update_status.assert_called_with(2, "analyzed")
