"""Amazon / Keepa data-fetching layer.

Public API
----------
fetch_category_top  – top-N competitors in a Keepa category
fetch_asin_detail   – single ASIN metadata dict
scrape_listing_images – image URLs for an ASIN (max 9)
"""

import time
from typing import Optional

import httpx

from pipeline.config import config
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.utils.logger import setup_logger

__all__ = [
    "fetch_category_top",
    "fetch_asin_detail",
    "scrape_listing_images",
]

logger = setup_logger("aip.amazon_data")

KEEPA_BASE = "https://api.keepa.com"

MARKET_DOMAIN: dict[str, int] = {
    "US": 1,
    "UK": 2,
    "DE": 3,
    "JP": 6,
}

_MAX_TOP_N = 50
_RATE_LIMIT_SLEEP = 1.0


def _api_key() -> str:
    key: str = config.keepa_api_key or ""
    if not key:
        raise ValueError(
            "E_AMAZON_001: keepa_api_key is empty – set it in config before calling Amazon layer."
        )
    return key


def _domain(market: str) -> int:
    d = MARKET_DOMAIN.get(market.upper())
    if d is None:
        raise ValueError(
            f"E_AMAZON_001: Unknown market '{market}'. Supported: {list(MARKET_DOMAIN.keys())}"
        )
    return d


def _get(url: str, params: dict) -> dict:
    """Thin httpx wrapper; surfaces rate-limit and unexpected errors."""
    logger.debug(
        "GET %s params=%s", url, {k: v for k, v in params.items() if k != "key"}
    )
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)

    if resp.status_code == 429:
        raise ValueError("E_AMAZON_003: Keepa API rate limit exceeded (HTTP 429).")

    if resp.status_code == 404:
        raise ValueError("E_AMAZON_004: Resource not found (HTTP 404).")

    resp.raise_for_status()
    return resp.json()


def fetch_category_top(category: str, market: str = "US", top_n: int = 20) -> list:
    """Fetch top N competitors in a category via Keepa API.

    Returns list[AmazonBenchmark] ORM instances (NOT committed to DB yet — caller commits).
    Raises ValueError("E_AMAZON_001: ...") if keepa_api_key is empty.
    Raises ValueError("E_AMAZON_002: ...") if category not found (Keepa returns empty).
    Raises ValueError("E_AMAZON_003: ...") if rate limited (HTTP 429).
    """
    key = _api_key()
    domain = _domain(market)
    top_n = min(int(top_n), _MAX_TOP_N)

    url = f"{KEEPA_BASE}/bestsellers"
    params = {
        "key": key,
        "domain": domain,
        "category": category,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    asin_list: list[str] = data.get("asinList") or []
    if not asin_list:
        raise ValueError(
            f"E_AMAZON_002: Category '{category}' not found or returned no ASINs from Keepa."
        )

    asin_list = asin_list[:top_n]
    logger.info(
        "fetch_category_top: category=%s market=%s asins=%d",
        category,
        market,
        len(asin_list),
    )

    benchmarks: list[AmazonBenchmark] = []
    for slot_index, asin in enumerate(asin_list):
        bm = AmazonBenchmark(
            competitor_asin=asin[:20],
            slot_index=slot_index,
        )
        benchmarks.append(bm)

    return benchmarks


def fetch_asin_detail(asin: str) -> dict:
    """Fetch single ASIN details via Keepa API.

    Returns dict with keys: title, price, bsr_rank, review_count, rating, category_path.
    Raises ValueError("E_AMAZON_004: ...") if ASIN not found.
    """
    key = _api_key()

    url = f"{KEEPA_BASE}/product"
    params = {
        "key": key,
        "domain": 1,
        "asin": asin,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    products: list[dict] = data.get("products") or []
    if not products:
        raise ValueError(f"E_AMAZON_004: ASIN '{asin}' not found in Keepa.")

    p = products[0]
    logger.info("fetch_asin_detail: asin=%s title=%.40s", asin, p.get("title", ""))

    # price in keepa csv is stored as cents×100 in csv[0][-1]; fall back gracefully
    csv = p.get("csv") or []
    price_raw: Optional[int] = None
    if csv and isinstance(csv[0], list) and len(csv[0]) >= 2:
        price_raw = csv[0][-1]
    price = (price_raw / 100.0) if (price_raw and price_raw > 0) else None

    # salesRanks maps category-id → rank history list; first key is main category
    sales_ranks: dict = p.get("salesRanks") or {}
    bsr_rank: Optional[int] = None
    category_path: Optional[str] = None
    if sales_ranks:
        first_cat = next(iter(sales_ranks))
        rank_list = sales_ranks[first_cat]
        if rank_list and isinstance(rank_list, list):
            bsr_rank = rank_list[-1]
        category_path = first_cat

    return {
        "title": p.get("title"),
        "price": price,
        "bsr_rank": bsr_rank,
        "review_count": p.get("reviewCount"),
        "rating": p.get("rating"),
        "category_path": category_path,
    }


def scrape_listing_images(asin: str) -> list[str]:
    """Scrape listing image URLs for an ASIN via Keepa API.

    Returns list of image URL strings (max 9).
    Raises ValueError("E_AMAZON_004: ...") if ASIN not found.
    """
    key = _api_key()

    url = f"{KEEPA_BASE}/product"
    params = {
        "key": key,
        "domain": 1,
        "asin": asin,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    products: list[dict] = data.get("products") or []
    if not products:
        raise ValueError(f"E_AMAZON_004: ASIN '{asin}' not found in Keepa.")

    p = products[0]

    # imagesCSV holds comma-separated Keepa image codes;
    # full URL = https://images-na.ssl-images-amazon.com/images/I/<code>.jpg
    images_csv: str = p.get("imagesCSV") or ""
    codes = [c.strip() for c in images_csv.split(",") if c.strip()]

    image_urls = [
        f"https://images-na.ssl-images-amazon.com/images/I/{code}.jpg"
        for code in codes[:9]
    ]

    logger.info("scrape_listing_images: asin=%s images=%d", asin, len(image_urls))
    return image_urls
