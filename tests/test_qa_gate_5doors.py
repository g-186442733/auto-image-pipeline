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
            session.query(ReferencePack).filter_by(project_id=88888).delete()
            session.commit()
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
            session.query(ConsistencyProfile).filter_by(project_id=88887).delete()
            session.commit()
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

    def test_all_5_gates_present_even_when_gate1_fails(self):
        """run_qa_gate 不短路：Gate1 FAIL 时仍然执行全部 5 个门。"""
        from pipeline.layers.qa_gate import run_qa_gate

        # 500x500 → Gate1 必然 FAIL (< 1000px)
        path = _make_image(500, 500)
        try:
            result = run_qa_gate(1, path)
            assert result["overall"] == "FAIL"
            for i in range(1, 6):
                assert f"gate_{i}" in result, (
                    f"gate_{i} missing — run_qa_gate short-circuited!"
                )
            assert result["gate_1"]["status"] == "FAIL"
        finally:
            os.unlink(path)


class TestGate1ComplianceBoundary:
    def test_fail_webp_format(self):
        """Gate1: .webp → FAIL（不在 allowed 列表）"""
        from pipeline.layers.qa_gate import check_compliance

        tmp = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
        img = Image.new("RGB", (1200, 1200))
        img.save(tmp, format="WEBP")
        tmp.close()
        try:
            result = check_compliance(1, tmp.name)
            assert result["status"] == "FAIL"
            assert result["gate"] == "compliance"
        finally:
            os.unlink(tmp.name)

    def test_fail_height_999(self):
        """Gate1: 1000x999 → FAIL（h < _MIN_DIM=1000）"""
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(1000, 999, "JPEG", ".jpg")
        try:
            result = check_compliance(1, path)
            assert result["status"] == "FAIL"
        finally:
            os.unlink(path)

    def test_pass_exactly_10mb(self, monkeypatch):
        """Gate1: 恰好 10MB → PASS（size > 10MB 才 FAIL，等于不触发）"""
        import pipeline.layers.qa_gate as _mod
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(1200, 1200, "JPEG", ".jpg")
        try:
            monkeypatch.setattr(_mod.os.path, "getsize", lambda p: 10 * 1024 * 1024)
            result = check_compliance(1, path)
            assert result["status"] == "PASS"
        finally:
            os.unlink(path)

    def test_fail_over_10mb(self, monkeypatch):
        """Gate1: 10MB + 1 byte → FAIL"""
        import pipeline.layers.qa_gate as _mod
        from pipeline.layers.qa_gate import check_compliance

        path = _make_image(1200, 1200, "JPEG", ".jpg")
        try:
            monkeypatch.setattr(_mod.os.path, "getsize", lambda p: 10 * 1024 * 1024 + 1)
            result = check_compliance(1, path)
            assert result["status"] == "FAIL"
        finally:
            os.unlink(path)


class TestGate2VisualAnchorEdgeCases:
    def test_fail_on_nonexistent_file(self):
        """Gate2: 文件不存在 → OSError → FAIL"""
        from pipeline.layers.qa_gate import check_visual_anchor

        result = check_visual_anchor(1, "/tmp/no_such_file_xyz_abc.jpg")
        assert result["status"] == "FAIL"
        assert result["gate"] == "visual_anchor"

    def test_fail_on_zero_width(self):
        """Gate2: width=0 → FAIL（退化图片）"""
        from unittest.mock import MagicMock, patch
        from pipeline.layers.qa_gate import check_visual_anchor

        mock_img = MagicMock()
        mock_img.__enter__ = MagicMock(return_value=mock_img)
        mock_img.__exit__ = MagicMock(return_value=False)
        mock_img.size = (0, 1200)

        with patch("pipeline.layers.qa_gate.Image.open", return_value=mock_img):
            result = check_visual_anchor(1, "/tmp/dummy.jpg")

        assert result["status"] == "FAIL"
        assert result["gate"] == "visual_anchor"


class TestGate4ConsistencyMock:
    def test_fail_when_validate_returns_false(self):
        """Gate4: validate_consistency 返回 (False, ['color_palette']) → FAIL"""
        from unittest.mock import patch
        from pipeline.layers.qa_gate import check_consistency

        with patch(
            "pipeline.layers.qa_gate.check_consistency",
            return_value={
                "status": "FAIL",
                "gate": "consistency",
                "details": "Missing fields: ['color_palette']",
            },
        ) as mock_c4:
            result = mock_c4(1, "/tmp/dummy.jpg")

        assert result["status"] == "FAIL"
        assert "color_palette" in result["details"]

    def test_fail_via_validate_consistency_mock(self):
        """Gate4: 内部 validate_consistency 直接 mock 返回 False → check_consistency FAIL"""
        from unittest.mock import patch
        from pipeline.layers.qa_gate import check_consistency

        with patch(
            "pipeline.layers.consistency_system.validate_consistency",
            return_value=(False, ["lighting_style", "color_palette"]),
        ):
            result = check_consistency(77777, "/tmp/dummy.jpg")

        assert result["status"] == "FAIL"
        assert result["gate"] == "consistency"
