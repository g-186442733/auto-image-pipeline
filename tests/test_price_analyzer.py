import pytest
from pipeline.layers.price_analyzer import analyze_price


def test_basic_case():
    result = analyze_price(
        "B09XS7JWHH", {"price": 348}, [{"price": 200}, {"price": 300}, {"price": 400}]
    )
    assert result.asin == "B09XS7JWHH"
    assert result.price_current == 348
    assert result.price_position in ("budget", "mid", "premium", "luxury")


def test_price_band_budget():
    result = analyze_price(
        "ASIN1",
        {"price": 10},
        [{"price": 100}, {"price": 200}, {"price": 300}, {"price": 400}],
    )
    assert result.price_position == "budget"


def test_price_band_mid():
    result = analyze_price(
        "ASIN2",
        {"price": 150},
        [{"price": 100}, {"price": 200}, {"price": 300}, {"price": 400}],
    )
    assert result.price_position == "mid"


def test_price_band_premium():
    result = analyze_price(
        "ASIN3",
        {"price": 350},
        [{"price": 100}, {"price": 200}, {"price": 300}, {"price": 400}],
    )
    assert result.price_position == "premium"


def test_price_band_luxury():
    result = analyze_price(
        "ASIN4",
        {"price": 500},
        [{"price": 100}, {"price": 200}, {"price": 300}, {"price": 400}],
    )
    assert result.price_position == "luxury"


def test_no_benchmarks():
    result = analyze_price("ASIN5", {"price": 99}, [])
    assert result.price_position in ("budget", "mid", "premium", "luxury")
    assert result.price_avg_30d == 99


def test_identical_prices():
    result = analyze_price(
        "ASIN6", {"price": 100}, [{"price": 100}, {"price": 100}, {"price": 100}]
    )
    assert result.price_position == "luxury"


def test_avg_category_price():
    result = analyze_price(
        "ASIN7", {"price": 300}, [{"price": 100}, {"price": 200}, {"price": 300}]
    )
    assert result.price_avg_30d == 200.0


def test_missing_price_key():
    result = analyze_price("ASIN8", {}, [{"price": 100}, {"price": 200}])
    assert result.price_current == 0
    assert result.price_position == "budget"
