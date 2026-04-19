from __future__ import annotations

import statistics

_SLOPE_THRESHOLD = 0.1
_MIN_DATA_POINTS = 7


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """返回 (slope, R²)。纯 Python 线性回归，用于趋势斜率和拟合度计算。"""
    n = len(x)
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)

    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0.0

    y_pred = [slope * (x[i] - x_mean) + y_mean for i in range(n)]
    ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0.0

    return slope, r2


def analyze_trend(asin: str, keepa_data: dict) -> dict:
    """分析 ASIN 价格趋势。

    keepa_data 格式: {"price_history": [10, 11, ...], "dates": ["2024-01-01", ...]}
    返回: {"predicted_trend": "rising"|"stable"|"declining", "confidence": float, "data_points": int}
    数据不足(<7点) → stable + confidence=0.0；空数据 → ValueError
    """
    if not keepa_data or "price_history" not in keepa_data:
        raise ValueError(f"keepa_data 为空或缺少 price_history: asin={asin}")

    prices = keepa_data["price_history"]

    if not prices:
        raise ValueError(f"price_history 为空: asin={asin}")

    if len(prices) < _MIN_DATA_POINTS:
        return {
            "predicted_trend": "stable",
            "confidence": 0.0,
            "data_points": len(prices),
        }

    x = list(range(len(prices)))
    y = [float(p) for p in prices]

    slope, r2 = _linear_regression(x, y)

    if slope > _SLOPE_THRESHOLD:
        trend = "rising"
    elif slope < -_SLOPE_THRESHOLD:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "predicted_trend": trend,
        "confidence": round(r2, 4),
        "data_points": len(prices),
    }
