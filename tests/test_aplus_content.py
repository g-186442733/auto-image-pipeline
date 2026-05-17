from __future__ import annotations

import io
import pytest


def _make_in_memory_db():
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")
    return "sqlite:///:memory:"


def _session(db_url="sqlite:///:memory:"):
    from pipeline.models.base import get_session

    return get_session(db_url)


def _create_project(session):
    from pipeline.models.project import Project

    p = Project(
        name="test-proj", asin="B0TESTTEST", category="Electronics", status="draft"
    )
    session.add(p)
    session.commit()
    return p.id


class TestAPlusContentModel:
    def setup_method(self):
        self.db_url = _make_in_memory_db()
        self.sess = _session(self.db_url)
        self.project_id = _create_project(self.sess)

    def teardown_method(self):
        self.sess.close()

    def test_create_and_read(self):
        from pipeline.models.aplus_content import APlusContent

        rec = APlusContent(
            project_id=self.project_id,
            module_type="HERO",
            headline="Test Headline",
            body_text="Test body",
            image_refs='["img1.png"]',
            position_index=0,
        )
        self.sess.add(rec)
        self.sess.commit()

        loaded = self.sess.get(APlusContent, rec.id)
        assert loaded is not None
        assert loaded.module_type == "HERO"
        assert loaded.headline == "Test Headline"
        assert loaded.project_id == self.project_id

    def test_update(self):
        from pipeline.models.aplus_content import APlusContent

        rec = APlusContent(project_id=self.project_id, module_type="BENEFIT")
        self.sess.add(rec)
        self.sess.commit()

        rec.headline = "Updated"
        self.sess.commit()

        loaded = self.sess.get(APlusContent, rec.id)
        assert loaded.headline == "Updated"

    def test_delete(self):
        from pipeline.models.aplus_content import APlusContent

        rec = APlusContent(project_id=self.project_id, module_type="BRAND_STORY")
        self.sess.add(rec)
        self.sess.commit()
        rec_id = rec.id

        self.sess.delete(rec)
        self.sess.commit()
        assert self.sess.get(APlusContent, rec_id) is None

    def test_relationship_to_project(self):
        from pipeline.models.aplus_content import APlusContent

        rec = APlusContent(project_id=self.project_id, module_type="HERO")
        self.sess.add(rec)
        self.sess.commit()

        assert rec.project is not None
        assert rec.project.name == "test-proj"


class TestUploadEndpoint:
    def setup_method(self):
        _make_in_memory_db()
        from pipeline.web.app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        from tests.conftest import inject_auth
        inject_auth(self.client)

    def test_upload_happy_path(self, tmp_path, monkeypatch):
        import pipeline.web.app as app_mod

        monkeypatch.chdir(tmp_path)

        data = {
            "file": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100), "test.png"),
        }
        resp = self.client.post(
            "/api/projects/1/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "path" in body
        assert "test.png" in body["path"]

    def test_upload_invalid_type(self):
        data = {
            "file": (io.BytesIO(b"not an image"), "test.txt"),
        }
        resp = self.client.post(
            "/api/projects/1/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    def test_upload_oversized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        big_data = b"\x00" * (11 * 1024 * 1024)
        data = {
            "file": (io.BytesIO(big_data), "big.png"),
        }
        resp = self.client.post(
            "/api/projects/1/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 413
