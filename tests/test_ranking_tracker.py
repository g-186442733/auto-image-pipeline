import pytest
from datetime import datetime, timedelta, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.asin_ranking import ASINRanking
from pipeline.layers.ranking_tracker import (
    record_ranking,
    get_ranking_history,
    get_ranking_summary,
)

TEST_PID = 10020

_mem_engine = create_engine("sqlite:///:memory:")
_MemSession = sessionmaker(bind=_mem_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(_mem_engine)
    session = _MemSession()
    try:
        session.add(Project(id=TEST_PID, name="Ranking Test", status="draft"))
        session.commit()
    finally:
        session.close()
    yield
    Base.metadata.drop_all(_mem_engine)


class TestRecordRanking:
    def test_creates_record(self):
        session = _MemSession()
        try:
            r = record_ranking(
                session, TEST_PID, "B0TEST123", "wireless earbuds", 5, "Electronics"
            )
            assert r.id is not None
            assert r.asin == "B0TEST123"
            assert r.keyword == "wireless earbuds"
            assert r.rank_position == 5
            assert r.category_name == "Electronics"
        finally:
            session.close()

    def test_multiple_records_same_asin(self):
        session = _MemSession()
        try:
            record_ranking(session, TEST_PID, "B0TEST123", "earbuds", 10, "Electronics")
            record_ranking(session, TEST_PID, "B0TEST123", "earbuds", 8, "Electronics")
            count = (
                session.query(ASINRanking)
                .filter_by(project_id=TEST_PID, asin="B0TEST123")
                .count()
            )
            assert count == 2
        finally:
            session.close()


class TestGetRankingHistory:
    def test_returns_time_series(self):
        session = _MemSession()
        try:
            record_ranking(session, TEST_PID, "B0TEST123", "earbuds", 10, "Electronics")
            record_ranking(session, TEST_PID, "B0TEST123", "earbuds", 7, "Electronics")
            history = get_ranking_history(session, TEST_PID, "B0TEST123", "earbuds")
            assert isinstance(history, list)
            assert len(history) == 2
            assert history[0]["rank_position"] == 10
        finally:
            session.close()

    def test_empty_history(self):
        session = _MemSession()
        try:
            history = get_ranking_history(session, TEST_PID, "B0NONE", "none")
            assert history == []
        finally:
            session.close()

    def test_filters_by_days(self):
        session = _MemSession()
        try:
            r = record_ranking(
                session, TEST_PID, "B0TEST123", "earbuds", 10, "Electronics"
            )
            r.tracked_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60)
            session.commit()
            record_ranking(session, TEST_PID, "B0TEST123", "earbuds", 5, "Electronics")
            history = get_ranking_history(
                session, TEST_PID, "B0TEST123", "earbuds", days=30
            )
            assert len(history) == 1
            assert history[0]["rank_position"] == 5
        finally:
            session.close()


class TestGetRankingSummary:
    def test_returns_latest_per_asin(self):
        session = _MemSession()
        try:
            record_ranking(session, TEST_PID, "B0AAA", "kw1", 20, "Cat1")
            record_ranking(session, TEST_PID, "B0AAA", "kw1", 15, "Cat1")
            record_ranking(session, TEST_PID, "B0BBB", "kw2", 3, "Cat2")
            summary = get_ranking_summary(session, TEST_PID)
            assert isinstance(summary, list)
            assert len(summary) == 2
            asin_map = {s["asin"]: s for s in summary}
            assert asin_map["B0AAA"]["rank_position"] == 15
            assert asin_map["B0BBB"]["rank_position"] == 3
        finally:
            session.close()

    def test_empty_project(self):
        session = _MemSession()
        try:
            summary = get_ranking_summary(session, TEST_PID)
            assert summary == []
        finally:
            session.close()


class TestRankingRoutes:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr("pipeline.web.app.get_session", _MemSession)
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            from tests.conftest import inject_auth
            inject_auth(c)
            yield c

    def test_get_rankings_page(self, client):
        resp = client.get(f"/project/{TEST_PID}/rankings")
        assert resp.status_code == 200
        assert b"Ranking" in resp.data or b"ranking" in resp.data.lower()

    def test_rankings_page_not_found(self, client):
        resp = client.get("/project/99999/rankings")
        assert resp.status_code == 404
