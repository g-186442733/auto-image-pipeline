"""Amazon / Keepa data-fetching layer.

Public API
----------
fetch_category_top  – top-N competitors in a Keepa category
fetch_asin_detail   – single ASIN metadata dict
scrape_listing_images – image URLs for an ASIN (max 9)
"""

import os
import time
from typing import Optional
import requests

from pipeline.config import config
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.utils.logger import setup_logger

__all__ = [
    "fetch_category_top",
    "fetch_asin_detail",
    "fetch_asins_price_batch",
    "scrape_listing_images",
    "fetch_reviews",
    "fetch_qa",
]

logger = setup_logger("aip.amazon_data")


class KeepaDataError(Exception):
    """Raised when Keepa API fails to return usable data."""


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


_RETRY_MAX = 3
_RETRY_BACKOFF = 2.0  # 秒，每次翻倍：2s → 4s → 8s


def _get(url: str, params: dict) -> dict:
    """requests 封装；处理限速和异常错误。失败后最多重试 3 次（指数退避）。"""
    logger.debug(
        "GET %s params=%s", url, {k: v for k, v in params.items() if k != "key"}
    )
    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or "http://127.0.0.1:7890"
    )
    proxies = {"http": proxy_url, "https": proxy_url}

    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            resp = requests.get(url, params=params, proxies=proxies, timeout=30)

            # 不重试的终态错误
            if resp.status_code == 429:
                raise ValueError(
                    "E_AMAZON_003: Keepa API rate limit exceeded (HTTP 429)."
                )
            if resp.status_code == 404:
                raise ValueError("E_AMAZON_004: Resource not found (HTTP 404).")
            if resp.status_code == 401 or resp.status_code == 403:
                raise ValueError(
                    f"E_AMAZON_001: Keepa API auth error (HTTP {resp.status_code})."
                )

            resp.raise_for_status()
            return resp.json()

        except ValueError:
            # 终态错误直接抛出，不重试
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _RETRY_MAX:
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "_get attempt %d/%d failed (%s), retrying in %.1fs…",
                    attempt,
                    _RETRY_MAX,
                    exc,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error("_get failed after %d attempts: %s", _RETRY_MAX, exc)

    raise last_exc


def fetch_category_top(category: str, market: str = "US", top_n: int = 50) -> list:
    """Fetch top N competitors in a category via Keepa API.

    Returns list[AmazonBenchmark] ORM instances (NOT committed to DB yet — caller commits).
    Raises ValueError("E_AMAZON_001: ...") if keepa_api_key is empty.
    Raises ValueError("E_AMAZON_002: ...") if category not found (Keepa returns empty).
    Raises ValueError("E_AMAZON_003: ...") if rate limited (HTTP 429).
    """
    key = _api_key()
    domain = _domain(market)
    top_n = min(int(top_n), _MAX_TOP_N)

    if not str(category).strip().isdigit():
        raise ValueError(
            f"E_AMAZON_005: Category must be a numeric Keepa category ID (e.g. '172541'), "
            f"not a text name (got: '{category}'). "
            f"Look up the numeric ID at https://www.keepa.com/#!categorytree"
        )

    url = f"{KEEPA_BASE}/bestsellers"
    params = {
        "key": key,
        "domain": domain,
        "category": category,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    asin_list: list[str] = (data.get("bestSellersList") or data).get("asinList") or []
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
    for slot_index, asin in enumerate(asin_list, start=1):
        image_slots: list[tuple[int, str]] = []
        try:
            image_slots = scrape_listing_images(asin)
        except Exception as exc:
            logger.warning(
                "scrape_listing_images failed for %s, falling back to fetch_asin_detail: %s",
                asin,
                exc,
            )
            try:
                detail = fetch_asin_detail(asin)
                main = detail.get("main_image_url")
                if main:
                    image_slots = [(1, main)]
            except Exception as exc2:
                logger.warning(
                    "fetch_asin_detail also failed for %s: %s",
                    asin,
                    exc2,
                )

        if not image_slots:
            bm = AmazonBenchmark(
                competitor_asin=asin[:20],
                slot_index=slot_index,
                image_slot=None,
                image_url=None,
            )
            benchmarks.append(bm)
        else:
            for img_slot, img_url in image_slots:
                bm = AmazonBenchmark(
                    competitor_asin=asin[:20],
                    slot_index=slot_index,
                    image_slot=img_slot,
                    image_url=img_url,
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
        "rating": 1,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    products: list[dict] = data.get("products") or []
    if not products:
        raise ValueError(f"E_AMAZON_004: ASIN '{asin}' not found in Keepa.")

    p = products[0]
    logger.info("fetch_asin_detail: asin=%s title=%.40s", asin, p.get("title", ""))

    csv = p.get("csv") or []

    price_raw: Optional[int] = None
    if csv and isinstance(csv[0], list) and len(csv[0]) >= 2:
        price_raw = csv[0][-1]
    price = (price_raw / 100.0) if (price_raw and price_raw > 0) else None

    sales_ranks: dict = p.get("salesRanks") or {}
    bsr_rank: Optional[int] = None
    category_path: Optional[str] = None
    if sales_ranks:
        first_cat = next(iter(sales_ranks))
        rank_list = sales_ranks[first_cat]
        if rank_list and isinstance(rank_list, list):
            bsr_rank = rank_list[-1]

    category_tree: list[dict] = p.get("categoryTree") or []
    if category_tree:
        category_path = " › ".join(
            node["name"] for node in category_tree if node.get("name")
        )

    # images 列表（新版 Keepa API 字段）→ 主图 URL
    # 每个元素格式：{'l': 'xxx.jpg', 'lH': 1000, 'lW': 1000, 'm': 'yyy.jpg', ...}
    images_list: list[dict] = p.get("images") or []
    main_image_url: Optional[str] = None
    if images_list and isinstance(images_list[0], dict):
        code = images_list[0].get("l") or images_list[0].get("m") or ""
        if code:
            fname = code if code.endswith(".jpg") else code + ".jpg"
            main_image_url = f"https://images-na.ssl-images-amazon.com/images/I/{fname}"

    features: list[str] = p.get("features") or []
    description_val: Optional[str] = p.get("description")

    # rating/reviewCount：优先顶级字段，回退到 csv[16]/csv[17]
    # csv[16]=RATING (0-50, ÷10=星级), csv[17]=COUNT_REVIEWS，需 rating=1 参数才填充
    review_count: Optional[int] = p.get("reviewCount")
    rating_raw: Optional[int] = p.get("rating")
    if review_count is None and len(csv) > 17 and csv[17]:
        review_count = csv[17][-1] if csv[17][-1] > 0 else None
    if rating_raw is None and len(csv) > 16 and csv[16]:
        rating_raw = csv[16][-1] if csv[16][-1] > 0 else None
    rating: Optional[float] = (rating_raw / 10.0) if rating_raw else None

    return {
        "title": p.get("title"),
        "price": price,
        "bsr_rank": bsr_rank,
        "review_count": review_count,
        "rating": rating,
        "category_path": category_path,
        "main_image_url": main_image_url,
        "bullet_points": features,
        "description": description_val,
    }


def scrape_listing_images(asin: str) -> list[tuple[int, str]]:
    """Scrape listing image URLs for an ASIN via Keepa API.

    Returns list of (image_slot, url) tuples (max 9), where image_slot starts at 1.
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

    images_list: list[dict] = p.get("images") or []
    image_slots: list[tuple[int, str]] = []
    for i, img in enumerate(images_list[:9], start=1):
        if not isinstance(img, dict):
            continue
        code = img.get("l") or img.get("m") or ""
        if code:
            fname = code if code.endswith(".jpg") else code + ".jpg"
            image_slots.append(
                (i, f"https://images-na.ssl-images-amazon.com/images/I/{fname}")
            )

    logger.info("scrape_listing_images: asin=%s images=%d", asin, len(image_slots))
    return image_slots


def fetch_reviews(asin: str, market: str = "us", max_reviews: int = 20) -> list[dict]:
    """使用 Playwright 抓取 Amazon 评论页，返回含 title/body/rating 的评论列表。

    Keepa API 不提供评论原文（仅提供评论计数历史），因此改用浏览器自动化抓取。
    """
    import asyncio
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup

    # Amazon 评论页 URL（按最新排序，取第1页）
    _MARKET_DOMAINS = {
        "us": "www.amazon.com",
        "uk": "www.amazon.co.uk",
        "de": "www.amazon.de",
        "jp": "www.amazon.co.jp",
    }
    domain = _MARKET_DOMAINS.get(market, "www.amazon.com")
    url = f"https://{domain}/product-reviews/{asin}/?sortBy=recent&pageNumber=1&pageSize=10"

    async def _scrape() -> list[dict]:
        proxy_env = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        proxy_cfg = None
        if proxy_env:
            proxy_cfg = {"server": proxy_env}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_cfg,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = await ctx.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 等待评论容器出现
                await page.wait_for_selector("[data-hook='review']", timeout=15000)
            except Exception as exc:
                logger.warning("fetch_reviews playwright wait failed: %s", exc)

            html = await page.content()
            await browser.close()
            return html

    try:
        html = asyncio.run(_scrape())
    except Exception as exc:
        raise KeepaDataError(
            f"fetch_reviews playwright failed for ASIN {asin}: {exc}"
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    review_nodes = soup.select("[data-hook='review']")

    if not review_nodes:
        # CAPTCHA 或其他阻断
        raise KeepaDataError(
            f"fetch_reviews: no reviews found for ASIN {asin} "
            "(possible CAPTCHA or page structure change)"
        )

    results: list[dict] = []
    for node in review_nodes[:max_reviews]:
        title_el = node.select_one("[data-hook='review-title'] span:not([class])")
        title = title_el.get_text(strip=True) if title_el else ""

        body_el = node.select_one("[data-hook='review-body'] span")
        body = body_el.get_text(strip=True) if body_el else ""

        # "5.0 out of 5 stars" → 5.0
        rating_el = node.select_one("[data-hook='review-star-rating'] span")
        rating_text = rating_el.get_text(strip=True) if rating_el else "0"
        try:
            rating = float(rating_text.split()[0])
        except (ValueError, IndexError):
            rating = None

        date_el = node.select_one("[data-hook='review-date']")
        date_str = date_el.get_text(strip=True) if date_el else ""

        vp_el = node.select_one("[data-hook='avp-badge']")
        verified = vp_el is not None

        if title or body:
            results.append(
                {
                    "title": title,
                    "body": body,
                    "rating": rating,
                    "date": date_str,
                    "verified_purchase": verified,
                }
            )

    if not results:
        raise KeepaDataError(f"fetch_reviews: parsed 0 reviews for ASIN {asin}")

    logger.info("fetch_reviews: asin=%s count=%d (playwright)", asin, len(results))
    return results


def fetch_qa(asin: str, market: str = "us") -> list[dict]:
    try:
        key = _api_key()
        domain = _domain(market)
        time.sleep(_RATE_LIMIT_SLEEP)
        data = _get(
            f"{KEEPA_BASE}/product",
            {"key": key, "domain": domain, "asin": asin, "qa": 1},
        )
    except (ValueError, requests.HTTPError) as exc:
        raise KeepaDataError(
            f"Keepa API failed for ASIN {asin}: Q&A unavailable"
        ) from exc

    products: list[dict] = data.get("products") or []
    if not products:
        raise KeepaDataError(f"Keepa API returned no product data for ASIN {asin}")

    raw_qa: list[dict] = products[0].get("questions") or []
    if not raw_qa:
        raise KeepaDataError(f"Keepa API returned no Q&A for ASIN {asin}")

    results: list[dict] = []
    for q in raw_qa:
        results.append(
            {
                "question": q.get("question", ""),
                "answer": q.get("answer", ""),
                "votes": q.get("votes", 0),
            }
        )

    if not results:
        raise KeepaDataError(f"Keepa API returned empty Q&A for ASIN {asin}")
    logger.info("fetch_qa: asin=%s count=%d", asin, len(results))
    return results


def fetch_asins_price_batch(
    asin_list: list[str], market: str = "US"
) -> dict[str, float]:
    """Batch-fetch current prices for a list of ASINs via Keepa /product endpoint.

    Keepa supports up to 100 ASINs per request as a comma-separated list.
    Returns dict[asin, price]. ASINs with no price data are omitted.
    """
    if not asin_list:
        return {}

    key = _api_key()
    domain = _domain(market)

    url = f"{KEEPA_BASE}/product"
    params = {
        "key": key,
        "domain": domain,
        "asin": ",".join(asin_list[:100]),
        "rating": 0,
    }

    data = _get(url, params)
    time.sleep(_RATE_LIMIT_SLEEP)

    products: list[dict] = data.get("products") or []
    prices: dict[str, float] = {}
    for p in products:
        asin = (p.get("asin") or "").strip()
        if not asin:
            continue
        csv = p.get("csv") or []
        price_raw: Optional[int] = None
        if csv and isinstance(csv[0], list) and len(csv[0]) >= 2:
            price_raw = csv[0][-1]
        if price_raw and price_raw > 0:
            prices[asin] = price_raw / 100.0

    logger.info(
        "fetch_asins_price_batch: requested=%d returned=%d with_price=%d",
        len(asin_list),
        len(products),
        len(prices),
    )
    return prices
