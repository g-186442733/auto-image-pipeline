import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.image_snapshot import ImageSnapshot
from pipeline.layers.change_detector import (
    capture_snapshot,
    detect_changes,
    get_change_history,
)

TEST_PID = 10030

_mem_engine = create_engine("sqlite:///:memory:")
_MemSession = sessionmaker(bind=_mem_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(_mem_engine)
    session = _MemSession()
    try:
        session.add(Project(id=TEST_PID, name="Change Test", status="draft"))
        session.commit()
    finally:
        session.close()
    yield
    Base.metadata.drop_all(_mem_engine)


class TestCaptureSnapshot:
    def test_creates_record(self, tmp_path):
        img = tmp_path / "img.jpg"
        img.write_bytes(b"fake image content")
        session = _MemSession()
        try:
            snap = capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            assert snap.id is not None
            assert snap.asin == "B0TEST"
            assert snap.slot_position == 1
            assert len(snap.image_hash) == 64
        finally:
            session.close()

    def test_same_file_same_hash(self, tmp_path):
        img = tmp_path / "img.jpg"
        img.write_bytes(b"same content")
        session = _MemSession()
        try:
            s1 = capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            s2 = capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            assert s1.image_hash == s2.image_hash
        finally:
            session.close()

    def test_different_file_different_hash(self, tmp_path):
        img1 = tmp_path / "a.jpg"
        img1.write_bytes(b"content A")
        img2 = tmp_path / "b.jpg"
        img2.write_bytes(b"content B")
        session = _MemSession()
        try:
            s1 = capture_snapshot(session, TEST_PID, "B0TEST", str(img1), 1)
            s2 = capture_snapshot(session, TEST_PID, "B0TEST", str(img2), 1)
            assert s1.image_hash != s2.image_hash
        finally:
            session.close()


class TestDetectChanges:
    def test_no_change_same_content(self, tmp_path):
        img = tmp_path / "img.jpg"
        img.write_bytes(b"same")
        session = _MemSession()
        try:
            capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            changes = detect_changes(session, TEST_PID, "B0TEST")
            assert changes == []
        finally:
            session.close()

    def test_detects_change(self, tmp_path):
        img1 = tmp_path / "v1.jpg"
        img1.write_bytes(b"version 1")
        img2 = tmp_path / "v2.jpg"
        img2.write_bytes(b"version 2")
        session = _MemSession()
        try:
            capture_snapshot(session, TEST_PID, "B0TEST", str(img1), 1)
            capture_snapshot(session, TEST_PID, "B0TEST", str(img2), 1)
            changes = detect_changes(session, TEST_PID, "B0TEST")
            assert len(changes) == 1
            assert changes[0]["slot_position"] == 1
            assert "old_hash" in changes[0]
            assert "new_hash" in changes[0]
        finally:
            session.close()

    def test_single_snapshot_no_change(self, tmp_path):
        img = tmp_path / "img.jpg"
        img.write_bytes(b"only one")
        session = _MemSession()
        try:
            capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            changes = detect_changes(session, TEST_PID, "B0TEST")
            assert changes == []
        finally:
            session.close()

    def test_multiple_slots(self, tmp_path):
        a1 = tmp_path / "a1.jpg"
        a1.write_bytes(b"slot1 v1")
        a2 = tmp_path / "a2.jpg"
        a2.write_bytes(b"slot1 v2")
        b1 = tmp_path / "b1.jpg"
        b1.write_bytes(b"slot2 same")
        session = _MemSession()
        try:
            capture_snapshot(session, TEST_PID, "B0TEST", str(a1), 1)
            capture_snapshot(session, TEST_PID, "B0TEST", str(a2), 1)
            capture_snapshot(session, TEST_PID, "B0TEST", str(b1), 2)
            capture_snapshot(session, TEST_PID, "B0TEST", str(b1), 2)
            changes = detect_changes(session, TEST_PID, "B0TEST")
            assert len(changes) == 1
            assert changes[0]["slot_position"] == 1
        finally:
            session.close()


class TestGetChangeHistory:
    def test_returns_all_snapshots(self, tmp_path):
        img = tmp_path / "img.jpg"
        img.write_bytes(b"data")
        session = _MemSession()
        try:
            capture_snapshot(session, TEST_PID, "B0TEST", str(img), 1)
            capture_snapshot(session, TEST_PID, "B0TEST", str(img), 2)
            history = get_change_history(session, TEST_PID, "B0TEST")
            assert len(history) == 2
        finally:
            session.close()

    def test_empty_history(self):
        session = _MemSession()
        try:
            history = get_change_history(session, TEST_PID, "B0NONE")
            assert history == []
        finally:
            session.close()


class TestChangeRoutes:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr("pipeline.web.app.get_session", _MemSession)
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_get_changes_page(self, client):
        resp = client.get(f"/project/{TEST_PID}/changes")
        assert resp.status_code == 200
        assert b"Change" in resp.data or b"change" in resp.data.lower()

    def test_changes_page_not_found(self, client):
        resp = client.get("/project/99999/changes")
        assert resp.status_code == 404
