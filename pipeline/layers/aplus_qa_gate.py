"""A+ 图片 QA Gate（T6 / L4.8）

对标 slot 图的 ``qa_gate.py``，对 ``APlusContent`` 的生成图做自动评分 + 自动重试。

评分体系（满分 100，≥70 通过）：

    L1 技术基础     20 分   本地计算
        L1.1  文件存在且可读           10 分
        L1.2  格式(JPEG/PNG) + RGB色彩空间 + ≤2MB  10 分

    L2 尺寸合规     15 分   本地计算
        精确匹配期望尺寸 → 15 分
        宽高各在 ±5% 容差内 → 8 分
        否则 → 0 分

    L3 视觉技术质量  20 分   LLM 评估
        L3.1  清晰度 / 焦点            10 分
        L3.2  曝光 / 色彩              10 分

    L4 模块意图适配  25 分   LLM 评估（按 module_type 分支）
        HERO / LIFESTYLE / BRAND_STORY / BENEFIT / DETAIL / COMPARISON / CROSS_SELL

    L5 产品一致性   10 分   LLM 评估
        有参考图时：与参考图对比；无参考图时：评估产品可识别性

    L6 品牌商业价值  10 分   LLM 评估
        移动端可读性、视觉冲击力、商业转化潜力

L1+L2（35 分）纯技术本地计算；L3~L6（65 分）单次 LLM 调用。
LLM 失败或返回非法 JSON 时必须硬失败，禁止用默认分数伪装有效 QA。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any

import httpx

from pipeline.config import config
from pipeline.layers.image_path_security import (
    filter_external_image_paths,
    validate_external_image_path,
)
from pipeline.models.aplus_content import APlusContent
from pipeline.models.base import get_session

log = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────

# 模块类型 → 期望尺寸（与 aplus_image_generator 中的常量保持一致）
_EXPECTED_SIZE: dict[str, tuple[int, int]] = {
    "HERO": (1536, 1024),
    "LIFESTYLE": (1536, 1024),
    "BRAND_STORY": (1536, 1024),
    "BENEFIT": (1024, 1024),
    "DETAIL": (1024, 1024),
    "COMPARISON": (1024, 1024),
    "CROSS_SELL": (1024, 1024),
}

# 尺寸容差（±5%）
_SIZE_TOLERANCE = 0.05

# 文件大小限制（亚马逊官方要求 ≤ 2MB）
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB

# 评分阈值：首次评估须达到 70 分，重试后降至 60 分（对齐套图两档通过线）
_PASS_SCORE = 70.0
_RETRY_PASS_SCORE = 60.0
_MAX_RETRY = 3

# 各模块 L4 意图评估说明
_L4_MODULE_INTENT: dict[str, str] = {
    "HERO": (
        "HERO 模块：高冲击力视觉首屏。"
        "评估要点：产品/品牌是否绝对主导画面，是否传达强烈受益感或价值主张，"
        "是否没有杂乱无关元素，视觉焦点是否清晰有力。"
        "满分标准：产品占主导地位，背景简洁有力，能在 0.5 秒内抓住注意力。"
    ),
    "LIFESTYLE": (
        "LIFESTYLE 模块：产品处于真实使用状态。"
        "评估要点：产品是否处于真实使用中（人在使用产品做某事），"
        "场景是否自然真实而非棚拍摆拍，移动端关键文字是否可读（如有），"
        "能否让目标用户产生代入感。"
        "满分标准：产品在真实生活场景中被使用，场景感强，有情境带入感。"
    ),
    "BRAND_STORY": (
        "BRAND_STORY 模块：情感叙事与品牌故事。"
        "评估要点：是否传达情感/品牌故事而非单纯产品摆拍，"
        "是否有场景/人物/情绪渲染，是否让人产生品牌认同感，"
        "能否区分于普通产品展示图。"
        "满分标准：有故事感、情绪感，品牌调性清晰。"
    ),
    "BENEFIT": (
        "BENEFIT 模块：功能卖点可视化。"
        "评估要点：是否清晰展示 3~5 个功能卖点，"
        "卖点是否通过图标+短文字或视觉方式呈现，"
        "视觉层级是否清晰，是否避免文字堆砌。"
        "满分标准：卖点清晰、视觉化，移动端一眼看懂。"
    ),
    "DETAIL": (
        "DETAIL 模块：细节特写展示。"
        "评估要点：是否是产品细节/材质/工艺的近景特写，"
        "背景是否简洁不干扰主体，细节纹理/质感是否清晰可见，"
        "能否建立产品品质感。"
        "满分标准：细节真实清晰，材质质感表现出色，背景干净。"
    ),
    "COMPARISON": (
        "COMPARISON 模块：对比展示竞争优势。"
        "评估要点：对比结构是否清晰（左/右 或 前/后 对比），"
        "是否清楚展示本品相对优势，是否避免直接命名竞品，"
        "差异化信息是否在移动端可读。"
        "满分标准：对比直观，优势一目了然，结构整洁。"
    ),
    "CROSS_SELL": (
        "CROSS_SELL 模块：关联销售多产品展示。"
        "评估要点：多产品是否和谐并列（非杂乱堆放），"
        "产品间视觉关联性是否强，是否能引导用户看到关联购买价值，"
        "整体构图是否平衡。"
        "满分标准：多产品整洁排列，关联感强，引导购买欲望。"
    ),
}

_LLM_HARD_FAILURE_SCORES = {
    "L3_sharpness": 0,
    "L3_exposure": 0,
    "L4_intent": 0,
    "L5_consistency": 0,
    "L6_commercial": 0,
    "llm_unavailable": True,
    "qa_retryable_failure": True,
}

_LLM_QA_CALL_ATTEMPTS = 2

# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_mime_type(image_path: str) -> str:
    """根据文件扩展名返回 MIME 类型。"""
    ext = os.path.splitext(image_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


def _read_image_info(path: str) -> tuple[int, int, str] | None:
    """用 PIL 读取图片尺寸和色彩模式，返回 (width, height, mode)；失败返回 None。"""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size[0], img.size[1], img.mode
    except Exception as exc:
        log.warning("PIL 读取图片信息失败 path=%s err=%s", path, exc)
        return None


def _strip_markdown_fence(text: str) -> str:
    """去除 LLM 输出中的 markdown 代码块包裹（```json ... ```）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # 去掉首行（```json 或 ```）和末行（```）
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner).strip()
    return stripped


def _extract_issue_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [str(raw)]
    if isinstance(parsed, dict):
        issues = parsed.get("issues", [])
        return [str(i) for i in issues] if isinstance(issues, list) else [str(issues)]
    if isinstance(parsed, list):
        return [str(i) for i in parsed]
    return [str(parsed)]


def _try_repair_json(text: str) -> dict:
    """尝试解析 JSON；失败时尝试简单修复（截断到最后一个 }）后再解析。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截断到最后一个 }
        last_brace = text.rfind("}")
        if last_brace != -1:
            try:
                return json.loads(text[: last_brace + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _call_llm(
    prompt: str,
    image_path: str | None = None,
    ref_image_path: str | None = None,
    ref_image_paths: list[str] | None = None,
) -> str:
    """调用视觉 LLM（147AI OpenAI-compatible endpoint）。

    支持传入待评估图片和可选的参考图片。
    失败时返回空字符串，不抛异常。
    """
    api_key = config.api_key or "test-api-key"

    endpoint = f"{config.api_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 构建消息内容：文字 prompt + 图片（评估图在前，参考图在后）
    content: list = [{"type": "text", "text": prompt}]

    paths = filter_external_image_paths([p for p in [image_path] if p])
    if image_path and not paths:
        log.warning("A+ QA 拒绝外发不安全或非图片路径")
        return ""
    if ref_image_paths:
        paths.extend(filter_external_image_paths(ref_image_paths))
    elif ref_image_path:
        validated_ref = validate_external_image_path(ref_image_path)
        if validated_ref:
            paths.append(validated_ref)
    for path in paths:
        try:
            with open(path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{_get_mime_type(path)};base64,{img_b64}",
                        "detail": "low",
                    },
                }
            )
        except OSError as exc:
            log.warning("读取图片失败 path=%s err=%s", path, exc)

    payload: dict = {
        "model": config.vision_model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("LLM 调用失败: %s", exc)
        return ""


# ── 主类 ──────────────────────────────────────────────────────────────────────


class APlusQAGate:
    """A+ 图 QA Gate：6层100分评估体系 + 自动重试。

    L1(20) + L2(15) 本地计算；L3~L6(65) 单次 LLM 调用。
    """

    def __init__(self, max_retry: int = _MAX_RETRY) -> None:
        self.max_retry = max_retry

    # ── L1 技术基础（20 分）──────────────────────────────────────────────────

    def _score_technical_base(self, image_path: str | None) -> tuple[float, list[str]]:
        """L1 技术基础：文件存在/可读(10分) + 格式/色彩空间/大小(10分)。"""
        issues: list[str] = []
        score = 0.0

        # L1.1：文件存在且可读（10 分）
        if not image_path:
            issues.append("image_path 为空")
            return 0.0, issues
        if not os.path.isfile(image_path):
            issues.append(f"图片文件不存在：{image_path}")
            return 0.0, issues
        try:
            with open(image_path, "rb") as f:
                f.read(1)
            score += 10.0
        except Exception as exc:
            issues.append(f"图片不可读：{exc}")
            return 0.0, issues

        # L1.2：格式 + RGB色彩空间 + ≤2MB（10 分，全部满足才给分）
        l12_ok = True

        # 检查文件格式（JPEG / PNG）
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            issues.append(f"文件格式不合规（{ext}），须为 JPEG 或 PNG")
            l12_ok = False

        # 检查色彩空间（须为 RGB，CMYK 会被亚马逊直接拒稿）
        img_info = _read_image_info(image_path)
        if img_info is not None:
            mode = img_info[2]
            if mode not in ("RGB", "RGBA"):
                issues.append(
                    f"色彩空间不合规（{mode}），须为 RGB（CMYK 会被亚马逊拒稿）"
                )
                l12_ok = False
        else:
            issues.append("无法读取图片色彩空间信息")
            l12_ok = False

        # 检查文件大小（≤ 2MB）
        try:
            file_size = os.path.getsize(image_path)
            if file_size > _MAX_FILE_SIZE:
                issues.append(f"文件过大：{file_size / 1024 / 1024:.1f}MB（上限 2MB）")
                l12_ok = False
        except Exception as exc:
            issues.append(f"无法获取文件大小：{exc}")
            l12_ok = False

        if l12_ok:
            score += 10.0

        return score, issues

    # ── L2 尺寸合规（15 分）──────────────────────────────────────────────────

    def _score_resolution(
        self, image_path: str, module_type: str
    ) -> tuple[float, list[str]]:
        """L2 尺寸合规：精确匹配15分，±5%容差8分，否则0分。"""
        issues: list[str] = []
        expected = _EXPECTED_SIZE.get((module_type or "").upper())

        if expected is None:
            issues.append(f"未知 module_type={module_type}，跳过尺寸校验")
            return 15.0, issues  # 未知类型不扣分

        img_info = _read_image_info(image_path)
        if img_info is None:
            issues.append("PIL 无法读取图片尺寸")
            return 0.0, issues

        actual_w, actual_h = img_info[0], img_info[1]
        exp_w, exp_h = expected

        if actual_w == exp_w and actual_h == exp_h:
            # 精确匹配
            return 15.0, issues

        # 检查 ±5% 容差
        w_ok = abs(actual_w - exp_w) / exp_w <= _SIZE_TOLERANCE
        h_ok = abs(actual_h - exp_h) / exp_h <= _SIZE_TOLERANCE

        if w_ok and h_ok:
            issues.append(
                f"尺寸在容差范围内：实际 {actual_w}x{actual_h}，"
                f"期望 {exp_w}x{exp_h}（±5% 内得 8 分）"
            )
            return 8.0, issues

        issues.append(f"尺寸不符：实际 {actual_w}x{actual_h}，期望 {exp_w}x{exp_h}")
        return 0.0, issues

    # ── L3~L6 LLM 评估（65 分）──────────────────────────────────────────────

    def _score_llm(
        self,
        image_path: str,
        module_type: str,
        ref_image_path: str | None = None,
        ref_image_paths: list[str] | None = None,
        custom_requirements: dict | None = None,
    ) -> tuple[float, list[str], dict[str, int]]:
        """L3~L6 单次 LLM 调用评估（65 分）。

        LLM 不可用或 JSON 无效时返回硬失败，禁止 fallback 分数放行。
        返回 (总分, issues列表, 各层得分dict)。
        """
        module_key = (module_type or "HERO").upper()
        l4_intent_desc = _L4_MODULE_INTENT.get(
            module_key, f"按 {module_key} 模块的亚马逊 A+ 最佳实践评估内容意图适配度。"
        )

        # 参考图说明
        ref_note = (
            "第二张及后续图片为产品参考图，请在评估 L5 产品一致性时与第一张（待评估图）进行对比。"
            if (ref_image_paths or validate_external_image_path(ref_image_path))
            else "本次无产品参考图，L5 请评估产品在图中的可识别性和一致性表现。"
        )

        prompt = f"""你是亚马逊 A+ 内容图片质量评审专家。请对提供的图片进行专业评分。

## 评分任务

按以下 4 个维度评分，输出严格合法的 JSON（不含任何解释文字）：

### L3 视觉技术质量（满分 20 分）
- **L3_sharpness**（0-10）：图片清晰度与焦点。10分=极清晰焦点准确；0分=严重模糊/失焦
- **L3_exposure**（0-10）：曝光与色彩。10分=曝光完美色彩真实；0分=严重过曝/欠曝或色偏

### L4 模块意图适配（满分 25 分）
- **L4_intent**（0-25）：{l4_intent_desc}
  25分=完美契合；15分=基本符合；5分=明显偏离；0分=完全不符合

### L5 产品一致性（满分 10 分）
- **L5_consistency**（0-10）：{ref_note}
  同时检查用户要求：{json.dumps(custom_requirements or {}, ensure_ascii=False)}
  10分=产品高度一致且满足用户 must_show / must_not_show；5分=基本一致但有轻微遗漏；0分=完全无法识别或违反用户禁止项

### L6 品牌商业价值（满分 10 分）
- **L6_commercial**（0-10）：综合评估移动端可读性 + 视觉冲击力 + 商业转化潜力
  10分=移动端可读、视觉冲击强、极具转化力；0分=三项均差
  同时检查构图安全区：重要文字、产品、callout、对比元素不得贴边或被画布边缘意外截断；DETAIL/macro 允许有意局部裁切，但目标细节本身必须完整可读。

## 亚马逊 A+ 注意事项
- 禁止出现促销语言：best-selling、buy now、on sale、#1
- 文字须在移动端可读（设计稿字号 ≥24pt）
- 关键信息须在图片上方/中央 60% 区域内
- CMYK 色彩空间会被拒稿（技术层已检测，此处仅评估内容）

## 输出格式（严格 JSON，不含其他文字）
{{
  "L3_sharpness": <0-10的整数>,
  "L3_exposure": <0-10的整数>,
  "L4_intent": <0-25的整数>,
  "L5_consistency": <0-10的整数>,
  "L6_commercial": <0-10的整数>,
  "issues": ["<发现的具体问题1>", "<发现的具体问题2>"]
}}"""

        raw = ""
        data: dict[str, Any] = {}
        for attempt in range(1, _LLM_QA_CALL_ATTEMPTS + 1):
            raw = _call_llm(
                prompt,
                image_path=image_path,
                ref_image_path=ref_image_path,
                ref_image_paths=ref_image_paths,
            )
            if not raw:
                log.warning(
                    "LLM 返回空，A+ QA 调用重试 attempt=%s/%s",
                    attempt,
                    _LLM_QA_CALL_ATTEMPTS,
                )
                continue

            cleaned = _strip_markdown_fence(raw)
            data = _try_repair_json(cleaned)
            if data:
                break
            log.warning(
                "LLM JSON 解析失败，A+ QA 调用重试 attempt=%s/%s raw_length=%s",
                attempt,
                _LLM_QA_CALL_ATTEMPTS,
                len(raw),
            )

        if not raw:
            log.warning("LLM 返回空，A+ QA 硬失败")
            return (
                0.0,
                ["LLM evaluation unavailable — retry required"],
                dict(_LLM_HARD_FAILURE_SCORES),
            )

        if not data:
            log.warning("LLM JSON 解析失败，A+ QA 硬失败 raw_length=%s", len(raw))
            return (
                0.0,
                ["Invalid LLM QA JSON — retry required"],
                dict(_LLM_HARD_FAILURE_SCORES),
            )

        # 提取各维度得分（限制在有效范围内）
        dim_scores = {
            "L3_sharpness": min(
                10,
                max(
                    0,
                    int(data.get("L3_sharpness", 0)),
                ),
            ),
            "L3_exposure": min(
                10,
                max(
                    0, int(data.get("L3_exposure", 0))
                ),
            ),
            "L4_intent": min(
                25,
                max(0, int(data.get("L4_intent", 0))),
            ),
            "L5_consistency": min(
                10,
                max(
                    0,
                    int(
                        data.get("L5_consistency", 0)
                    ),
                ),
            ),
            "L6_commercial": min(
                10,
                max(
                    0,
                    int(
                        data.get("L6_commercial", 0)
                    ),
                ),
            ),
        }

        total = float(sum(dim_scores.values()))

        # 收集 LLM 发现的问题
        llm_issues: list[str] = []
        raw_issues = data.get("issues", [])
        if isinstance(raw_issues, list):
            llm_issues = [str(i) for i in raw_issues if i]

        return total, llm_issues, dim_scores

    # ── 单次评估（组合 L1~L6）───────────────────────────────────────────────

    def _evaluate_once(
        self,
        content: APlusContent,
        session,
    ) -> tuple[float, list[str], dict]:
        """单次完整评分（L1~L6），返回 (score, issues, breakdown)。

        breakdown 结构：{"L1": float, "L2": float, "L3_sharpness": int, ...}
        """
        issues: list[str] = []
        breakdown: dict = {}

        # L1 技术基础（20 分）
        s1, i1 = self._score_technical_base(content.image_path)
        breakdown["L1"] = s1
        issues.extend(i1)

        if s1 == 0.0:
            # 文件都不存在/不可读，后续无法评估
            return 0.0, issues, breakdown

        # L2 尺寸合规（15 分）
        s2, i2 = self._score_resolution(content.image_path, content.module_type or "")
        breakdown["L2"] = s2
        issues.extend(i2)

        # HERO 白底产品图必须完整入框；本地像素检测先于 LLM，避免主观漏判。
        module_type = (content.module_type or "").upper()
        if module_type == "HERO" and content.image_path:
            from pipeline.layers.safe_frame import (
                SAFE_FRAME_MIN_MARGIN_RATIO,
                measure_white_bg_foreground_margins,
                safe_frame_failed,
            )

            safe_frame = measure_white_bg_foreground_margins(content.image_path)
            if safe_frame.get("applicable"):
                breakdown["hero_safe_frame"] = safe_frame
                min_margin = float(safe_frame.get("min_margin_ratio") or 0.0)
                if safe_frame_failed(safe_frame):
                    margins_ratio = safe_frame.get("margins_ratio") or {}
                    issues.append(
                        "HERO product safe-frame failure: product is too close to canvas edge; "
                        f"minimum margin {min_margin * 100:.1f}% is below "
                        f"{SAFE_FRAME_MIN_MARGIN_RATIO * 100:.0f}% requirement; "
                        f"margins={margins_ratio}"
                    )
                    breakdown["hero_safe_frame_failed"] = True
                else:
                    breakdown["hero_safe_frame_failed"] = False
            else:
                breakdown["hero_safe_frame"] = safe_frame
                breakdown["hero_safe_frame_failed"] = False

        # L3~L6 LLM 评估（65 分）
        ref_paths = [
            p.strip()
            for p in (content.reference_image_paths or "").split(",")
            if p.strip() and os.path.isfile(p.strip())
        ]
        custom_requirements: dict = {}
        try:
            from pipeline.layers.custom_requirement_parser import parse_custom_requirements
            from pipeline.layers.project_constraints import load_customer_brief
            from pipeline.models.project import Project

            project = session.get(Project, content.project_id)
            custom_requirements = parse_custom_requirements(
                load_customer_brief(project) if project else {}
            )
        except Exception:
            custom_requirements = {}

        s_llm, i_llm, dim_scores = self._score_llm(
            content.image_path,
            content.module_type or "HERO",
            ref_image_paths=ref_paths,
            custom_requirements=custom_requirements,
        )
        breakdown.update(dim_scores)
        issues.extend(i_llm)

        total = s1 + s2 + s_llm
        try:
            from pipeline.layers.delivery_status import is_product_fact_aplus_module

            _product_fact_required = is_product_fact_aplus_module(content.module_type)
        except Exception:
            _product_fact_required = False
        if _product_fact_required and float(dim_scores.get("L5_consistency", 0) or 0) < 8:
            issues.append("A+ product-fact module failed strict L5 consistency gate")
            total = min(total, 59.0)
        if bool(breakdown.get("hero_safe_frame_failed")):
            total = min(total, 59.0)
        breakdown["total"] = total

        log.debug(
            "A+ QA breakdown id=%s: L1=%.0f L2=%.0f LLM=%.0f total=%.1f",
            content.id,
            s1,
            s2,
            s_llm,
            total,
        )

        return total, issues, breakdown

    # ── Prompt 改写（QA 感知重试）────────────────────────────────────────────

    def _refine_prompt(
        self,
        prompt_text: str,
        issues: list[str],
        breakdown: dict,
    ) -> str:
        """根据 QA 各层得分和问题列表，调用 LLM 改写 image_prompt。

        参数：
            prompt_text: 当前生图 prompt 原文
            issues:      QA 发现的问题列表（中文）
            breakdown:   各层得分 dict，例如 {"L1": 20, "L2": 8, "L3": 5, ...}

        返回：
            改写后的 prompt 文本；失败时返回原 prompt 不抛异常。
        """
        # 构建各层说明，帮助 LLM 理解哪些方面分数低
        layer_labels = {
            "L1": "技术基础(满分20)",
            "L2": "尺寸合规(满分15)",
            "L3": "视觉技术质量(满分20)",
            "L4": "模块意图适配(满分25)",
            "L5": "产品一致性(满分10)",
            "L6": "品牌商业价值(满分10)",
        }
        layer_summary = ", ".join(
            f"{layer_labels.get(k, k)}={v}"
            for k, v in breakdown.items()
            if k in layer_labels
        )
        issues_text = (
            "\n".join(f"- {iss}" for iss in issues) if issues else "（无具体问题）"
        )

        # 各层低分阈值（低于满分60%时触发对应约束）
        layer_thresholds = {"L1": 12, "L2": 9, "L3": 12, "L4": 15, "L5": 6, "L6": 6}
        layer_constraints = {
            "L1": (
                "TECHNICAL REQUIREMENTS: ultra-sharp focus, f/8 aperture equivalent, "
                "ISO 100, no motion blur, no chromatic aberration, "
                "pure white background (#FFFFFF), product centered with 10% padding"
            ),
            "L2": (
                "SIZE COMPLIANCE: output at exact 1464×600px (WIDE) or 970×300px (TILE), "
                "maintain 1:1 aspect ratio for square modules, "
                "no letterboxing or pillarboxing, fill entire frame"
            ),
            "L3": (
                "VISUAL QUALITY: 8K commercial photography, HDR tonal range, "
                "studio strobe lighting with fill card, "
                "specular highlights on product surfaces, "
                "shadow detail preserved, no overexposure, no flat lighting"
            ),
            "L4": (
                "MODULE INTENT: hero lifestyle scene matching module purpose, "
                "product as primary visual subject (≥40% frame area), "
                "supporting props complement without obscuring product, "
                "clear visual hierarchy guiding eye to product"
            ),
            "L5": (
                "PRODUCT CONSISTENCY: PRESERVE EXACTLY product shape, brand colors, "
                "logo placement, proportions — DO NOT alter product identity, "
                "color scheme, or structural elements"
            ),
            "L6": (
                "BRAND VALUE: premium commercial aesthetic, aspirational lifestyle context, "
                "color palette matches brand identity, "
                "composition suitable for Amazon A+ premium placement"
            ),
            "hero_safe_frame": (
                "HERO SAFE FRAME: full product completely visible inside the canvas, "
                "no product part or shadow clipped by any edge, centered composition, "
                "minimum 8-12% clean white margin on all four sides"
            ),
        }

        active_constraints = [
            layer_constraints[layer]
            for layer, threshold in layer_thresholds.items()
            if breakdown.get(layer, 0) < threshold and layer in layer_constraints
        ]
        if breakdown.get("hero_safe_frame_failed"):
            active_constraints.append(layer_constraints["hero_safe_frame"])
        constraints_block = (
            "\n强制修正指令（必须全部体现在改写后的 prompt 中）：\n"
            + "\n".join(f"- {c}" for c in active_constraints)
            if active_constraints
            else ""
        )

        refine_prompt = (
            "你是一位 Amazon A+ 页面图像 prompt 优化专家。\n"
            "以下是当前的图像生成 prompt（英文）：\n"
            f"---\n{prompt_text}\n---\n\n"
            "该图经过 6 层 QA 审核，各层得分如下：\n"
            f"{layer_summary}\n\n"
            "发现的质量问题：\n"
            f"{issues_text}\n"
            f"{constraints_block}\n\n"
            "请根据上述问题，对 prompt 进行针对性改写，使生成的图片能通过 QA（总分 ≥70）。\n"
            "要求：\n"
            "1. 保持原有产品描述和核心意图不变\n"
            "2. 针对低分层的问题加入修正指令（如清晰度、曝光、色彩、产品可识别性等）\n"
            "3. 输出格式：仅输出改写后的英文 prompt 原文，不加任何解释或前缀\n"
            "4. 长度控制在 500 词以内"
        )

        # 纯文字 prompt 改写，不传图片
        refined = _call_llm(refine_prompt)
        if refined and len(refined.strip()) > 20:
            log.info("A+ QA prompt 改写成功，改写长度 %d 字符", len(refined))
            return refined.strip()
        log.warning("A+ QA prompt 改写失败或返回为空，使用原 prompt")
        return prompt_text

    # ── 主入口 ───────────────────────────────────────────────────────────────

    def run(
        self,
        aplus_content_id: int,
        session=None,
        regenerate_fn=None,
    ) -> dict[str, Any]:
        """对单个 APlusContent 跑 QA + 重试，结果写回 DB 并返回。

        参数：
            aplus_content_id: APlusContent 主键
            session: 可选外部 session；为空时本方法自行管理
            regenerate_fn: 可选重生图回调（默认调用 APlusImageGenerator.generate_single）

        返回：
            {
                "score": float,          # 最终得分（满分 100）
                "passed": bool,          # 是否通过（≥70 分）
                "issues": list[str],     # 发现的问题列表
                "retry_count": int,      # 已重试次数
                "breakdown": dict,       # 各层得分明细
            }
        """
        own_session = session is None
        if own_session:
            session = get_session()

        try:
            content = session.query(APlusContent).filter_by(id=aplus_content_id).first()
            if content is None:
                return {
                    "score": 0.0,
                    "passed": False,
                    "issues": [f"APlusContent id={aplus_content_id} 不存在"],
                    "retry_count": 0,
                    "breakdown": {},
                }

            retry_count = int(content.retry_count or 0)

            while True:
                score, issues, breakdown = self._evaluate_once(content, session)
                # 首次评估用严格阈值；有重试记录后降至宽松阈值
                threshold = _PASS_SCORE if retry_count == 0 else _RETRY_PASS_SCORE
                passed = score >= threshold

                ref_raw = getattr(content, "reference_image_paths", None)
                ref_text = ref_raw if isinstance(ref_raw, str) else ""
                ref_paths = [p.strip() for p in ref_text.split(",") if p.strip()]
                try:
                    from pipeline.layers.delivery_status import aplus_delivery_metadata

                    delivery = aplus_delivery_metadata(
                        passed=passed,
                        score=score,
                        breakdown=breakdown,
                        module_type=content.module_type,
                        reference_paths=ref_paths,
                    )
                except Exception as delivery_exc:
                    log.warning("A+ delivery status classification failed id=%s: %s", aplus_content_id, delivery_exc)
                    delivery = {}
                issue_payload = {"issues": issues, "breakdown": breakdown, **delivery}
                delivery_status = str(delivery.get("delivery_status") or "")
                delivery_passed = bool(passed and delivery_status == "final")

                # 写回 DB（每轮都写，保证幂等可见）
                content.qa_score = float(score)
                content.qa_passed = delivery_passed
                content.qa_issues = json.dumps(issue_payload, ensure_ascii=False)
                content.retry_count = retry_count
                session.add(content)
                session.commit()

                log.info(
                    "A+ QA 评估 id=%s score=%.1f passed=%s retry=%s breakdown=%s issues=%s",
                    aplus_content_id,
                    score,
                    delivery_passed,
                    retry_count,
                    breakdown,
                    issues,
                )

                if delivery_passed:
                    break
                if bool(breakdown.get("qa_retryable_failure")):
                    log.warning(
                        "A+ QA 调用失败 id=%s，暂停图片重生并等待 QA 重试",
                        aplus_content_id,
                    )
                    break
                if retry_count >= self.max_retry:
                    log.warning(
                        "A+ QA 重试已达上限 id=%s retry=%s，停止",
                        aplus_content_id,
                        retry_count,
                    )
                    break

                # 先用 QA 问题改写 prompt，再触发重生图
                retry_count += 1
                log.info(
                    "A+ QA 触发 prompt 改写 + 重生图 id=%s retry=%s/%s",
                    aplus_content_id,
                    retry_count,
                    self.max_retry,
                )
                try:
                    # Step 1：用 QA issues + breakdown 改写 image_prompt
                    current_prompt = content.image_prompt or ""
                    if current_prompt:
                        refined = self._refine_prompt(current_prompt, issues, breakdown)
                        if refined != current_prompt:
                            content.image_prompt = refined
                            session.add(content)
                            session.commit()
                            log.info(
                                "A+ QA prompt 已改写 id=%s retry=%s",
                                aplus_content_id,
                                retry_count,
                            )

                    # Step 2：重生图
                    if regenerate_fn is not None:
                        regenerate_fn(aplus_content_id)
                    else:
                        from pipeline.layers.aplus_image_generator import (
                            generate_single,
                        )

                        generate_single(aplus_content_id, session=session)

                    # Step 3：刷新 content 对象，进入下一轮 QA
                    session.expire(content)
                    content = (
                        session.query(APlusContent)
                        .filter_by(id=aplus_content_id)
                        .first()
                    )
                except Exception as exc:
                    log.error(
                        "A+ QA 重生图失败 id=%s err=%s（不抛出，记录后退出）",
                        aplus_content_id,
                        exc,
                    )
                    issues.append(f"重生图失败：{exc}")
                    content.qa_issues = json.dumps({"issues": issues}, ensure_ascii=False)
                    content.retry_count = retry_count
                    session.add(content)
                    session.commit()
                    break

            return {
                "score": float(content.qa_score or 0.0),
                "passed": bool(content.qa_passed),
                "issues": _extract_issue_list(content.qa_issues),
                "retry_count": int(content.retry_count or 0),
                "breakdown": breakdown,
            }

        finally:
            if own_session:
                session.close()
