from pipeline.models.price_analysis import PriceAnalysis


def _get_price(b) -> float:
    if isinstance(b, dict):
        return b.get("price", 0) or 0
    return getattr(b, "price", 0) or 0


def analyze_price(
    asin: str, keepa_data: dict, category_benchmarks: list
) -> PriceAnalysis:
    current_price = keepa_data.get("price", 0) or 0
    benchmark_prices = [_get_price(b) for b in category_benchmarks if _get_price(b)]

    if benchmark_prices:
        avg_category_price = sum(benchmark_prices) / len(benchmark_prices)
        below_or_equal = sum(1 for p in benchmark_prices if p <= current_price)
        price_percentile = (below_or_equal / len(benchmark_prices)) * 100.0
    else:
        avg_category_price = current_price
        price_percentile = 50.0

    if price_percentile < 25:
        price_band = "budget"
    elif price_percentile < 60:
        price_band = "mid"
    elif price_percentile < 85:
        price_band = "premium"
    else:
        price_band = "luxury"

    return PriceAnalysis(
        asin=asin,
        price_current=current_price,
        price_avg_30d=avg_category_price,
        price_min_30d=min(benchmark_prices) if benchmark_prices else current_price,
        price_max_30d=max(benchmark_prices) if benchmark_prices else current_price,
        price_position=price_band,
    )
