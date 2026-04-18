"""Tests for QA Gate 5 hard doors."""

from __future__ import annotations

import io
import os
import tempfile

import pytest
from PIL import Image

from pipeline.models.base import get_session, create_all
from pipeline.models.consistency_profile import ConsistencyProfile
from pipeline.models.reference_pack import ReferencePack


@pytest.fixture(autouse=True)
def _setup_db():
    create_all()


def _make_image(w: int, h: int, fmt: str = "JPEG", suffix: str = ".jpg") -> str:
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    img.save(tmp, format=fmt)
    tmp.close()
    return tmp.name


class TestGate1Compliance:
    def test_pass_valid_jpeg(self):
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(1200, 1200, "JPEG", ".jpg")
        try:
            result = check_compliance(1, path)
            assert result["status"] == "PASS"
            assert result["gate"] == "compliance"
        finally:
            os.unlink(path)

    def test_fail_bad_format(self):
        from pipeline.layers.qa_gate import check_compliance

        tmp = tempfile.NamedTemporaryFile(suffix=".bmp", delete=False)
        img = Image.new("RGB", (1200, 1200))
        img.save(tmp, format="BMP")
        tmp.close()
        try:
            result = check_compliance(1, tmp.name)
            assert result["status"] == "FAIL"
        finally:
            os.unlink(tmp.name)

    def test_fail_small_dimensions(self):
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(500, 500, "JPEG", ".jpg")
        try:
            result = check_compliance(1, path)
            assert result["status"] == "FAIL"
            assert "1000" in result["details"]
        finally:
            os.unlink(path)

    def test_pass_png(self):
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(1500, 1500, "PNG", ".png")
        try:
            result = check_compliance(1, path)
            assert result["status"] == "PASS"
        finally:
            os.unlink(path)


class TestGate2VisualAnchor:
    def test_returns_dict_with_status(self):
        from pipeline.layers.qa_gate import check_visual_anchor

        path = _make_image(1200, 1200)
        try:
            result = check_visual_anchor(1, path)
            assert "status" in result
            assert result["gate"] == "visual_anchor"
            assert result["status"] in ("PASS", "FAIL")
        finally:
            os.unlink(path)


class TestGate3ReferenceChain:
    def test_fail_no_reference_pack(self):
        from pipeline.layers.qa_gate import check_reference_chain

        result = check_reference_chain(99999, "/tmp/dummy.jpg")
        assert result["status"] == "FAIL"
        assert result["gate"] == "reference_chain"

    def test_pass_reference_pack_exists(self):
        from pipeline.layers.qa_gate import check_reference_chain

        session = get_session()
        try:
            rp = ReferencePack(project_id=88888, product_truth="test")
            session.add(rp)
            session.commit()
        finally:
            session.close()

        result = check_reference_chain(88888, "/tmp/dummy.jpg")
        assert result["status"] == "PASS"


class TestGate4Consistency:
    def test_fail_no_profile(self):
        from pipeline.layers.qa_gate import check_consistency

        result = check_consistency(99998, "/tmp/dummy.jpg")
        assert result["status"] == "FAIL"
        assert result["gate"] == "consistency"

    def test_pass_profile_exists(self):
        from pipeline.layers.qa_gate import check_consistency

        session = get_session()
        try:
            cp = ConsistencyProfile(
                project_id=88887,
                lighting_style="soft",
                color_palette="#fff",
                camera_angle="front",
                element_density="medium",
                text_overlay_style="none",
            )
            session.add(cp)
            session.commit()
        finally:
            session.close()

        result = check_consistency(88887, "/tmp/dummy.jpg")
        assert result["status"] == "PASS"


class TestRunQaGate:
    def test_returns_5_gates(self):
        from pipeline.layers.qa_gate import run_qa_gate

        path = _make_image(1200, 1200)
        try:
            result = run_qa_gate(1, path)
            assert "overall" in result
            for i in range(1, 6):
                assert f"gate_{i}" in result
        finally:
            os.unlink(path)

    def test_any_fail_means_overall_fail(self):
        from pipeline.layers.qa_gate import run_qa_gate

        path = _make_image(500, 500)
        try:
            result = run_qa_gate(1, path)
            assert result["overall"] == "FAIL"
        finally:
            os.unlink(path)
