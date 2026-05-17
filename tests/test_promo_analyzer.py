import pytest
from datetime import datetime, timedelta
from pipeline.layers.promo_analyzer import analyze_promo, KEEPA_EPOCH


def keepa_ts(dt: datetime) -> float:
    return (dt - KEEPA_EPOCH).total_seconds() / 60


def test_frequent_pattern():
    base = datetime(2023, 1, 1)
    history = []
    price = 100.0
    for month in range(12):
        dt = base + timedelta(days=month * 30)
        history.append({"timestamp": keepa_ts(dt), "price": price})
        drop_dt = dt + timedelta(days=10)
        history.append({"timestamp": keepa_ts(drop_dt), "price": price * 0.80})
        recover_dt = drop_dt + timedelta(days=5)
        history.append({"timestamp": keepa_ts(recover_dt), "price": price})

    result = analyze_promo("B09XS7JWHH", {"priceHistory": history})

    assert result.asin == "B09XS7JWHH"
    assert isinstance(result.promo_pattern, str)
    assert result.promo_pattern == "frequent"
    assert isinstance(result.avg_discount_pct, float)
    assert result.avg_discount_pct > 0
    assert result.last_promo_date is not None


def test_never_pattern_empty_history():
    result = analyze_promo("B09XS7JWHH", {"priceHistory": []})

    assert result.asin == "B09XS7JWHH"
    assert result.promo_pattern == "never"
    assert result.promo_frequency == 0.0
    assert result.avg_discount_pct == 0.0
    assert result.last_promo_date is None


def test_never_pattern_missing_key():
    result = analyze_promo("B09XS7JWHH", {})

    assert result.promo_pattern == "never"
    assert result.avg_discount_pct == 0.0


def test_rare_pattern():
    base = datetime(2022, 1, 1)
    history = [
        {"timestamp": keepa_ts(base), "price": 100.0},
        {"timestamp": keepa_ts(base + timedelta(days=180)), "price": 85.0},
        {"timestamp": keepa_ts(base + timedelta(days=365)), "price": 100.0},
    ]
    result = analyze_promo("TESTB001", {"priceHistory": history})

    assert result.promo_pattern == "rare"
    assert result.promo_frequency < 2.0


def test_seasonal_pattern():
    base = datetime(2022, 1, 1)
    history = []
    price = 100.0
    history.append({"timestamp": keepa_ts(base), "price": price})
    for q in range(3):
        drop_dt = base + timedelta(days=90 * q + 45)
        history.append({"timestamp": keepa_ts(drop_dt), "price": price * 0.80})
        recover_dt = drop_dt + timedelta(days=15)
        history.append({"timestamp": keepa_ts(recover_dt), "price": price})

    result = analyze_promo("TESTB002", {"priceHistory": history})

    assert result.promo_pattern in ("seasonal", "frequent")
    assert result.avg_discount_pct > 0


def test_single_entry_returns_never():
    base = datetime(2023, 6, 1)
    history = [{"timestamp": keepa_ts(base), "price": 99.99}]
    result = analyze_promo("TESTB003", {"priceHistory": history})

    assert result.promo_pattern == "never"


def test_no_drops_returns_never():
    base = datetime(2023, 1, 1)
    history = [
        {"timestamp": keepa_ts(base + timedelta(days=i * 30)), "price": 100.0 + i}
        for i in range(6)
    ]
    result = analyze_promo("TESTB004", {"priceHistory": history})

    assert result.promo_pattern == "never"
    assert result.avg_discount_pct == 0.0


def test_unix_timestamp_support():
    base_unix = 1_700_000_000
    history = [
        {"timestamp": base_unix, "price": 100.0},
        {"timestamp": base_unix + 86400 * 10, "price": 80.0},
        {"timestamp": base_unix + 86400 * 20, "price": 100.0},
        {"timestamp": base_unix + 86400 * 365, "price": 100.0},
    ]
    result = analyze_promo("TESTB005", {"priceHistory": history})

    assert result.promo_pattern in ("rare", "seasonal", "frequent", "never")
    assert isinstance(result.avg_discount_pct, float)
