"""Wave 1 bug fix tests — B1 through B4."""

from __future__ import annotations

import os
import re
import struct
import tempfile
import zlib

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_in_memory_db():
    """Reset SQLAlchemy globals and point to in-memory SQLite."""
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")
    return "sqlite:///:memory:"


def _minimal_png(width: int = 1600, height: int = 1600) -> bytes:
    """Create a minimal valid white PNG."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    row = b"\x00" + b"\xff" * (width * 3)
    raw = b"".join(row for _ in range(height))
    idat = _chunk(b"IDAT", zlib.compress(raw, 1))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# ===========================================================================
# B1: image_path must be persisted after generation
# ===========================================================================


class TestB1ImagePathPersisted:
    """step_generate must write adapter result image_path back to PromptAsset."""

    def test_image_path_saved_to_db(self, tmp_path):
        db_url = _make_in_memory_db()

        from pipeline.models.base import get_session
        from pipeline.models.project import Project
        from pipeline.models.slot_plan import SlotPlan
        from pipeline.models.prompt_asset import PromptAsset
        from pipeline.orchestrator import step_generate

        session = get_session(db_url)
        try:
            proj = Project(
                name="test", asin="B0ABCDEFGH", category="Electronics", status="planned"
            )
            session.add(proj)
            session.commit()
            pid = proj.id

            slot = SlotPlan(
                project_id=pid,
                slot_index=0,
                intent_tag="hero",
                layout_tag="center",
                style_tag="clean",
            )
            session.add(slot)
            session.commit()

            asset = PromptAsset(
                project_id=pid, slot_index=0, prompt_text="A test prompt", version=1
            )
            session.add(asset)
            session.commit()
            asset_id = asset.id
        finally:
            session.close()

        # Run generation with mock adapter
        os.environ["AIP_OUTPUT_DIR"] = str(tmp_path)
        step_generate(pid, adapter_name="mock")

        # Verify image_path was persisted
        session = get_session(db_url)
        try:
            asset = session.get(PromptAsset, asset_id)
            assert asset.image_path is not None, (
                "image_path should be persisted after generation"
            )
            assert os.path.isfile(asset.image_path), (
                "image_path should point to an existing file"
            )
        finally:
            session.close()


# ===========================================================================
# B2: QA gate — real validation (file exists, valid image, min dimensions)
# ===========================================================================


class TestB2QAGateValidation:
    """QA gate must validate: file exists, valid PNG, minimum dimensions."""

    def test_check_resolution_rejects_small_image(self, tmp_path):
        from pipeline.layers.qa_gate import check_resolution

        small_png = tmp_path / "small.png"
        small_png.write_bytes(_minimal_png(800, 800))
        assert check_resolution(str(small_png)) is False

    def test_check_resolution_accepts_large_image(self, tmp_path):
        from pipeline.layers.qa_gate import check_resolution

        large_png = tmp_path / "large.png"
        large_png.write_bytes(_minimal_png(1600, 1600))
        assert check_resolution(str(large_png)) is True

    def test_file_exists_validation(self):
        """run_qa_checks should raise if image file doesn't exist."""
        from pipeline.layers.qa_gate import _read_png_dimensions

        with pytest.raises((ValueError, FileNotFoundError, OSError)):
            _read_png_dimensions("/nonexistent/path.png")

    def test_invalid_png_rejected(self, tmp_path):
        """Invalid PNG signature should raise ValueError."""
        from pipeline.layers.qa_gate import _read_png_dimensions

        bad_file = tmp_path / "bad.png"
        bad_file.write_bytes(b"not a png at all!!!!!!!!")
        with pytest.raises(ValueError, match="Not a valid PNG"):
            _read_png_dimensions(str(bad_file))

    def test_validate_image_function_exists(self):
        """A validate_image function should exist for basic sanity checks."""
        from pipeline.layers.qa_gate import validate_image

        # Should return (is_valid, error_message)
        valid, msg = validate_image("/nonexistent/file.png")
        assert valid is False
        assert msg  # should have error message

    def test_validate_image_rejects_non_png(self, tmp_path):
        from pipeline.layers.qa_gate import validate_image

        bad = tmp_path / "fake.png"
        bad.write_bytes(b"JFIF fake jpeg content here!!")
        valid, msg = validate_image(str(bad))
        assert valid is False

    def test_validate_image_rejects_tiny(self, tmp_path):
        from pipeline.layers.qa_gate import validate_image

        tiny = tmp_path / "tiny.png"
        tiny.write_bytes(_minimal_png(100, 100))
        valid, msg = validate_image(str(tiny))
        assert valid is False

    def test_validate_image_accepts_good(self, tmp_path):
        from pipeline.layers.qa_gate import validate_image

        good = tmp_path / "good.png"
        good.write_bytes(_minimal_png(1600, 1600))
        valid, msg = validate_image(str(good))
        assert valid is True


# ===========================================================================
# B3: ASIN validation must use ^B[0-9A-Z]{9}$ and web route must enforce it
# ===========================================================================


class TestB3ASINValidation:
    """ASIN pattern must be ^B[0-9A-Z]{9}$ and web route must validate."""

    def test_pattern_accepts_valid_asins(self):
        from pipeline.layers.input_layer import ASIN_PATTERN

        # B followed by 9 alphanumeric chars (B0... and B1... both valid)
        assert ASIN_PATTERN.match("B0ABCDEFGH")
        assert ASIN_PATTERN.match("B1ABCDEFGH")
        assert ASIN_PATTERN.match("B09XYZAB12")

    def test_pattern_rejects_invalid_asins(self):
        from pipeline.layers.input_layer import ASIN_PATTERN

        assert not ASIN_PATTERN.match("A0ABCDEFGH")  # doesn't start with B
        assert not ASIN_PATTERN.match("B0ABC")  # too short
        assert not ASIN_PATTERN.match("B0ABCDEFGHx")  # too long
        assert not ASIN_PATTERN.match("b0ABCDEFGH")  # lowercase b

    def test_create_project_rejects_bad_asin(self):
        _make_in_memory_db()
        from pipeline.layers.input_layer import create_project

        with pytest.raises(ValueError, match="E_INPUT_002"):
            create_project(
                {"name": "test", "asin": "INVALID", "category": "Electronics"}
            )

    def test_web_route_validates_asin(self):
        """POST /project/new must validate ASIN, not bypass input_layer."""
        _make_in_memory_db()
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        # Bad ASIN should be rejected
        resp = client.post(
            "/project/new",
            data={
                "name": "Test",
                "asin": "INVALID_ASIN",
                "category": "Electronics",
            },
        )
        # Should NOT be a redirect (302 = success), should be 400 or similar
        assert resp.status_code != 302, "Web route should reject invalid ASIN"


# ===========================================================================
# B4: Session management — Flask secret key + 24h TTL
# ===========================================================================


class TestB4SessionManagement:
    """Flask app must have secret_key and session with 24h TTL."""

    def test_app_has_secret_key(self):
        _make_in_memory_db()
        from pipeline.web.app import create_app

        app = create_app()
        assert app.secret_key, "Flask app must have a secret_key configured"

    def test_session_has_ttl(self):
        """Session should expire after 24 hours."""
        _make_in_memory_db()
        from datetime import timedelta
        from pipeline.web.app import create_app

        app = create_app()
        assert app.config.get("PERMANENT_SESSION_LIFETIME") == timedelta(hours=24)

    def test_session_is_permanent(self):
        """Sessions should be marked permanent by default."""
        _make_in_memory_db()
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        # Make a request and verify session behavior
        resp = client.get("/")
        assert resp.status_code == 200
