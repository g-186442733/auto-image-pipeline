from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.knowledge_entry import KnowledgeEntry, VALID_CATEGORIES
from pipeline.layers.knowledge_base import (
    add_entry,
    search_entries,
    get_popular_entries,
    increment_usage,
)


@pytest.fixture(autouse=True)
def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    _Session = sessionmaker(bind=engine)
    session = _Session()
    project = Project(name="kb-test")
    session.add(project)
    session.commit()
    yield session, project.id
    session.close()
    Base.metadata.drop_all(engine)


class TestAddEntry:
    def test_creates_entry(self, _db):
        session, pid = _db
        entry = add_entry(session, pid, "qa_lesson", "Test Title", "Test content")
        assert entry.id is not None
        assert entry.title == "Test Title"
        assert entry.category == "qa_lesson"

    def test_nullable_project_id(self, _db):
        session, _ = _db
        entry = add_entry(session, None, "style_rule", "Global Rule", "content")
        assert entry.source_project_id is None

    def test_invalid_category_raises(self, _db):
        session, pid = _db
        with pytest.raises(ValueError, match="Invalid category"):
            add_entry(session, pid, "bad_cat", "T", "C")

    def test_tags_stored(self, _db):
        session, pid = _db
        entry = add_entry(session, pid, "prompt_pattern", "T", "C", tags="a,b,c")
        assert entry.tags == "a,b,c"

    def test_default_usage_count(self, _db):
        session, pid = _db
        entry = add_entry(session, pid, "qa_lesson", "T", "C")
        assert entry.usage_count == 0


class TestSearchEntries:
    def test_search_by_title(self, _db):
        session, pid = _db
        add_entry(session, pid, "qa_lesson", "Background tips", "some content")
        add_entry(session, pid, "qa_lesson", "Color guide", "other content")
        results = search_entries(session, "Background")
        assert len(results) == 1
        assert results[0].title == "Background tips"

    def test_search_by_content(self, _db):
        session, pid = _db
        add_entry(session, pid, "style_rule", "Rule1", "use warm colors")
        results = search_entries(session, "warm")
        assert len(results) == 1

    def test_filter_by_category(self, _db):
        session, pid = _db
        add_entry(session, pid, "qa_lesson", "T1", "C1")
        add_entry(session, pid, "style_rule", "T2", "C2")
        results = search_entries(session, "", category="qa_lesson")
        assert all(r.category == "qa_lesson" for r in results)

    def test_limit(self, _db):
        session, pid = _db
        for i in range(5):
            add_entry(session, pid, "qa_lesson", f"T{i}", f"C{i}")
        results = search_entries(session, "", limit=3)
        assert len(results) == 3

    def test_empty_query_returns_all(self, _db):
        session, pid = _db
        add_entry(session, pid, "qa_lesson", "T1", "C1")
        add_entry(session, pid, "style_rule", "T2", "C2")
        results = search_entries(session, "")
        assert len(results) == 2


class TestGetPopularEntries:
    def test_ordered_by_usage(self, _db):
        session, pid = _db
        e1 = add_entry(session, pid, "qa_lesson", "Low", "C")
        e2 = add_entry(session, pid, "qa_lesson", "High", "C")
        e2.usage_count = 10
        session.commit()
        results = get_popular_entries(session)
        assert results[0].title == "High"

    def test_filter_by_category(self, _db):
        session, pid = _db
        add_entry(session, pid, "qa_lesson", "T1", "C1")
        add_entry(session, pid, "style_rule", "T2", "C2")
        results = get_popular_entries(session, category="style_rule")
        assert len(results) == 1
        assert results[0].category == "style_rule"


class TestIncrementUsage:
    def test_increments(self, _db):
        session, pid = _db
        entry = add_entry(session, pid, "qa_lesson", "T", "C")
        assert entry.usage_count == 0
        updated = increment_usage(session, entry.id)
        assert updated.usage_count == 1

    def test_nonexistent_returns_none(self, _db):
        session, _ = _db
        assert increment_usage(session, 9999) is None


class TestValidCategories:
    def test_has_all_four(self):
        assert "prompt_pattern" in VALID_CATEGORIES
        assert "qa_lesson" in VALID_CATEGORIES
        assert "style_rule" in VALID_CATEGORIES
        assert "client_preference" in VALID_CATEGORIES


class TestKnowledgeRoute:
    @pytest.fixture()
    def client(self):
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            from tests.conftest import inject_auth
            inject_auth(c)
            yield c

    def test_knowledge_page_200(self, client):
        resp = client.get("/knowledge")
        assert resp.status_code == 200

    def test_knowledge_page_contains_categories(self, client):
        resp = client.get("/knowledge")
        html = resp.data.decode()
        assert "prompt_pattern" in html
        assert "qa_lesson" in html

    def test_knowledge_search_param(self, client):
        resp = client.get("/knowledge?q=test")
        assert resp.status_code == 200

    def test_knowledge_category_filter(self, client):
        resp = client.get("/knowledge?category=style_rule")
        assert resp.status_code == 200
