from datetime import datetime, timedelta, timezone
from pipeline.models.promo_analysis import PromoAnalysis

KEEPA_EPOCH = datetime(2011, 1, 8)


def _to_datetime(ts: float) -> datetime:
    if ts > 1_000_000_000:
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    return KEEPA_EPOCH + timedelta(minutes=ts)


def analyze_promo(asin: str, keepa_data: dict) -> PromoAnalysis:
    price_history = keepa_data.get("priceHistory") or []

    if len(price_history) < 2:
        return PromoAnalysis(
            asin=asin,
            promo_frequency=0.0,
            avg_discount_pct=0.0,
            last_promo_date=None,
            promo_pattern="never",
        )

    sorted_history = sorted(price_history, key=lambda x: x["timestamp"])

    promo_events = []
    for i in range(1, len(sorted_history)):
        prev = sorted_history[i - 1]
        curr = sorted_history[i]
        prev_price = prev.get("price", 0)
        curr_price = curr.get("price", 0)
        if prev_price > 0 and curr_price > 0:
            drop_pct = (prev_price - curr_price) / prev_price * 100
            if drop_pct > 10:
                promo_events.append(
                    {
                        "date": _to_datetime(curr["timestamp"]),
                        "discount_pct": drop_pct,
                    }
                )

    first_dt = _to_datetime(sorted_history[0]["timestamp"])
    last_dt = _to_datetime(sorted_history[-1]["timestamp"])
    total_months = max((last_dt - first_dt).days / 30.0, 1.0)
    promo_frequency = (len(promo_events) / total_months) * 12

    if not promo_events:
        return PromoAnalysis(
            asin=asin,
            promo_frequency=0.0,
            avg_discount_pct=0.0,
            last_promo_date=None,
            promo_pattern="never",
        )

    avg_discount_pct = sum(e["discount_pct"] for e in promo_events) / len(promo_events)
    last_promo_date = max(e["date"] for e in promo_events).strftime("%Y-%m-%d")

    if promo_frequency == 0:
        pattern = "never"
    elif promo_frequency < 2:
        pattern = "rare"
    elif promo_frequency <= 4:
        pattern = "seasonal"
    else:
        pattern = "frequent"

    return PromoAnalysis(
        asin=asin,
        promo_frequency=round(promo_frequency, 4),
        avg_discount_pct=round(avg_discount_pct, 4),
        last_promo_date=last_promo_date,
        promo_pattern=pattern,
    )
