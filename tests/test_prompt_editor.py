"""TDD tests for prompt editor UI (Task 13)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.prompt_asset import PromptAsset
from pipeline.layers.prompt_manager import update_prompt_text

TEST_PID = 10013

_mem_engine = create_engine("sqlite:///:memory:")
_MemSession = sessionmaker(bind=_mem_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    """Create fresh in-memory tables for each test."""
    Base.metadata.create_all(_mem_engine)
    session = _MemSession()
    try:
        session.add(Project(id=TEST_PID, name="Editor Test Project", status="draft"))
        session.add(
            PromptAsset(
                project_id=TEST_PID,
                slot_index=1,
                prompt_text="original prompt",
                negative_prompt="",
                model_name="flux-1.1-pro",
                version=1,
            )
        )
        session.add(
            PromptAsset(
                project_id=TEST_PID,
                slot_index=3,
                prompt_text="slot three prompt",
                negative_prompt="bad quality",
                model_name="flux-1.1-pro",
                version=1,
            )
        )
        session.commit()
    finally:
        session.close()
    yield
    Base.metadata.drop_all(_mem_engine)


class TestUpdatePromptText:
    def test_updates_text_and_increments_version(self):
        session = _MemSession()
        try:
            result = update_prompt_text(session, TEST_PID, "slot_1", "new prompt text")
            assert result is True
            asset = (
                session.query(PromptAsset)
                .filter_by(project_id=TEST_PID, slot_index=1)
                .first()
            )
            assert asset.prompt_text == "new prompt text"
            assert asset.version == 2
        finally:
            session.close()

    def test_returns_false_for_missing_slot(self):
        session = _MemSession()
        try:
            result = update_prompt_text(session, TEST_PID, "slot_7", "text")
            assert result is False
        finally:
            session.close()

    def test_returns_false_for_missing_project(self):
        session = _MemSession()
        try:
            result = update_prompt_text(session, 99999, "slot_1", "text")
            assert result is False
        finally:
            session.close()

    def test_slot_name_to_index_mapping(self):
        session = _MemSession()
        try:
            result = update_prompt_text(session, TEST_PID, "slot_3", "updated three")
            assert result is True
            asset = (
                session.query(PromptAsset)
                .filter_by(project_id=TEST_PID, slot_index=3)
                .first()
            )
            assert asset.prompt_text == "updated three"
        finally:
            session.close()

    def test_invalid_slot_name_returns_false(self):
        session = _MemSession()
        try:
            result = update_prompt_text(session, TEST_PID, "bad_slot", "text")
            assert result is False
        finally:
            session.close()


class TestPromptEditorRoutes:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr("pipeline.web.app.get_session", _MemSession)
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_get_prompt_list(self, client):
        resp = client.get(f"/project/{TEST_PID}/prompts")
        assert resp.status_code == 200
        assert b"original prompt" in resp.data

    def test_get_prompt_editor(self, client):
        resp = client.get(f"/project/{TEST_PID}/prompts/slot_1")
        assert resp.status_code == 200
        assert b"original prompt" in resp.data
        assert b"textarea" in resp.data.lower()

    def test_get_prompt_editor_missing_slot(self, client):
        resp = client.get(f"/project/{TEST_PID}/prompts/slot_7")
        assert resp.status_code == 404

    def test_post_prompt_update_redirects(self, client):
        resp = client.post(
            f"/project/{TEST_PID}/prompts/slot_1",
            data={"prompt_text": "updated via form"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_post_prompt_update_saves(self, client):
        client.post(
            f"/project/{TEST_PID}/prompts/slot_1",
            data={"prompt_text": "saved prompt"},
        )
        session = _MemSession()
        try:
            asset = (
                session.query(PromptAsset)
                .filter_by(project_id=TEST_PID, slot_index=1)
                .first()
            )
            assert asset.prompt_text == "saved prompt"
        finally:
            session.close()
