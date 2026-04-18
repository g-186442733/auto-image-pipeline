"""Tests for fetch_reviews and fetch_qa (Task 2)."""

from unittest.mock import patch

import pytest

from pipeline.layers.amazon_data import fetch_reviews, fetch_qa


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
