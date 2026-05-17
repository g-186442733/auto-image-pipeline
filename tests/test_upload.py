"""素材上传 UI 测试 — TDD"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from pipeline.web.app import create_app


@pytest.fixture()
def app_client(tmp_path):
    """创建测试客户端，使用临时目录作为 output_dir"""
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)

    with patch("pipeline.web.app.create_all"):
        app = create_app()
        app.config["TESTING"] = True
        app.config["AIP_OUTPUT_DIR"] = output_dir

    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.name = "Test Project"

    def _mock_get_session():
        sess = MagicMock()
        sess.get.return_value = mock_project
        return sess

    with app.test_client() as client:
        from tests.conftest import inject_auth
        inject_auth(client)
        with patch("pipeline.web.app.get_session", side_effect=_mock_get_session):
            app._aip_output_dir = output_dir
            yield client, output_dir


class TestUploadPage:
    """GET /upload/<project_id> 页面"""

    def test_get_upload_page_200(self, app_client):
        client, _ = app_client
        resp = client.get("/upload/1")
        assert resp.status_code == 200
        assert (
            b"\xe4\xb8\x8a\xe4\xbc\xa0" in resp.data or b"upload" in resp.data.lower()
        )


class TestUploadFile:
    """POST /upload/<project_id> 文件上传"""

    def test_upload_jpg_success(self, app_client):
        client, output_dir = app_client
        data = {
            "file": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100), "test.jpg"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)
        assets_dir = os.path.join(output_dir, "1", "assets")
        if os.path.exists(assets_dir):
            assert "test.jpg" in os.listdir(assets_dir)

    def test_upload_png_success(self, app_client):
        client, output_dir = app_client
        data = {
            "file": (io.BytesIO(b"\x89PNG" + b"\x00" * 100), "photo.png"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)

    def test_upload_webp_success(self, app_client):
        client, output_dir = app_client
        data = {
            "file": (io.BytesIO(b"RIFF" + b"\x00" * 100), "image.webp"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)

    def test_upload_svg_success(self, app_client):
        client, output_dir = app_client
        svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        data = {
            "file": (io.BytesIO(svg_content), "icon.svg"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)

    def test_reject_exe_file(self, app_client):
        """不允许的文件类型应返回 400"""
        client, _ = app_client
        data = {
            "file": (io.BytesIO(b"MZ" + b"\x00" * 100), "malware.exe"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_reject_oversized_file(self, app_client):
        """超过 10MB 的文件应返回 413"""
        client, _ = app_client
        large_data = b"\x00" * (10 * 1024 * 1024 + 1)
        data = {
            "file": (io.BytesIO(large_data), "huge.jpg"),
        }
        resp = client.post(
            "/upload/1",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 413

    def test_no_file_provided(self, app_client):
        """没有文件应返回 400"""
        client, _ = app_client
        resp = client.post("/upload/1", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400


class TestDeleteFile:
    """POST /upload/<project_id>/delete 删除文件"""

    def test_delete_existing_file(self, app_client):
        client, output_dir = app_client
        assets_dir = os.path.join(output_dir, "1", "assets")
        os.makedirs(assets_dir, exist_ok=True)
        filepath = os.path.join(assets_dir, "to_delete.jpg")
        with open(filepath, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0")

        resp = client.post(
            "/upload/1/delete",
            data={"filename": "to_delete.jpg"},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)
        assert not os.path.exists(filepath)

    def test_delete_nonexistent_file(self, app_client):
        """删除不存在的文件应返回 404"""
        client, _ = app_client
        resp = client.post(
            "/upload/1/delete",
            data={"filename": "ghost.jpg"},
        )
        assert resp.status_code == 404
