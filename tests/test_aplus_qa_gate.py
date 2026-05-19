from __future__ import annotations

import json
import os
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_png(path: str, width: int = 970, height: int = 600, mode: str = "RGB") -> str:
    """生成最小合法 PNG，写入 path，返回 path。"""
    try:
        from PIL import Image as PILImage

        img = PILImage.new(mode, (width, height), color=(200, 200, 200))
        img.save(path, format="PNG")
    except ImportError:

        def _chunk(tag: bytes, data: bytes) -> bytes:
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)

        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw_row = b"\x00" + b"\xff\x00\x00" * width
        raw = raw_row * height
        idat_data = zlib.compress(raw)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr_data)
            + _chunk(b"IDAT", idat_data)
            + _chunk(b"IEND", b"")
        )
        with open(path, "wb") as f:
            f.write(png)
    return path


def _make_jpeg(path: str, width: int = 970, height: int = 600) -> str:
    """生成最小合法 JPEG，写入 path，返回 path。"""
    try:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (width, height), color=(200, 200, 200))
        img.save(path, format="JPEG")
    except ImportError:
        jpeg = bytes(
            [
                0xFF,
                0xD8,  # SOI
                0xFF,
                0xE0,
                0x00,
                0x10,  # APP0 marker
                0x4A,
                0x46,
                0x49,
                0x46,
                0x00,  # JFIF\0
                0x01,
                0x01,
                0x00,
                0x00,
                0x01,
                0x00,
                0x01,
                0x00,
                0x00,
                0xFF,
                0xD9,  # EOI
            ]
        )
        with open(path, "wb") as f:
            f.write(jpeg)
    return path


# ── Fake LLM 响应构造 ─────────────────────────────────────────────────────────

_GOOD_LLM_RESPONSE = {
    "L3_sharpness": 9,
    "L3_exposure": 9,
    "L4_intent": 23,
    "L5_consistency": 9,
    "L6_commercial": 9,
    "reasoning": "图片清晰，焦点准确，色调均衡，与模块意图高度吻合。",
}

_POOR_LLM_RESPONSE = {
    "L3_sharpness": 3,
    "L3_exposure": 3,
    "L4_intent": 8,
    "L5_consistency": 3,
    "L6_commercial": 3,
    "reasoning": "图片模糊，曝光过度，与模块意图关联弱。",
}


def _mock_llm_response(payload: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    return mock_resp


from pipeline.layers.aplus_qa_gate import (
    APlusQAGate,
    _MAX_FILE_SIZE,
    _PASS_SCORE,
    _RETRY_PASS_SCORE,
    _SIZE_TOLERANCE,
)
from pipeline.layers.safe_frame import (
    SAFE_FRAME_MIN_MARGIN_RATIO,
    measure_white_bg_foreground_margins,
)


class TestL1TechnicalBase:
    def test_l1_none_path_returns_zero(self):
        """image_path 为 None → 0 分"""
        gate = APlusQAGate()
        score, issues = gate._score_technical_base(None)
        assert score == 0.0
        assert any("image_path" in i for i in issues)

    def test_l1_missing_file_returns_zero(self):
        """文件不存在 → 0 分"""
        gate = APlusQAGate()
        score, issues = gate._score_technical_base("/nonexistent/path/img.png")
        assert score == 0.0
        assert issues

    def test_l1_valid_png_full_score(self, tmp_path):
        """合法 RGB PNG ≤2MB → 20 分"""
        path = _make_png(str(tmp_path / "test.png"), 970, 600, "RGB")
        gate = APlusQAGate()
        score, issues = gate._score_technical_base(path)
        assert score == 20.0, f"期望 20 分，实际 {score}，issues={issues}"

    def test_l1_valid_jpeg_full_score(self, tmp_path):
        """合法 JPEG ≤2MB → 20 分"""
        path = _make_jpeg(str(tmp_path / "test.jpg"))
        gate = APlusQAGate()
        score, issues = gate._score_technical_base(path)
        assert score == 20.0, f"期望 20 分，实际 {score}，issues={issues}"

    def test_l1_invalid_extension(self, tmp_path):
        """.bmp 文件 → L1.2 扣分"""
        p = tmp_path / "img.bmp"
        p.write_bytes(b"BM" + b"\x00" * 50)
        gate = APlusQAGate()
        score, issues = gate._score_technical_base(str(p))
        assert score < 20.0
        assert any("格式" in i or "format" in i.lower() for i in issues)

    def test_l1_oversized_file(self, tmp_path):
        """文件超过 2MB → L1.2 扣分"""
        p = tmp_path / "big.jpg"
        p.write_bytes(b"\xff\xd8" + b"\x00" * (_MAX_FILE_SIZE + 100))
        gate = APlusQAGate()
        score, issues = gate._score_technical_base(str(p))
        assert score < 20.0
        assert any("2MB" in i or "大小" in i or "size" in i.lower() for i in issues)


class TestL2Resolution:
    def test_exact_match_full_score(self, tmp_path):
        """尺寸精确匹配 HERO(1536x1024) → 15 分"""
        path = _make_png(str(tmp_path / "exact.png"), 1536, 1024)
        gate = APlusQAGate()
        score, issues = gate._score_resolution(path, "HERO")
        assert score == 15.0, f"期望 15 分，实际 {score}"

    def test_tolerance_match_partial_score(self, tmp_path):
        """尺寸在 ±5% 容差内 → 8 分（BENEFIT 期望 1024x1024，实际 1055x1024 约 3%）"""
        path = _make_png(str(tmp_path / "tol.png"), 1055, 1024)
        gate = APlusQAGate()
        score, issues = gate._score_resolution(path, "BENEFIT")
        assert score == 8.0, f"期望 8 分，实际 {score}"

    def test_out_of_tolerance_zero_score(self, tmp_path):
        """尺寸超出 ±5% 容差 → 0 分"""
        path = _make_png(str(tmp_path / "wrong.png"), 800, 400)
        gate = APlusQAGate()
        score, issues = gate._score_resolution(path, "HERO")
        assert score == 0.0
        assert issues

    def test_missing_file_zero_score(self):
        """文件不存在 → 0 分"""
        gate = APlusQAGate()
        score, issues = gate._score_resolution("/no/such/file.png", "HERO")
        assert score == 0.0

    def test_unknown_module_type_no_penalty(self, tmp_path):
        """未知 module_type → 不扣分（返回 15 分，跳过校验）"""
        path = _make_png(str(tmp_path / "any.png"), 970, 600)
        gate = APlusQAGate()
        score, issues = gate._score_resolution(path, "UNKNOWN_TYPE")
        # 未知类型不扣分
        assert score == 15.0


class TestHeroSafeFrame:
    def _make_white_bg_hero(
        self,
        tmp_path,
        filename: str,
        box: tuple[int, int, int, int],
    ) -> str:
        from PIL import Image as PILImage
        from PIL import ImageDraw

        path = tmp_path / filename
        image = PILImage.new("RGB", (1536, 1024), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle(box, fill=(80, 80, 80))
        image.save(path, format="PNG")
        return str(path)

    def test_hero_safe_frame_detects_bottom_edge_risk(self, tmp_path):
        """HERO 主体贴近底边时，应输出低于安全阈值的最小边距。"""
        path = self._make_white_bg_hero(
            tmp_path,
            "edge_risk.png",
            (420, 80, 1120, 1010),
        )

        metrics = measure_white_bg_foreground_margins(path)

        assert metrics["applicable"] is True
        assert metrics["min_margin_ratio"] < SAFE_FRAME_MIN_MARGIN_RATIO
        assert metrics["margins_px"]["bottom"] < 30

    def test_hero_safe_frame_passes_centered_product(self, tmp_path):
        """HERO 主体四边留白充足时，应通过安全边距检测。"""
        path = self._make_white_bg_hero(
            tmp_path,
            "safe.png",
            (420, 120, 1120, 880),
        )

        metrics = measure_white_bg_foreground_margins(path)

        assert metrics["applicable"] is True
        assert metrics["min_margin_ratio"] >= SAFE_FRAME_MIN_MARGIN_RATIO

    @patch("pipeline.layers.aplus_qa_gate._call_llm")
    def test_hero_safe_frame_failure_caps_score_below_pass(self, mock_call_llm, tmp_path):
        """即使 LLM 给高分，HERO 主体贴边也必须被压到不通过区间。"""
        path = self._make_white_bg_hero(
            tmp_path,
            "edge_risk_eval.png",
            (420, 80, 1120, 1010),
        )
        mock_call_llm.return_value = json.dumps(_GOOD_LLM_RESPONSE)

        fake_content = MagicMock()
        fake_content.id = 901
        fake_content.project_id = 1
        fake_content.module_type = "HERO"
        fake_content.image_path = path
        fake_content.reference_image_paths = ""
        fake_session = MagicMock()
        fake_session.get.return_value = None

        score, issues, breakdown = APlusQAGate()._evaluate_once(fake_content, fake_session)

        assert score < _PASS_SCORE
        assert breakdown["hero_safe_frame_failed"] is True
        assert any("safe-frame failure" in issue for issue in issues)


class TestLLMScoring:
    def _make_image(self, tmp_path, width: int = 1500, height: int = 500) -> str:
        return _make_png(str(tmp_path / "img.png"), width, height)

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_good_llm_score(self, mock_post, tmp_path, monkeypatch):
        """LLM 返回高分 → L3~L6 接近满分"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        mock_post.return_value = _mock_llm_response(_GOOD_LLM_RESPONSE)

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "HERO")

        assert total >= 50, f"LLM 高分时期望 ≥50 分，实际 {total}"

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_poor_llm_score(self, mock_post, tmp_path, monkeypatch):
        """LLM 返回低分 → 各层分数均低"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        mock_post.return_value = _mock_llm_response(_POOR_LLM_RESPONSE)

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "BENEFIT")

        assert total < 40, f"LLM 低分时期望 <40 分，实际 {total}"

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_llm_failure_is_hard_failure(self, mock_post, tmp_path, monkeypatch):
        """LLM 调用失败 → 硬失败，禁止 fallback 分数放行。"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        mock_post.side_effect = Exception("网络超时")

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "DETAIL")

        assert total == 0.0
        assert breakdown["llm_unavailable"] is True
        assert any("retry required" in i for i in issues)

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_llm_returns_invalid_json_is_hard_failure(self, mock_post, tmp_path, monkeypatch):
        """LLM 返回非 JSON → 硬失败，禁止用默认分数伪装有效评分。"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json.return_value = {
            "choices": [{"message": {"content": "这不是 JSON"}}]
        }
        mock_post.return_value = bad_resp

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "LIFESTYLE")

        assert total == 0.0
        assert breakdown["llm_unavailable"] is True
        assert breakdown["qa_retryable_failure"] is True
        assert any("Invalid LLM QA JSON" in i for i in issues)

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_invalid_json_retries_qa_call_before_hard_failure(self, mock_post, tmp_path, monkeypatch):
        """A+ QA JSON 截断/非法时先重试 QA 调用，不能立刻触发生图重试。"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json.return_value = {
            "choices": [{"message": {"content": '{"L3_sharpness": 10, "L3_exposure": 10, "L'}}]
        }
        good_resp = _mock_llm_response(_GOOD_LLM_RESPONSE)
        mock_post.side_effect = [bad_resp, good_resp]

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "HERO")

        assert total >= 50
        assert issues == []
        assert "llm_unavailable" not in breakdown
        assert mock_post.call_count == 2

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_unsafe_image_path_is_not_uploaded(self, mock_post, tmp_path, monkeypatch):
        """不在允许根目录内的图片路径不能被读取或外发给外部 QA API。"""
        safe_root = tmp_path / "safe"
        unsafe_root = tmp_path / "unsafe"
        safe_root.mkdir()
        unsafe_root.mkdir()
        path = self._make_image(unsafe_root)
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(safe_root))

        gate = APlusQAGate()
        total, issues, breakdown = gate._score_llm(path, "HERO")

        assert total == 0.0
        assert breakdown["llm_unavailable"] is True
        mock_post.assert_not_called()

    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_invalid_json_log_omits_raw_content(self, mock_post, tmp_path, monkeypatch, caplog):
        """非法 JSON 日志只记录长度，不能落盘模型原文片段。"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        secret = "CUSTOMER_SECRET_PROMPT_TEXT"
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json.return_value = {"choices": [{"message": {"content": secret}}]}
        mock_post.return_value = bad_resp

        path = self._make_image(tmp_path)
        gate = APlusQAGate()
        gate._score_llm(path, "HERO")

        assert secret not in caplog.text
        assert "raw_length" in caplog.text


class TestEvaluateOnce:
    def _make_content(self, tmp_path, module_type: str = "HERO") -> Any:
        """构造带 image_path/module_type 的 mock APlusContent。"""
        path = _make_png(str(tmp_path / "img.png"), 1536, 1024)
        c = MagicMock()
        c.id = 1
        c.module_type = module_type
        c.image_path = path
        c.ref_image_path = None
        return c

    @patch("pipeline.layers.aplus_qa_gate.config")
    @patch("pipeline.layers.aplus_qa_gate.httpx.post")
    def test_high_quality_image_passes(self, mock_post, mock_config, tmp_path, monkeypatch):
        """技术合格 + LLM 高分 → 总分 ≥70，passed=True"""
        monkeypatch.setenv("AIP_ALLOWED_IMAGE_ROOTS", str(tmp_path))
        mock_config.api_key = "test-key"
        mock_config.api_base_url = "https://api.test.com"
        mock_config.vision_model = "gpt-4o"
        mock_post.return_value = _mock_llm_response(_GOOD_LLM_RESPONSE)

        c = self._make_content(tmp_path)
        gate = APlusQAGate()
        score, issues, breakdown = gate._evaluate_once(c, MagicMock())

        assert score >= 70, f"期望 score≥70，实际 {score}"
        assert "breakdown" not in issues
        assert "L1" in breakdown

    @patch("pipeline.layers.aplus_qa_gate.httpx.Client")
    def test_low_quality_image_fails(self, mock_client_cls, tmp_path):
        """LLM 评低分 + 尺寸偏差 → 总分偏低"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_llm_response(_POOR_LLM_RESPONSE)

        path = _make_png(str(tmp_path / "img.png"), 800, 400)
        c = MagicMock()
        c.id = 2
        c.module_type = "HERO"
        c.image_path = path
        c.ref_image_path = None

        gate = APlusQAGate()
        score, issues, breakdown = gate._evaluate_once(c, MagicMock())

        assert score < 70, f"期望低分，实际 {score}"

    @patch("pipeline.layers.aplus_qa_gate.httpx.Client")
    def test_breakdown_keys_present(self, mock_client_cls, tmp_path):
        """_evaluate_once 结果必须包含 breakdown 各层字段"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_llm_response(_GOOD_LLM_RESPONSE)

        c = self._make_content(tmp_path)
        gate = APlusQAGate()
        score, issues, breakdown = gate._evaluate_once(c, MagicMock())

        for key in (
            "L1",
            "L2",
            "L3_sharpness",
            "L3_exposure",
            "L4_intent",
            "L5_consistency",
            "L6_commercial",
        ):
            assert key in breakdown, f"breakdown 缺少字段：{key}"


class TestRunIntegration:
    @patch("pipeline.layers.aplus_qa_gate.httpx.Client")
    def test_run_returns_expected_structure(self, mock_client_cls, tmp_path):
        """run() 传入合法 content，返回完整结果结构"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_llm_response(_GOOD_LLM_RESPONSE)

        img_path = _make_png(str(tmp_path / "img.png"), 1500, 500)
        fake_module = MagicMock()
        fake_module.module_type = "HERO"
        fake_module.image_path = img_path
        fake_module.expected_width = 1500
        fake_module.expected_height = 500

        fake_content = MagicMock()
        fake_content.id = 1
        fake_content.modules = [fake_module]
        fake_content.qa_score = None
        fake_content.qa_status = None

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = (
            fake_content
        )

        gate = APlusQAGate(max_retry=0)
        result = gate.run(1, session=fake_session)

        assert "score" in result
        assert "passed" in result
        assert "issues" in result
        assert "retry_count" in result
        assert "breakdown" in result
        assert isinstance(result["score"], (int, float))
        assert isinstance(result["passed"], bool)

    @patch("pipeline.layers.aplus_qa_gate.httpx.Client")
    def test_run_not_found_returns_error(self, mock_client_cls):
        """run() content 不存在 → score=0，issues 含'不存在'提示"""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = None

        gate = APlusQAGate()
        result = gate.run(9999, session=fake_session)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert any("不存在" in i for i in result["issues"])


class TestRefinePrompt:
    """验证 _refine_prompt：LLM 改写成功/失败时的行为，以及改写后写回 DB。"""

    def test_refine_prompt_success(self):
        """LLM 返回合法改写文本（>20字符）→ 返回改写后 prompt"""
        gate = APlusQAGate()
        refined_text = "A high-quality product photo with sharp focus, balanced exposure, centered on white background"

        with patch(
            "pipeline.layers.aplus_qa_gate._call_llm", return_value=refined_text
        ):
            result = gate._refine_prompt(
                prompt_text="original prompt",
                issues=["图片模糊", "曝光不足"],
                breakdown={"L1": 20, "L2": 8, "L3_sharpness": 3, "L3_exposure": 3},
            )

        assert result == refined_text

    def test_refine_prompt_llm_returns_empty(self):
        """LLM 返回空字符串 → 回退到原 prompt，不抛异常"""
        gate = APlusQAGate()
        original = "original prompt text"

        with patch("pipeline.layers.aplus_qa_gate._call_llm", return_value=""):
            result = gate._refine_prompt(
                prompt_text=original,
                issues=["图片模糊"],
                breakdown={"L1": 20},
            )

        assert result == original

    def test_refine_prompt_llm_returns_too_short(self):
        """LLM 返回内容 ≤20 字符（无效）→ 回退到原 prompt"""
        gate = APlusQAGate()
        original = "original prompt text"

        with patch("pipeline.layers.aplus_qa_gate._call_llm", return_value="too short"):
            result = gate._refine_prompt(
                prompt_text=original,
                issues=["图片模糊"],
                breakdown={"L1": 20},
            )

        assert result == original

    @patch("pipeline.layers.aplus_qa_gate._call_llm")
    def test_run_does_not_regenerate_when_qa_call_is_unavailable(self, mock_call_llm, tmp_path):
        """QA LLM 不可用/JSON 持续非法是 QA 调用失败，不应浪费图片重生次数。"""
        img_path = _make_png(str(tmp_path / "img.png"), 1536, 1024)
        mock_call_llm.return_value = "not json"

        fake_content = MagicMock()
        fake_content.id = 77
        fake_content.module_type = "HERO"
        fake_content.image_path = img_path
        fake_content.reference_image_paths = ""
        fake_content.image_prompt = "original product prompt"
        fake_content.retry_count = 0
        fake_content.qa_score = None
        fake_content.qa_passed = None
        fake_content.qa_issues = None

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = fake_content
        regenerate_fn = MagicMock()

        gate = APlusQAGate(max_retry=1)
        result = gate.run(77, session=fake_session, regenerate_fn=regenerate_fn)

        assert result["passed"] is False
        assert result["retry_count"] == 0
        regenerate_fn.assert_not_called()
        payload = json.loads(fake_content.qa_issues)
        assert payload["breakdown"]["qa_retryable_failure"] is True

    @patch("pipeline.layers.aplus_qa_gate._call_llm")
    def test_run_regenerates_when_delivery_status_failed_despite_high_score(self, mock_call_llm, tmp_path):
        """总分过线但 L4 intent 失败时不能把 qa_passed 写成 true，应继续飞轮重生。"""
        img_path = _make_png(str(tmp_path / "intent_bad.png"), 1536, 1024)
        low_intent = {
            **_GOOD_LLM_RESPONSE,
            "L4_intent": 5,
            "issues": ["模块意图不符"],
        }
        mock_call_llm.side_effect = [
            json.dumps(low_intent),
            "A sharper module-specific prompt with explicit intent composition and product identity lock",
            json.dumps(_GOOD_LLM_RESPONSE),
        ]

        fake_content = MagicMock()
        fake_content.id = 88
        fake_content.module_type = "DETAIL"
        fake_content.image_path = img_path
        fake_content.reference_image_paths = str(tmp_path / "real_detail.webp")
        fake_content.image_prompt = "original product prompt"
        fake_content.retry_count = 0
        fake_content.qa_score = None
        fake_content.qa_passed = None
        fake_content.qa_issues = None

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = fake_content
        regenerate_fn = MagicMock()

        gate = APlusQAGate(max_retry=1)
        gate.run(88, session=fake_session, regenerate_fn=regenerate_fn)

        regenerate_fn.assert_called_once_with(88)
        assert fake_content.retry_count == 1

    @patch("pipeline.layers.aplus_qa_gate._call_llm")
    def test_run_refines_prompt_and_commits(self, mock_call_llm, tmp_path):
        """run() QA 失败时：_refine_prompt 改写 image_prompt 并 commit 写回 DB"""
        # 构造一张注定低分的图（尺寸偏差大，LLM 评低分）
        img_path = _make_png(str(tmp_path / "bad.png"), 800, 400)

        refined_prompt = (
            "A sharp, well-exposed product photo on clean white background, "
            "centered product, high resolution, no blur, correct Amazon A+ sizing"
        )

        # 第一次调用（LLM 图片评分）→ 返回低分 JSON
        # 后续调用（_refine_prompt 改写）→ 返回改写文本
        call_results = [
            # _score_llm 第一轮评估（传 image_path）→ 返回低分 JSON
            json.dumps(_POOR_LLM_RESPONSE),
            # _refine_prompt 改写（纯文字）→ 返回改写 prompt
            refined_prompt,
            # _score_llm 第二轮评估（重生图后）→ 返回高分 JSON，让流程正常退出
            json.dumps(_GOOD_LLM_RESPONSE),
        ]
        mock_call_llm.side_effect = call_results

        # 构造 fake content：image_prompt 有值，qa_score/qa_passed/qa_issues 支持赋值
        fake_content = MagicMock()
        fake_content.id = 42
        fake_content.module_type = "HERO"
        fake_content.image_path = img_path
        fake_content.ref_image_path = None
        fake_content.image_prompt = "original product prompt"
        fake_content.retry_count = 0
        fake_content.qa_score = None
        fake_content.qa_passed = None
        fake_content.qa_issues = None

        # 第一次 first() 返回 fake_content，第二次（expire 后重查）也返回它
        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = (
            fake_content
        )

        # regenerate_fn 什么都不做（避免真实生图）
        regenerate_fn = MagicMock()

        gate = APlusQAGate(max_retry=1)
        gate.run(42, session=fake_session, regenerate_fn=regenerate_fn)

        # 验证：image_prompt 被改写为 refined_prompt
        assert fake_content.image_prompt == refined_prompt, (
            f"期望 image_prompt 被改写，实际值：{fake_content.image_prompt}"
        )
        # 验证：session.commit() 至少被调用过（改写后写回 + 每轮 QA 写回）
        assert fake_session.commit.call_count >= 2, (
            f"期望 commit ≥2 次，实际 {fake_session.commit.call_count} 次"
        )
        # 验证：regenerate_fn 被调用了一次（触发重生图）
        regenerate_fn.assert_called_once_with(42)
