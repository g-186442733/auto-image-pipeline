"""Tests for fetch_reviews and fetch_qa (Task 2)."""

import json
from unittest.mock import patch, MagicMock

import pytest

from pipeline.layers.amazon_data import (
    fetch_reviews,
    fetch_qa,
    fetch_category_top,
    fetch_asin_detail,
)
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models import Base, get_engine, get_session


REQUIRED_REVIEW_KEYS = {"title", "body", "rating", "date", "verified_purchase"}
REQUIRED_QA_KEYS = {"question", "answer", "votes"}


class TestFetchReviewsFallback:
    def test_returns_list_on_missing_key(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_reviews("B000TEST01")
        assert isinstance(result, list)
        assert len(result) >= 5

    def test_review_keys_present(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_reviews("B000TEST01")
        for item in result:
            assert REQUIRED_REVIEW_KEYS <= set(item.keys())

    def test_never_returns_empty(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_reviews("B000TEST01")
        assert result


class TestFetchQaFallback:
    def test_returns_list_on_missing_key(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_qa("B000TEST01")
        assert isinstance(result, list)
        assert len(result) >= 5

    def test_qa_keys_present(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_qa("B000TEST01")
        for item in result:
            assert REQUIRED_QA_KEYS <= set(item.keys())

    def test_never_returns_empty(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_qa("B000TEST01")
        assert result


class TestFetchReviewsShape:
    def test_rating_is_numeric(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_reviews("B000TEST01")
        for item in result:
            assert isinstance(item["rating"], (int, float))

    def test_verified_purchase_is_bool(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_reviews("B000TEST01")
        for item in result:
            assert isinstance(item["verified_purchase"], bool)


class TestFetchQaShape:
    def test_votes_is_int(self):
        with patch("pipeline.layers.amazon_data.config") as mock_cfg:
            mock_cfg.keepa_api_key = ""
            result = fetch_qa("B000TEST01")
        for item in result:
            assert isinstance(item["votes"], int)


class TestTopNDefault:
    def test_default_top_n_is_50(self):
        import inspect

        sig = inspect.signature(fetch_category_top)
        assert sig.parameters["top_n"].default == 50

    def test_top_n_capped_at_50(self):
        from pipeline.layers.amazon_data import _MAX_TOP_N

        assert _MAX_TOP_N == 50


class TestFetchAsinDetailEnriched:
    def test_returns_all_enriched_fields(self):
        mock_response = {
            "products": [
                {
                    "title": "Test Product",
                    "csv": [[100, 2999]],
                    "salesRanks": {"cat1": [5, 3]},
                    "reviewCount": 150,
                    "rating": 45,
                    "imagesCSV": "ABC123.jpg,DEF456",
                    "features": ["Feature 1", "Feature 2"],
                    "description": "A great product",
                }
            ]
        }
        with (
            patch("pipeline.layers.amazon_data._api_key", return_value="fake"),
            patch("pipeline.layers.amazon_data._get", return_value=mock_response),
            patch("pipeline.layers.amazon_data.time"),
        ):
            result = fetch_asin_detail("B000TEST01")

        assert result["title"] == "Test Product"
        assert result["price"] == 29.99
        assert result["review_count"] == 150
        assert result["rating"] == 45
        assert result["bsr_rank"] == 3
        assert result["main_image_url"].endswith("ABC123.jpg")
        assert result["bullet_points"] == ["Feature 1", "Feature 2"]
        assert result["description"] == "A great product"

    def test_missing_fields_graceful(self):
        mock_response = {"products": [{"title": "Minimal"}]}
        with (
            patch("pipeline.layers.amazon_data._api_key", return_value="fake"),
            patch("pipeline.layers.amazon_data._get", return_value=mock_response),
            patch("pipeline.layers.amazon_data.time"),
        ):
            result = fetch_asin_detail("B000TEST01")

        assert result["title"] == "Minimal"
        assert result["price"] is None
        assert result["main_image_url"] is None
        assert result["bullet_points"] == []
        assert result["description"] is None


class TestCompetitorListingEnrichedFields:
    def test_all_new_fields_persist(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as SASession

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with SASession(engine) as session:
            cl = CompetitorListing(
                asin="B000TEST01",
                title="Test Product",
                price=29.99,
                rating=4.5,
                review_count=150,
                bullet_points=json.dumps(["Feature 1", "Feature 2"]),
                description="A great product",
                main_image_url="https://example.com/img.jpg",
                category_rank=42,
            )
            session.add(cl)
            session.commit()

            loaded = session.query(CompetitorListing).filter_by(asin="B000TEST01").one()
            assert loaded.title == "Test Product"
            assert loaded.price == 29.99
            assert loaded.rating == 4.5
            assert loaded.review_count == 150
            assert json.loads(loaded.bullet_points) == ["Feature 1", "Feature 2"]
            assert loaded.description == "A great product"
            assert loaded.main_image_url == "https://example.com/img.jpg"
            assert loaded.category_rank == 42

    def test_bullet_points_stored_as_json_array(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as SASession

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        bullets = ["Waterproof", "Durable", "Lightweight"]
        with SASession(engine) as session:
            cl = CompetitorListing(
                asin="B000TEST02",
                bullet_points=json.dumps(bullets),
            )
            session.add(cl)
            session.commit()

            loaded = session.query(CompetitorListing).filter_by(asin="B000TEST02").one()
            parsed = json.loads(loaded.bullet_points)
            assert isinstance(parsed, list)
            assert parsed == bullets


class TestFetchCategoryTopHandlesFewerThan50:
    def test_fewer_asins_no_error(self):
        mock_response = {"bestSellersList": {"asinList": ["B001", "B002", "B003"]}}
        with (
            patch("pipeline.layers.amazon_data._api_key", return_value="fake"),
            patch("pipeline.layers.amazon_data._get", return_value=mock_response),
            patch("pipeline.layers.amazon_data.time"),
        ):
            result = fetch_category_top("Electronics", top_n=50)
        assert len(result) == 3
