import pytest

from pipeline.layers.trend_engine import analyze_trend


def test_rising_trend_30_ascending_prices():
    prices = list(range(10, 40))
    dates = [f"2024-01-{i + 1:02d}" for i in range(30)]
    result = analyze_trend("B001", {"price_history": prices, "dates": dates})
    assert result["predicted_trend"] == "rising"
    assert result["confidence"] > 0.7
    assert result["data_points"] == 30


def test_declining_trend_30_descending_prices():
    prices = list(range(39, 9, -1))
    dates = [f"2024-01-{i + 1:02d}" for i in range(30)]
    result = analyze_trend("B002", {"price_history": prices, "dates": dates})
    assert result["predicted_trend"] == "declining"
    assert result["confidence"] > 0.7


def test_stable_trend_small_fluctuation():
    prices = [100, 101, 99, 100, 101, 100, 99, 100, 101, 100]
    dates = [f"2024-01-{i + 1:02d}" for i in range(10)]
    result = analyze_trend("B003", {"price_history": prices, "dates": dates})
    assert result["predicted_trend"] == "stable"


def test_insufficient_data_returns_stable_zero_confidence():
    prices = [10, 20, 30]
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    result = analyze_trend("B004", {"price_history": prices, "dates": dates})
    assert result["predicted_trend"] == "stable"
    assert result["confidence"] == 0.0
    assert result["data_points"] == 3


def test_empty_keepa_data_raises_value_error():
    with pytest.raises(ValueError):
        analyze_trend("B005", {})


def test_none_keepa_data_raises_value_error():
    with pytest.raises(ValueError):
        analyze_trend("B005", None)


def test_empty_price_list_raises_value_error():
    with pytest.raises(ValueError):
        analyze_trend("B005", {"price_history": []})
