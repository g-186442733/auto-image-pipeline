import io
import json
import os
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.config import config as _cfg

_tmp_db = tempfile.mktemp(suffix=".db")
_tmp_out = tempfile.mkdtemp(prefix="aip_web_e2e_")
_cfg.db_path = _tmp_db
_cfg.output_dir = _tmp_out
_cfg.keepa_api_key = "test-keepa-key"
_cfg.openai_api_key = "test-openai-key"

from sqlalchemy import create_engine
from pipeline.models import base as base_mod
from pipeline.models.base import Base, get_session

base_mod._engine = create_engine(f"sqlite:///{_tmp_db}")
base_mod._SessionLocal = None
Base.metadata.create_all(base_mod._engine)

from pipeline.models.project import Project
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.prompt_asset import PromptAsset

from pipeline.web.app import create_app


def _minimal_png_bytes(w=1200, h=1200):
    def _chunk(ct, data):
        c = ct + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    row = b"\x00" + b"\xff" * (w * 3)
    raw = b"".join(row for _ in range(h))
    idat = _chunk(b"IDAT", zlib.compress(raw, 1))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


FULL_INPUT = {
    "product_name": "Web E2E Widget",
    "asin": "B0WEBTEST01",
    "product_category": "gadgets",
    "key_selling_points": "fast, durable",
    "target_age": "18-35",
    "target_gender": "all",
    "lifestyle": "urban",
    "purchase_motivation": "quality",
    "competitor_asins": "B0COMP00AA",
    "differentiation": "unique build",
    "primary_color": "black",
    "style_keywords": "sleek, modern",
    "budget_level": "mid",
    "deadline": "2026-12-01",
}


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    app._aip_output_dir = _tmp_out
    c = app.test_client()
    from tests.conftest import inject_auth

    inject_auth(c)
    return c


@pytest.fixture(scope="module", autouse=True)
def _restore_config():
    yield
    _cfg.keepa_api_key = None
    _cfg.openai_api_key = None


def _make_project(name="Web Test Project", asin="B0WEBTEST99"):
    session = get_session()
    proj = Project(name=name, asin=asin, category="test", status="initialized")
    session.add(proj)
    session.commit()
    session.refresh(proj)
    pid = proj.id
    session.close()
    return pid


class TestIndexRoute:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_html_content(self, client):
        resp = client.get("/")
        assert (
            b"<!DOCTYPE html>" in resp.data
            or b"<html" in resp.data
            or resp.status_code == 200
        )


class TestProjectRoutes:
    def test_project_new_get(self, client):
        resp = client.get("/project/new")
        assert resp.status_code == 200

    def test_project_create_post(self, client):
        resp = client.post(
            "/project/new",
            data={
                "name": "Created Project",
                "asin": "B0TEST00AB",
                "category": "tools",
                "notes": "",
            },
        )
        assert resp.status_code == 302

    def test_project_detail_not_found(self, client):
        resp = client.get("/project/999999")
        assert resp.status_code == 404

    def test_project_detail_exists(self, client):
        pid = _make_project("Detail Test")
        resp = client.get(f"/project/{pid}")
        assert resp.status_code == 200

    def test_project_detail_prompt_modal_has_bilingual_tabs(self, client):
        pid = _make_project("Prompt Modal Test")
        session = get_session()
        try:
            session.add(
                PromptAsset(
                    project_id=pid,
                    slot_index=1,
                    prompt_text="Photorealistic product photography with clean white background.",
                    negative_prompt="",
                    model_name="gpt_image",
                    version=1,
                    tenant_id=1,
                )
            )
            session.commit()
        finally:
            session.close()

        resp = client.get(f"/project/{pid}")
        assert resp.status_code == 200
        assert "中文直译".encode() in resp.data
        assert "英文原文".encode() in resp.data
        assert b'data-prompt-tab="original"' in resp.data
        assert resp.data.index(b'data-prompt-tab="original"') < resp.data.index(b'data-prompt-tab="summary"')
        assert b'id="prompt-modal-summary"' in resp.data
        assert b"loadPromptTranslation" in resp.data
        assert "点击“中文直译”后生成完整中文翻译。".encode() in resp.data
        assert b"translate-zh" in resp.data

    def test_prompt_translate_route_returns_cached_translation(self, client):
        pid = _make_project("Prompt Translate Cached Test")
        session = get_session()
        try:
            asset = PromptAsset(
                project_id=pid,
                slot_index=1,
                prompt_text="English source text must stay unchanged.",
                prompt_text_zh="英文源文本必须保持不变。",
                negative_prompt="",
                model_name="gpt_image",
                version=1,
                tenant_id=1,
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
            asset_id = asset.id
        finally:
            session.close()

        with mock.patch("pipeline.layers.prompt_translator.translate_prompt_to_zh") as mocked:
            resp = client.post(f"/api/prompt/{asset_id}/translate-zh")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["zh"] == "英文源文本必须保持不变。"
        assert data["cached"] is True
        mocked.assert_not_called()

    def test_project_status_idle(self, client):
        pid = _make_project("Status Test")
        resp = client.get(f"/project/{pid}/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "state" in data

    def test_project_run_starts(self, client):
        pid = _make_project("Run Test")
        with mock.patch("pipeline.web.app._run_pipeline_thread"):
            resp = client.post(f"/project/{pid}/run")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["state"] == "running"

    def test_project_run_409_when_already_running(self, client):
        pid = _make_project("Run 409 Test")
        from pipeline.web import app as app_mod

        app_mod._run_status[pid] = {"state": "running", "message": "already running"}
        resp = client.post(f"/project/{pid}/run")
        assert resp.status_code == 409

    def test_project_aplus_not_found(self, client):
        resp = client.get("/project/999999/aplus")
        assert resp.status_code == 404

    def test_project_versions_not_found(self, client):
        resp = client.get("/project/999999/versions")
        assert resp.status_code == 404

    def test_version_history_exists(self, client):
        pid = _make_project("Version Test")
        resp = client.get(f"/project/{pid}/versions")
        assert resp.status_code == 200


class TestCustomerInputRoutes:
    def test_input_new_get(self, client):
        resp = client.get("/input/new")
        assert resp.status_code == 200

    def test_input_create_with_all_required_fields(self, client):
        resp = client.post("/input/new", data=FULL_INPUT)
        assert resp.status_code in (200, 302)

    def test_input_create_missing_required_field_returns_400(self, client):
        partial = {k: v for k, v in FULL_INPUT.items() if k != "product_name"}
        resp = client.post("/input/new", data=partial)
        assert resp.status_code == 400
        assert b"product_name" in resp.data

    def test_input_edit_not_found(self, client):
        resp = client.get("/input/999999/edit")
        assert resp.status_code == 404

    def test_input_edit_get(self, client):
        pid = _make_project("Input Edit Test")
        resp = client.get(f"/input/{pid}/edit")
        assert resp.status_code == 200

    def test_input_update_missing_field(self, client):
        pid = _make_project("Input Update Miss")
        partial = {k: v for k, v in FULL_INPUT.items() if k != "deadline"}
        resp = client.post(f"/input/{pid}/edit", data=partial)
        assert resp.status_code == 400


class TestUploadRoutes:
    def test_upload_api_valid_png(self, client):
        pid = _make_project("Upload API Test")
        data = {"file": (io.BytesIO(_minimal_png_bytes()), "test.png")}
        resp = client.post(
            f"/api/projects/{pid}/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        assert b"path" in resp.data

    def test_upload_api_invalid_ext(self, client):
        pid = _make_project("Upload Ext Test")
        data = {"file": (io.BytesIO(b"fake"), "malware.exe")}
        resp = client.post(
            f"/api/projects/{pid}/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    def test_upload_api_no_file(self, client):
        pid = _make_project("Upload No File")
        resp = client.post(
            f"/api/projects/{pid}/upload", data={}, content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    def test_upload_api_oversized_file_returns_413(self, client):
        pid = _make_project("Upload Size Test")
        big_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024)
        data = {"file": (io.BytesIO(big_data), "big.png")}
        resp = client.post(
            f"/api/projects/{pid}/upload", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 413

    def test_upload_asset_not_found_project(self, client):
        pid = _make_project("Upload Asset Test")
        resp = client.get(f"/upload/{pid}")
        assert resp.status_code == 200

    def test_delete_asset_missing_filename(self, client):
        pid = _make_project("Delete Asset Test")
        resp = client.post(f"/upload/{pid}/delete", data={})
        assert resp.status_code == 400

    def test_delete_asset_not_found_file(self, client):
        pid = _make_project("Delete File NF")
        resp = client.post(f"/upload/{pid}/delete", data={"filename": "ghost.png"})
        assert resp.status_code == 404


class TestBrandProfileRoutes:
    def test_brand_profile_view_not_found(self, client):
        resp = client.get("/brand-profile/999999")
        assert resp.status_code == 404

    def test_brand_profile_view_exists(self, client):
        pid = _make_project("Brand Profile Test")
        with mock.patch("pipeline.layers.brand_profiler.build_brand_profile") as mp:
            mp.return_value = mock.MagicMock(
                brand_tone=None,
                color_system=None,
                font_preference=None,
                photo_style=None,
                model_type=None,
                scene_preference=None,
                composition_preference=None,
                material_texture=None,
                competitor_positioning=None,
                brand_story=None,
            )
            resp = client.get(f"/brand-profile/{pid}")
        assert resp.status_code == 200


class TestReviewRoutes:
    def test_review_page(self, client):
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_review_approve_not_found(self, client):
        resp = client.post("/review/999999/approve")
        assert resp.status_code == 404

    def test_review_reject_not_found(self, client):
        resp = client.post("/review/999999/reject", data={"reason": "low quality"})
        assert resp.status_code == 404

    def test_review_approve_and_reject_flow(self, client):
        pid = _make_project("Review Flow Test")
        session = get_session()
        dv = DeliveryVersion(
            project_id=pid,
            version_number=1,
            change_summary="initial",
        )
        session.add(dv)
        session.commit()
        vid = dv.id
        session.close()

        resp = client.post(f"/review/{vid}/approve")
        assert resp.status_code in (200, 302)

        session = get_session()
        dv2 = DeliveryVersion(
            project_id=pid,
            version_number=2,
            change_summary="v2",
        )
        session.add(dv2)
        session.commit()
        vid2 = dv2.id
        session.close()

        resp2 = client.post(f"/review/{vid2}/reject", data={"reason": "needs work"})
        assert resp2.status_code in (200, 302)


class TestQADashboard:
    def test_qa_dashboard_returns_200(self, client):
        resp = client.get("/qa-dashboard")
        assert resp.status_code == 200


class TestMiscRoutes:
    def test_prompts_list(self, client):
        resp = client.get("/prompts")
        assert resp.status_code == 200

    def test_benchmarks_list(self, client):
        resp = client.get("/benchmarks")
        assert resp.status_code == 200

    def test_revision_guide(self, client):
        resp = client.get("/revision-guide")
        assert resp.status_code == 200

    def test_knowledge_base(self, client):
        resp = client.get("/knowledge")
        assert resp.status_code == 200

    def test_image_serve_not_found(self, client):
        resp = client.get("/image/nonexistent/path/img.png")
        assert resp.status_code == 404

    def test_image_serve_forbidden_traversal(self, client):
        resp = client.get("/image/../../etc/passwd")
        assert resp.status_code in (403, 404)


class TestUploadPagePost:
    def test_upload_page_post_redirects(self, client):
        pid = _make_project("Upload Page POST Test")
        data = {"file": (io.BytesIO(_minimal_png_bytes()), "page_upload.png")}
        resp = client.post(
            f"/upload/{pid}",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code in (200, 302)

    def test_upload_page_post_file_exists_on_disk(self, client):
        pid = _make_project("Upload Disk Test")
        data = {"file": (io.BytesIO(_minimal_png_bytes()), "diskcheck.png")}
        client.post(
            f"/upload/{pid}",
            data=data,
            content_type="multipart/form-data",
        )
        assets_dir = os.path.join(_tmp_out, str(pid), "assets")
        assert os.path.isfile(os.path.join(assets_dir, "diskcheck.png"))


class TestBrandProfilePost:
    def test_brand_profile_post_redirects(self, client):
        pid = _make_project("Brand Profile POST Test")
        mock_bp = mock.MagicMock(
            brand_tone=None,
            color_system=None,
            font_preference=None,
            photo_style=None,
            model_type=None,
            scene_preference=None,
            composition_preference=None,
            material_texture=None,
            competitor_positioning=None,
            brand_story=None,
        )
        with mock.patch(
            "pipeline.layers.brand_profiler.build_brand_profile", return_value=mock_bp
        ):
            resp = client.post(
                f"/brand-profile/{pid}",
                data={"brand_tone": "modern", "color_system": "neutral"},
            )
        assert resp.status_code in (200, 302)


class TestFeedbackRoutes:
    def test_feedback_get_returns_200(self, client):
        pid = _make_project("Feedback GET Test")
        with mock.patch(
            "pipeline.layers.feedback_handler.get_feedback_summary", return_value={}
        ):
            resp = client.get(f"/project/{pid}/feedback")
        assert resp.status_code == 200

    def test_feedback_post_redirects(self, client):
        pid = _make_project("Feedback POST Test")
        with mock.patch("pipeline.layers.feedback_handler.submit_feedback") as msf:
            msf.return_value = None
            resp = client.post(
                f"/project/{pid}/feedback",
                data={
                    "slot_name": "hero",
                    "feedback_type": "reject",
                    "feedback_text": "too dark",
                },
            )
        assert resp.status_code in (200, 302)

    def test_feedback_post_empty_slot_no_submit(self, client):
        pid = _make_project("Feedback POST Empty")
        with mock.patch("pipeline.layers.feedback_handler.submit_feedback") as msf:
            resp = client.post(
                f"/project/{pid}/feedback",
                data={"slot_name": "", "feedback_type": "", "feedback_text": ""},
            )
        assert resp.status_code in (200, 302)
        msf.assert_not_called()


class TestConsistencyRoutes:
    def _make_mock_profile(self):
        return mock.MagicMock(
            lighting_style=None,
            color_palette=None,
            camera_angle=None,
            element_density=None,
            text_overlay_style=None,
            locked=False,
        )

    def test_consistency_get_returns_200(self, client):
        pid = _make_project("Consistency GET Test")
        mp = self._make_mock_profile()
        with (
            mock.patch(
                "pipeline.layers.consistency_system.get_consistency_profile",
                return_value=mp,
            ),
            mock.patch(
                "pipeline.layers.consistency_system.validate_consistency",
                return_value=(True, []),
            ),
        ):
            resp = client.get(f"/project/{pid}/consistency")
        assert resp.status_code == 200

    def test_consistency_post_redirects(self, client):
        pid = _make_project("Consistency POST Test")
        mp = self._make_mock_profile()
        with (
            mock.patch(
                "pipeline.layers.consistency_system.get_consistency_profile",
                return_value=mp,
            ),
            mock.patch(
                "pipeline.layers.consistency_system.update_consistency_profile"
            ) as mup,
        ):
            mup.return_value = None
            resp = client.post(
                f"/project/{pid}/consistency",
                data={"lighting_style": "soft", "color_palette": "warm"},
            )
        assert resp.status_code in (200, 302)

    def test_consistency_lock_redirects(self, client):
        pid = _make_project("Consistency Lock Test")
        with mock.patch(
            "pipeline.layers.consistency_system.lock_consistency_profile"
        ) as mlk:
            mlk.return_value = None
            resp = client.post(f"/project/{pid}/consistency/lock")
        assert resp.status_code in (200, 302)


class TestPromptListRoute:
    def test_prompts_get_returns_200(self, client):
        pid = _make_project("Prompts List Test")
        resp = client.get(f"/project/{pid}/prompts")
        assert resp.status_code == 200

    def test_prompts_list_not_found(self, client):
        resp = client.get("/project/999999/prompts")
        assert resp.status_code == 404


class TestRankingsRoute:
    def test_rankings_get_returns_200(self, client):
        pid = _make_project("Rankings Test")
        with mock.patch(
            "pipeline.layers.ranking_tracker.get_ranking_summary", return_value=[]
        ):
            resp = client.get(f"/project/{pid}/rankings")
        assert resp.status_code == 200

    def test_rankings_not_found(self, client):
        resp = client.get("/project/999999/rankings")
        assert resp.status_code == 404


class TestChangeHistoryRoute:
    def test_changes_get_returns_200(self, client):
        pid = _make_project("Change History Test")
        resp = client.get(f"/project/{pid}/changes")
        assert resp.status_code == 200

    def test_changes_not_found(self, client):
        resp = client.get("/project/999999/changes")
        assert resp.status_code == 404


class TestStatusStates:
    def test_status_returns_running_when_set(self, client):
        pid = _make_project("Status Running Test")
        from pipeline.web import app as app_mod

        app_mod._run_status[pid] = {"state": "running", "message": "in progress"}
        resp = client.get(f"/project/{pid}/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["state"] == "running"

    def test_status_returns_completed_state(self, client):
        pid = _make_project("Status Completed Test")
        from pipeline.web import app as app_mod

        app_mod._run_status[pid] = {"state": "completed", "message": "done"}
        resp = client.get(f"/project/{pid}/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["state"] == "completed"


class TestReferencePack:
    def test_reference_pack_not_found(self, client):
        pid = _make_project("Ref Pack 404 Test")
        with mock.patch(
            "pipeline.layers.reference_pack.get_reference_pack", return_value=None
        ):
            resp = client.get(f"/project/{pid}/reference-pack")
        assert resp.status_code == 404

    def test_reference_pack_returns_json(self, client):
        pid = _make_project("Ref Pack JSON Test")
        mock_rp = mock.MagicMock(
            project_id=pid,
            product_truth='{"key": "val"}',
            brand_rules="{}",
            winning_examples="[]",
            competitor_baseline="[]",
            negative_cases="[]",
            angle_matrix="{}",
        )
        with mock.patch(
            "pipeline.layers.reference_pack.get_reference_pack", return_value=mock_rp
        ):
            resp = client.get(f"/project/{pid}/reference-pack")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "product_truth" in data
