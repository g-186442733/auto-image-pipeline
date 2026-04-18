import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.layers.version_manager import (
    create_version,
    get_version_history,
    get_version_diff,
    rollback_version,
)

TEST_PID = 20020

_mem_engine = create_engine("sqlite:///:memory:")
_MemSession = sessionmaker(bind=_mem_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(_mem_engine)
    session = _MemSession()
    try:
        session.add(Project(id=TEST_PID, name="Version Test", status="draft"))
        session.commit()
    finally:
        session.close()
    yield
    Base.metadata.drop_all(_mem_engine)


@pytest.fixture()
def output_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = os.path.join(tmpdir, str(TEST_PID))
        os.makedirs(project_dir)
        with open(os.path.join(project_dir, "image.png"), "w") as f:
            f.write("fake")
        yield tmpdir


class TestCreateVersion:
    def test_first_version_is_1(self, output_dir):
        session = _MemSession()
        try:
            dv = create_version(session, TEST_PID, "initial", "first", output_dir)
            assert dv.version_number == 1
            assert dv.trigger == "initial"
            assert dv.project_id == TEST_PID
        finally:
            session.close()

    def test_auto_increments(self, output_dir):
        session = _MemSession()
        try:
            create_version(session, TEST_PID, "initial", "v1", output_dir)
            dv2 = create_version(session, TEST_PID, "revision", "v2", output_dir)
            assert dv2.version_number == 2
        finally:
            session.close()

    def test_snapshots_files(self, output_dir):
        session = _MemSession()
        try:
            dv = create_version(session, TEST_PID, "initial", "snap", output_dir)
            manifest = json.loads(dv.file_manifest)
            assert "image.png" in manifest
            version_dir = os.path.join(output_dir, str(TEST_PID), "versions", "v1")
            assert os.path.isfile(os.path.join(version_dir, "image.png"))
        finally:
            session.close()

    def test_no_project_dir_no_error(self):
        session = _MemSession()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                dv = create_version(session, TEST_PID, "initial", "empty", tmpdir)
                assert dv.version_number == 1
                assert json.loads(dv.file_manifest) == []
        finally:
            session.close()


class TestGetVersionHistory:
    def test_returns_ordered_list(self, output_dir):
        session = _MemSession()
        try:
            create_version(session, TEST_PID, "initial", "v1", output_dir)
            create_version(session, TEST_PID, "revision", "v2", output_dir)
            history = get_version_history(session, TEST_PID)
            assert len(history) == 2
            assert history[0].version_number == 1
            assert history[1].version_number == 2
        finally:
            session.close()


class TestGetVersionDiff:
    def test_diff_added_files(self, output_dir):
        session = _MemSession()
        try:
            create_version(session, TEST_PID, "initial", "v1", output_dir)
            project_dir = os.path.join(output_dir, str(TEST_PID))
            with open(os.path.join(project_dir, "new_file.txt"), "w") as f:
                f.write("new")
            create_version(session, TEST_PID, "revision", "v2", output_dir)
            diff = get_version_diff(session, TEST_PID, 1, 2)
            assert "new_file.txt" in diff["added"]
            assert diff["removed"] == []
        finally:
            session.close()

    def test_diff_removed_files(self, output_dir):
        session = _MemSession()
        try:
            create_version(session, TEST_PID, "initial", "v1", output_dir)
            project_dir = os.path.join(output_dir, str(TEST_PID))
            os.remove(os.path.join(project_dir, "image.png"))
            create_version(session, TEST_PID, "revision", "v2", output_dir)
            diff = get_version_diff(session, TEST_PID, 1, 2)
            assert "image.png" in diff["removed"]
        finally:
            session.close()


class TestRollbackVersion:
    def test_rollback_restores_files(self, output_dir):
        session = _MemSession()
        try:
            create_version(session, TEST_PID, "initial", "v1", output_dir)
            project_dir = os.path.join(output_dir, str(TEST_PID))
            os.remove(os.path.join(project_dir, "image.png"))
            assert not os.path.exists(os.path.join(project_dir, "image.png"))
            ok = rollback_version(session, TEST_PID, 1, output_dir)
            assert ok
            assert os.path.isfile(os.path.join(project_dir, "image.png"))
        finally:
            session.close()

    def test_rollback_nonexistent_returns_false(self, output_dir):
        session = _MemSession()
        try:
            ok = rollback_version(session, TEST_PID, 999, output_dir)
            assert not ok
        finally:
            session.close()


class TestVersionRoutes:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr("pipeline.web.app.get_session", _MemSession)
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_get_versions_page(self, client):
        resp = client.get(f"/project/{TEST_PID}/versions")
        assert resp.status_code == 200
