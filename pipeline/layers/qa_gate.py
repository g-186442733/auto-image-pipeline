from __future__ import annotations

import base64
import json
import os

import httpx
from PIL import Image

from pipeline.config import config
from pipeline.models.base import commit_with_retry, get_session
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.slot_plan import SlotPlan
from pipeline.utils.logger import setup_logger

__all__ = [
    "run_qa_checks",
    "run_qa_checks_legacy",
    "run_qa_gate",
    "llm_qa_evaluate",
    "validate_image",
    "check_resolution",
    "check_aspect_ratio",
    "check_background",
    "check_image_size",
    "check_text_overlay",
    "check_brand_consistency",
    "check_text_accuracy",
    "check_compliance",
    "check_visual_anchor",
    "check_reference_chain",
    "check_consistency",
    "compute_gate5_score",
    "refine_prompt_with_qa",
    "evaluate_set_intent_structure",
    "run_series_qa",
]

logger = setup_logger("aip.qa_gate")

_MIN_DIMENSION = 500
_QA_DIMENSION_KEYS = (
    "A1",
    "A2",
    "A3",
    "B1",
    "B2",
    "C1",
    "C2",
    "C3",
    "C4",
    "C5",
    "D1",
    "D2",
    "E1",
    "E2",
)


def _read_image_dimensions(image_path: str) -> tuple[int, int]:
    with Image.open(image_path) as img:
        return img.size


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _read_png_dimensions(image_path: str) -> tuple[int, int]:
    with open(image_path, "rb") as f:
        sig = f.read(8)
    if sig != _PNG_SIG:
        raise ValueError("Not a valid PNG")
    return _read_image_dimensions(image_path)


def _get_mime_type(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


def validate_image(image_path: str) -> tuple[bool, str]:
    """Basic sanity: file exists, valid image (Pillow-readable), minimum dimensions."""
    if not os.path.isfile(image_path):
        return False, f"File does not exist: {image_path}"
    try:
        w, h = _read_image_dimensions(image_path)
    except (ValueError, OSError, Exception) as exc:
        return False, str(exc)
    if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
        return (
            False,
            f"Image too small: {w}x{h}, minimum {_MIN_DIMENSION}x{_MIN_DIMENSION}",
        )
    return True, ""


def check_resolution(image_path: str) -> bool:
    w, h = _read_image_dimensions(image_path)
    long_side = max(w, h)
    logger.debug("Resolution %dx%d, long side %d", w, h, long_side)
    return long_side >= 1024


def check_aspect_ratio(image_path: str, expected: str = "16:9") -> bool:
    w, h = _read_image_dimensions(image_path)
    parts = expected.split(":")
    exp_w, exp_h = int(parts[0]), int(parts[1])
    expected_ratio = exp_w / exp_h
    actual_ratio = w / h if h > 0 else 0
    tolerance = 0.1
    return abs(actual_ratio - expected_ratio) <= tolerance


_BG_PASS_DIST = 15  # 亚马逊白底：平均像素欧氏距离 < 15 视为纯白
_BG_WARN_DIST = 30  # 距离 15-30 为疑似白底警告，> 30 为失败
_SIZE_HARD_MIN = 1000  # 亚马逊硬性最低要求（短边像素）
_SIZE_SOFT_MIN = 1600  # 亚马逊推荐最低尺寸（短边像素）


def check_background(image_path: str) -> float:
    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        s = 10
        corners = [
            (0, 0, s, s),
            (w - s, 0, w, s),
            (0, h - s, s, h),
            (w - s, h - s, w, h),
        ]
        pixels = []
        for box in corners:
            pixels.extend(list(img.crop(box).getdata()))
        avg_dist = sum(
            ((255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2) ** 0.5
            for r, g, b in pixels
        ) / len(pixels)
        if avg_dist < _BG_PASS_DIST:
            return 1.0
        elif avg_dist <= _BG_WARN_DIST:
            return 0.5
        else:
            return 0.0
    except Exception as exc:
        logger.warning("check_background 读取失败: %s", exc)
        return 0.5


def check_image_size(image_path: str) -> float:
    try:
        w, h = Image.open(image_path).size
        min_dim = min(w, h)
        if min_dim < _SIZE_HARD_MIN:
            return 0.0
        elif min_dim < _SIZE_SOFT_MIN:
            return 0.5
        else:
            return 1.0
    except Exception as exc:
        logger.warning("check_image_size 读取失败: %s", exc)
        return 0.5


def check_text_overlay(image_path: str) -> bool:
    if not config.openai_api_key:
        logger.info("No OpenAI API key configured; assuming no text overlay")
        return False

    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
    except OSError as exc:
        logger.warning("Cannot read image for text overlay check: %s", exc)
        return False

    endpoint = f"{config.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.openai_model or "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": 'Does this image contain any visible text overlay or watermark? Reply ONLY with JSON: {"has_text": true} or {"has_text": false}',
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{_get_mime_type(image_path)};base64,{img_b64}",
                            "detail": "low",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 64,
        "temperature": 0,
    }

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        result = json.loads(raw)
        return bool(result.get("has_text", False))
    except Exception as exc:
        logger.warning("Text overlay check failed, assuming no text: %s", exc)
        return False


def _call_gemini(
    prompt: str,
    image_path: str | None = None,
    image_paths: list[str] | None = None,
    json_mode: bool = False,
) -> str:
    """Call vision/text LLM via 147AI OpenAI-compatible endpoint.

    Returns raw text or empty string on failure.
    Accepts a single image_path (backward compat) or a list via image_paths.
    Both can be combined; image_path is prepended first.
    json_mode=True 时追加 response_format=json_object，强制输出合法 JSON。
    """
    api_key = config.api_key
    if not api_key:
        return ""

    endpoint = f"{config.api_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    content: list = [{"type": "text", "text": prompt}]

    all_paths: list[str] = []
    if image_path:
        all_paths.append(image_path)
    if image_paths:
        all_paths.extend(image_paths)

    for path in all_paths:
        if path and os.path.isfile(path):
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
                logger.warning("Cannot read image for LLM call: %s", exc)

    payload: dict = {
        "model": config.vision_model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0,
    }
    # 强制 JSON 模式，避免 LLM 输出 markdown 包裹或截断导致解析失败
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return ""


def _angle_correction_block(issues: list[str]) -> str:
    for issue in issues:
        if not isinstance(issue, str) or not issue.startswith("Angle mismatch:"):
            continue
        prefix = "Angle mismatch: target "
        marker = " but generated "
        if not issue.startswith(prefix) or marker not in issue:
            continue
        target, actual = issue[len(prefix) :].split(marker, 1)
        target = target.strip()
        actual = actual.strip()
        if not target or not actual:
            continue
        return (
            "\n\nANGLE MISMATCH CORRECTION:\n"
            f"- TARGET CAMERA ANGLE: {target}\n"
            f"- FORBIDDEN CAMERA ANGLE: {actual}\n"
            "- Do not use the forbidden angle again. Rewrite the prompt so the next generation uses the target camera angle as a hard composition constraint.\n"
            "- Place the target angle instruction near the beginning of the prompt and repeat it in the negative constraints.\n"
            "- If the target is macro close-up, require a tight partial crop/detail view rather than a full product view.\n"
            "- If the target is side profile, require a clear side-on 70-90 degree camera view.\n"
            "- If the target is overhead shot, require a top-down 90-degree flat-lay camera.\n"
            "- If the target is front view, require a direct front-facing/orthographic camera and explicitly avoid 3/4 view."
        )
    return ""


def refine_prompt_with_qa(
    prompt_text: str,
    issues: list[str],
    dim_scores: dict,
    prompt_asset_id: int | None = None,
) -> str:
    dim_labels = {
        "A": "平台合规(满分25)",
        "B": "技术质量(满分15)",
        "C": "AI瑕疵控制(满分25)",
        "D": "产品一致性(满分25)",
        "E": "商业品质(满分10)",
    }
    dim_summary = ", ".join(
        f"{dim_labels.get(k, k)}={v}" for k, v in dim_scores.items()
    )
    issues_text = (
        "\n".join(f"- {iss}" for iss in issues) if issues else "（无具体问题）"
    )

    angle_block = _angle_correction_block(issues)
    refine_prompt = (
        "你是一位电商产品图 prompt 优化专家。\n"
        "以下是当前的图像生成 prompt（英文）：\n"
        f"---\n{prompt_text}\n---\n\n"
        "该图经过 QA 审核，各维度得分如下：\n"
        f"{dim_summary}\n\n"
        "发现的质量问题：\n"
        f"{issues_text}\n"
        f"{angle_block}\n\n"
        "请根据上述问题，对 prompt 进行针对性改写，使生成的图片能通过 QA。\n"
        "要求：\n"
        "1. 保持原有产品描述和核心意图不变\n"
        "2. 针对低分维度的问题加入修正指令（如背景纯白、无文字叠加、产品清晰等）\n"
        "3. 如存在 ANGLE MISMATCH CORRECTION，必须保留目标角度、禁止失败角度，并把角度约束写成英文硬性构图要求\n"
        "4. 输出格式：仅输出改写后的英文 prompt 原文，不加任何解释或前缀\n"
        "5. 长度控制在 500 词以内"
    )

    refined = _call_gemini(refine_prompt, json_mode=False)
    if not (refined and len(refined.strip()) > 20):
        logger.warning("QA prompt refinement 失败或返回为空，使用原 prompt")
        return prompt_text

    refined_text = refined.strip()
    logger.info("QA prompt refinement 成功，改写长度 %d 字符", len(refined_text))

    if prompt_asset_id is not None and refined_text != prompt_text:
        session = get_session()
        try:
            pa = session.get(PromptAsset, prompt_asset_id)
            if pa:
                pa.prompt_text = refined_text
                pa.version = (pa.version or 1) + 1
                commit_with_retry(session)
                logger.info(
                    "PromptAsset %d prompt 已改写并写回 DB (v%d)",
                    prompt_asset_id,
                    pa.version,
                )
        except Exception as exc:
            session.rollback()
            logger.warning("refine_prompt_with_qa 写回 DB 失败: %s", exc)
        finally:
            session.close()

    return refined_text


def check_brand_consistency(
    image_path: str | None, brand_profile: dict | None = None
) -> float:
    """Score how well the image matches the brand profile (0.0-1.0). Returns 0.5 on degraded mode."""
    if not image_path or not os.path.isfile(image_path):
        return 0.5
    brand_desc = json.dumps(brand_profile) if brand_profile else "{}"
    prompt = (
        "Analyze this product image for brand consistency with the following brand profile. "
        f"Brand profile: {brand_desc}\n\n"
        "Rate the brand consistency from 0.0 to 1.0. "
        'Reply ONLY with JSON: {"brand_score": <float>}'
    )
    raw = _call_gemini(prompt, image_path)
    if not raw:
        return 0.5
    try:
        result = json.loads(raw)
        score = float(result.get("brand_score", 0.5))
        return max(0.0, min(1.0, score))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0.5


def check_text_accuracy(
    image_path: str | None, expected_text: str | None = None
) -> float:
    """Score how accurately text in the image matches expected text (0.0-1.0). Returns 0.5 on degraded mode."""
    if not image_path or not os.path.isfile(image_path):
        return 0.5
    expected_desc = expected_text or ""
    prompt = (
        "Extract any visible text from this product image and compare it to the expected text below. "
        f"Expected text: {expected_desc}\n\n"
        "Rate the text accuracy from 0.0 to 1.0. "
        'Reply ONLY with JSON: {"text_score": <float>}'
    )
    raw = _call_gemini(prompt, image_path)
    if not raw:
        return 0.5
    try:
        result = json.loads(raw)
        score = float(result.get("text_score", 0.5))
        return max(0.0, min(1.0, score))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0.5


def _strip_markdown_fence(text: str) -> str:
    """剥离 LLM 输出中的 markdown 代码块包裹（``` 或 ```json 均处理）。"""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _try_repair_json(text: str) -> dict | None:
    if not text:
        return None

    try:
        import json5  # type: ignore[import]

        result = json5.loads(text)
        if isinstance(result, dict):
            return result
    except Exception as json5_err:
        logger.debug("json5 also failed: %s", json5_err)

    for suffix in ['"}', '"]', '"]}', '"}]', '"}]}', '"]}}', '"}}}']:
        try:
            result = json.loads(text + suffix)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            continue

    for i in range(len(text) - 1, 0, -1):
        if text[i] in ("}", "]"):
            try:
                result = json.loads(text[: i + 1])
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                continue

    # 括号计数补尾：处理 dimensions 对象内部截断（无任何 } 可回溯）
    # 找到最后一个完整的 key:value 对（以逗号或换行结尾），截断残缺部分，再补 }
    last_comma = text.rfind(",")
    if last_comma != -1:
        truncated = text[:last_comma]
        open_braces = truncated.count("{") - truncated.count("}")
        if open_braces > 0:
            closed = truncated + "}" * open_braces
            try:
                result = json.loads(closed)
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

    return None


def _clamp_dimensions(dims: dict, d1_max: int, has_multiangle: bool) -> dict:
    # 各维度满分上限
    _dim_max: dict[str, int] = {
        "A1": 10,
        "A2": 8,
        "A3": 7,
        "B1": 8,
        "B2": 7,
        "C1": 5,
        "C2": 5,
        "C3": 5,
        "C4": 5,
        "C5": 5,
        "D1": d1_max,
        "D2": 7 if has_multiangle else 0,
        "E1": 5,
        "E2": 5,
    }
    return {k: max(0, min(int(v), _dim_max.get(k, int(v)))) for k, v in dims.items()}


def _retryable_llm_qa_failure(issue: str, reasoning: str) -> dict:
    return {
        "pass": False,
        "score": 0,
        "issues": [issue],
        "reasoning": reasoning,
        "dimensions": {},
        "contains_cjk_text": False,
    }


def _normalize_llm_qa_result(
    result: dict,
    d1_max: int,
    has_multiangle: bool,
) -> dict:
    dims_raw = result.get("dimensions", {})
    dims = dict(dims_raw) if isinstance(dims_raw, dict) else {}
    missing_dims = [key for key in _QA_DIMENSION_KEYS if key not in dims]
    if missing_dims:
        logger.warning(
            "LLM QA response missing dimensions %s; returning retryable failure",
            missing_dims,
        )
        return _retryable_llm_qa_failure(
            "LLM QA response incomplete — retry required",
            "LLM response was parsed but did not include all 14 required scoring dimensions; marking QA as failed so orchestrator retry logic can request a complete evaluation",
        )

    clamped = _clamp_dimensions(dims, d1_max, has_multiangle)
    issues = list(result.get("issues", []))
    contains_cjk = bool(result.get("contains_cjk_text", False))
    score = int(result.get("score", 0))
    if contains_cjk:
        issues.append("Amazon US image contains Chinese/CJK or non-English visible text")
        score = min(score, 0)
    return {
        "pass": False if contains_cjk else bool(result.get("pass", False)),
        "score": score,
        "issues": issues,
        "reasoning": str(result.get("reasoning", "")),
        "dimensions": clamped,
        "contains_cjk_text": contains_cjk,
    }


def _normalize_reference_identity_mode(value: str | None) -> str:
    normalized = (value or "strict").strip().lower().replace("-", "_")
    if normalized in {"silhouette", "reference_inspired", "generic", "shape_only"}:
        return "silhouette"
    return "strict"


def _repair_consistency_dimensions(
    image_path: str,
    white_bg_image_path: str | None,
    multiangle_image_paths: list[str] | None,
    intent_tag: str | None,
    d1_max: int,
    has_multiangle: bool,
) -> dict:
    """Run a small focused D1/D2 consistency re-check when full QA JSON is truncated."""
    if not image_path or not os.path.isfile(image_path) or not white_bg_image_path:
        return {}

    prompt = (
        "You are checking ONLY product appearance consistency for an Amazon listing image. "
        "The FIRST image is the generated image. The SECOND image is the real white-background product reference. "
        f"{'Subsequent images are real multi-angle/detail references.' if has_multiangle else ''}\n"
        f"Intent: {intent_tag or 'unknown'}\n"
        "Score D1 and D2 only. D1 checks exact product appearance vs the white-background reference: shape, color, brand logo, earcup/headband/hinge/button/port geometry, and absence of invented parts. "
        "D2 checks whether details match the provided multi-angle/detail references. "
        f"D1 max is {d1_max}. D2 max is {7 if has_multiangle else 0}. "
        "Reply ONLY with valid JSON: {\"D1\": <int>, \"D2\": <int>, \"reasoning\": \"简体中文简短说明\"}"
    )
    ref_paths: list[str] = []
    if white_bg_image_path and os.path.isfile(white_bg_image_path):
        ref_paths.append(white_bg_image_path)
    for path in (multiangle_image_paths or [])[:6]:
        if path and os.path.isfile(path) and path not in ref_paths:
            ref_paths.append(path)

    raw = _call_gemini(prompt, image_path=image_path, image_paths=ref_paths, json_mode=True)
    if not raw:
        return {}
    text = _strip_markdown_fence(raw)
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        repaired = _try_repair_json(text)
        result = repaired if isinstance(repaired, dict) else {}
    if not isinstance(result, dict):
        return {}
    try:
        d1 = int(result.get("D1", 0))
        d2 = int(result.get("D2", 0))
    except (TypeError, ValueError):
        return {}
    clamped = _clamp_dimensions({"D1": d1, "D2": d2}, d1_max, has_multiangle)
    reasoning = result.get("reasoning")
    if reasoning:
        clamped["D_repair_reasoning"] = str(reasoning)
    return clamped


def llm_qa_evaluate(
    image_path: str,
    goal_brief: str = "",
    brand_profile: dict | None = None,
    expected_text: str | None = None,
    white_bg_image_path: str | None = None,
    multiangle_image_paths: list[str] | None = None,
    listing_data: dict | None = None,
    intent_tag: str | None = None,
    extra_reference_image_paths: list[str] | None = None,
    custom_requirements: dict | None = None,
    reference_identity_mode: str = "strict",
) -> dict:
    """Goal-driven LLM QA evaluation using structured 5-group scoring.

    Returns dict with keys: pass (bool), score (int 0-100), issues (list[str]),
    reasoning (str), dimensions (dict). On API failure or incomplete JSON returns a retryable failure.

    Scoring framework (total 100pts):
      A Platform Compliance 25pts | B Technical Quality 15pts | C AI Artifacts 25pts
      D Product Consistency 25pts | E Commercial Quality 10pts
    """
    brand_desc = json.dumps(brand_profile) if brand_profile else "{}"
    listing_desc = (
        json.dumps(listing_data, ensure_ascii=False) if listing_data else "{}"
    )
    has_multiangle = bool(multiangle_image_paths)
    reference_identity_mode = _normalize_reference_identity_mode(reference_identity_mode)
    if reference_identity_mode == "silhouette":
        mode_note = (
            "Reference identity mode: silhouette/material inspiration only. "
            "Use reference images to judge shape, proportions, material family, product category, and color family. "
            "Do NOT penalize differences in brand logos, readable brand text, exact port/button micro-layout, or tiny manufacturing details unless they change the product category or core silhouette."
        )
        d2_note = (
            "D2 (7pts): General cross-angle silhouette/material alignment — exact logo, port, button, and micro-detail matching is NOT required."
            if has_multiangle
            else "D2: No multiangle images provided — D2 score is 0, D1 carries full 25pts."
        )
        d1_label = "Silhouette/material match vs white-bg reference"
        d1_full = "形状/比例/材质类别/颜色家族与参考图高度一致，不要求品牌logo或微细节复刻"
        d1_mid = "整体轮廓可识别但存在轻微比例、材质或颜色家族偏差"
        d1_low = "明显偏离参考轮廓、材质类别或颜色家族"
        d1_zero = "产品类别或核心轮廓与参考图无关"
    else:
        mode_note = (
            "Reference identity mode: strict product facts. "
            "Brand logos, exact colors, port/button positions, packaging/accessory facts, and micro-details must match the references."
        )
        d2_note = (
            "D2 (7pts): Multiangle feature match — shape/details align across provided angle shots."
            if has_multiangle
            else "D2: No multiangle images provided — D2 score is 0, D1 carries full 25pts."
        )
        d1_label = "Appearance match vs white-bg reference"
        d1_full = "形状/颜色/品牌/细节与参考图完全一致"
        d1_mid = "轻微光线角度差或色差整体可识别"
        d1_low = "明显差异（变形/颜色偏差/品牌细节缺失）"
        d1_zero = "严重不符（产品变形或与参考图无关）"
    d1_max = 18 if has_multiangle else 25

    _text_overlay_types = {"INT_INFOGRAPHIC", "INT_COMPARISON", "INT_PACKAGING"}

    if intent_tag in _text_overlay_types:
        # INT_INFOGRAPHIC / INT_COMPARISON / INT_PACKAGING 共用分支
        _a1_rule = (
            "A1 背景适配性 (10pts): "
            "10=背景完全适合图片类型且手机端主文字≥60px渲染高度 | "
            "7-9=背景适合但字号稍小或轻微干扰 | "
            "3-6=背景与图片类型有冲突或字号过小 | "
            "0-2=背景严重不适合或文字完全不可读；"
            "INT_INFOGRAPHIC须确保手机端主要文字字号等效≥30pt（2000px宽图上渲染高度≥60px）"
        )
        _a2_rule = (
            "A2 产品可见度与信息密度 (8pts): "
            "8=产品清晰可见且文字密度<20% | "
            "5-7=产品可见但文字密度接近20%或略高 | "
            "2-4=产品被遮挡或文字密度明显超标 | "
            "0-1=产品几乎不可见或文字密度严重超标；"
            "INT_INFOGRAPHIC/INT_COMPARISON须满足文字密度（文字面积/总面积）<20%（2026年亚马逊新规）"
        )
        _a3_rule = (
            "A3 禁止元素 (7pts): "
            "7=无无关水印或徽标 | "
            "5-6=极少量无关元素不影响主体 | "
            "2-4=明显无关水印或徽标 | "
            "0-1=严重无关覆盖影响整体；有意图的标注说明文字（callout text）可接受"
        )
        _c4_rule = (
            "C4 文字渲染 (4pts): "
            "4=所有文字清晰可读拼写正确 | "
            "3=轻微模糊或个别拼写问题 | "
            "1-2=明显乱码或部分不可读 | "
            "0=文字完全不可读或严重乱码；"
            "INT_INFOGRAPHIC须满足手机端可读性"
        )
    elif intent_tag == "INT_LIFESTYLE":
        # 生活场景图：强调产品使用状态、场景真实性、受众匹配度
        _a1_rule = (
            "A1 场景真实性 (10pts): "
            "10=场景自然真实有生活代入感 | "
            "7-9=场景基本自然但略显精修 | "
            "3-6=场景明显棚拍感缺乏代入感 | "
            "0-2=场景完全虚假或过度精修；"
            "纯白背景在此类型中不应出现且不得作为加分项"
        )
        _a2_rule = (
            "A2 产品使用状态与场景适配 (8pts): "
            "8=产品处于主动使用状态+环境自然真实+模特/场景与目标买家群体完全匹配 | "
            "5-7=三个子维度基本满足但有轻微不足 | "
            "2-4=一个或多个子维度明显不足 | "
            "0-1=产品未处于使用状态或场景与受众严重不符；"
            "①产品须处于主动使用状态 ②环境须真实自然 ③人口特征须与目标买家相符"
        )
        _a3_rule = (
            "A3 禁止元素 (7pts): "
            "7=无无关水印或徽标 | "
            "5-6=极少量无关元素 | "
            "2-4=明显无关水印或徽标 | "
            "0-1=严重无关覆盖；场景中的街道标识、背景招牌等附带自然文字可接受"
        )
        _c4_rule = (
            "C4 文字渲染 (4pts): "
            "4=无促销或说明性文字叠加，场景文字自然 | "
            "3=极少量附带场景文字 | "
            "1-2=有轻微促销或说明性叠加文字 | "
            "0=明显促销文字叠加；场景中附带的自然环境文字（如街道标牌）可接受"
        )
    elif intent_tag == "INT_DETAIL":
        # 细节图：背景支持细节展示，关键细节为主体，无无关水印
        _a1_rule = (
            "A1 背景适配性 (10pts): "
            "10=背景完全支持细节可见性展示无干扰 | "
            "7-9=背景轻微干扰细节呈现 | "
            "3-6=背景明显干扰细节识别 | "
            "0-2=背景严重遮挡或干扰细节；"
            "纯白非必须——中性色或渐变背景均可接受，只要不干扰细节呈现"
        )
        _a2_rule = (
            "A2 主体聚焦 (8pts): "
            "8=关键产品细节占据主导视觉位置且清晰突出 | "
            "5-7=细节可见但不够突出或稍微偏离中心 | "
            "2-4=细节模糊或被其他元素喧宾夺主 | "
            "0-1=细节几乎不可见或完全偏离主题"
        )
        _a3_rule = (
            "A3 禁止元素 (7pts): "
            "7=无无关水印或徽标 | "
            "5-6=极少量无关元素 | "
            "2-4=明显无关水印或徽标 | "
            "0-1=严重无关覆盖；技术标注（callout lines）和材质/功能说明文字可接受"
        )
        _c4_rule = (
            "C4 文字渲染 (4pts): "
            "4=无无关文字叠加，技术标注清晰可读 | "
            "3=标注轻微模糊或拼写问题 | "
            "1-2=标注不可读或有无关文字 | "
            "0=严重乱码或大量无关文字；技术标注、尺寸标注和材质说明等有意为之的文字可接受"
        )
    else:
        # INT_HERO（主图）及默认情况：2026年亚马逊主图新规
        _a1_rule = (
            "A1 背景纯洁度 (10pts): "
            "10=纯白底(#FFFFFF)无任何渐变/阴影/纹理/噪点 | "
            "7-9=近乎白底但有轻微色偏或极淡阴影 | "
            "3-6=非纯白背景有明显纹理或渐变 | "
            "0-2=明显有色或复杂背景；（2026年亚马逊主图新规）"
        )
        _a2_rule = (
            "A2 产品占框比 (8pts): "
            "8=产品占画面面积≥85%且为绝对主体 | "
            "6-7=产品占比80-84%基本满足 | "
            "3-5=产品占比60-79%偏小 | "
            "0-2=产品占比<60%严重不足；（2026年亚马逊主图新规）"
        )
        _a3_rule = (
            "A3 禁止元素 (7pts): "
            "7=无任何文字/水印/徽标/促销图形 | "
            "5-6=极少量图文覆盖(<5%) | "
            "2-4=图文覆盖5-20%明显违规 | "
            "0-1=图文覆盖>20%严重违规；（2026年亚马逊主图新规）"
        )
        _c4_rule = (
            "C4 文字渲染 (4pts): "
            "4=图中无任何可见文字 | "
            "2-3=发现极少量文字但不影响整体 | "
            "1=有明显文字叠加 | "
            "0=存在任何可见文字直接计0分；（2026年主图新规：禁止任何文字）"
        )

    prompt = (
        "重要：issues 和 reasoning 字段必须使用简体中文输出，禁止使用英文。\n\n"
        "You are a strict professional e-commerce image QA evaluator specializing in Amazon/Shopify listing standards.\n"
        "The FIRST image is the GENERATED product image to evaluate.\n"
        f"{'The SECOND image is the white-background product reference.' if white_bg_image_path else ''}"
        f"{'Subsequent images are multi-angle reference shots.' if has_multiangle else ''}\n\n"
        f"Listing Data: {listing_desc}\n"
        f"Goal Brief: {goal_brief}\n"
        f"Brand Profile: {brand_desc}\n"
        f"User Requirements: {json.dumps(custom_requirements or {}, ensure_ascii=False)}\n"
        f"{mode_note}\n\n"
        "Marketplace language policy for Amazon US: visible text must be English only when text is allowed. "
        "If any Chinese/CJK characters or non-English labels are visible in the image, set contains_cjk_text=true and pass=false. "
        "For text-prohibited intents, any visible text should also be penalized under A3/C4.\n\n"
        "Score the generated image using this framework (total = 100pts):\n\n"
        "GROUP A — Platform Compliance (25pts total):\n"
        f"  {_a1_rule}\n"
        f"  {_a2_rule}\n"
        f"  {_a3_rule}\n\n"
        "GROUP B — Technical Quality (15pts total):\n"
        "  B1 Sharpness/focus (8pts): "
        "8=完全清晰无模糊或压缩噪点 | 5-7=轻微模糊/边缘软化主体仍清晰 | 2-4=明显失焦影响主体质量 | 0-1=严重失焦\n"
        "  B2 Exposure & color (7pts): "
        "7=曝光准确色彩自然 | 5-6=轻微过曝/欠曝或轻微色偏 | 2-4=明显曝光问题或色彩偏差 | 0-1=严重过曝/欠曝或色彩严重失真\n\n"
        "GROUP C — AI Artifact Detection (25pts total):\n"
        "  C1 Lighting consistency (5pts): "
        "5=光源单一阴影自然合理 | 3-4=轻微光源不一致 | 1-2=明显矛盾光源/阴影方向混乱 | 0=严重光照混乱\n"
        "  C2 Material realism (5pts): "
        "5=材质真实自然 | 3-4=轻微塑料光泽或合成感 | 1-2=明显人工合成材质 | 0=材质完全不真实\n"
        "  C3 Edge quality (5pts): "
        "5=边缘干净清晰 | 3-4=轻微锯齿/光晕 | 1-2=明显边缘融化/锯齿/描边 | 0=严重边缘问题\n"
        f"  {_c4_rule}\n"
        "  C5 No hallucinated parts (5pts): "
        "5=无幻觉组件与参考完全一致 | 3-4=极少量轻微多余细节 | 1-2=明显多余组件或变形部件 | 0=严重幻觉（完全虚构部件）\n\n"
        "GROUP D — Product Consistency (25pts total, reference image required):\n"
        "  Also check intent-specific references when provided: detail closeups, packaging, accessories, scale, usage-context, and color variants. Penalize invented accessories, colors, packaging claims, or product parts.\n"
        "  Enforce user requirements: must_show items should appear when relevant; must_not_show items must not appear.\n"
        f"  D1 {d1_label} ({d1_max}pts): "
        f"{d1_max}={d1_full} | "
        f"{int(d1_max * 0.72)}-{d1_max - 1}={d1_mid} | "
        f"{int(d1_max * 0.4)}-{int(d1_max * 0.72) - 1}={d1_low} | "
        f"0-{int(d1_max * 0.4) - 1}={d1_zero}\n"
        f"  {d2_note}\n\n"
        "GROUP E — Commercial Quality (10pts total):\n"
        "  E1 Scene plausibility (5pts): "
        "5=比例/重力/尺度完全合理 | 3-4=轻微比例失调但整体可接受 | 1-2=明显物理不合理 | 0=严重违背物理规律\n"
        "  E2 Listing match (5pts): "
        "5=图像与产品标题/卖点/关键词高度一致 | 3-4=基本一致但有轻微偏差 | 1-2=部分对应关系不清晰 | 0=图文严重不符\n\n"
        "Reply ONLY with one-line compact valid JSON. No markdown fences, no line breaks, no indentation.\n"
        "Use exactly this schema with all 14 dimension keys present: "
        '{"pass":true,"score":0,"dimensions":{"A1":0,"A2":0,"A3":0,"B1":0,"B2":0,"C1":0,"C2":0,"C3":0,"C4":0,"C5":0,"D1":0,"D2":0,"E1":0,"E2":0},"contains_cjk_text":false,"issues":["简体中文问题描述"],"reasoning":"简体中文推理摘要"}\n'
        'Set "pass" to true if score >= 70, false otherwise. '
        "score must equal the sum of all dimension scores. "
        "Every dimension value must be an integer. "
        "所有 issues 和 reasoning 必须使用简体中文，不得使用英文。"
    )

    extra_paths: list[str] = []
    if white_bg_image_path and os.path.isfile(white_bg_image_path):
        extra_paths.append(white_bg_image_path)
    if has_multiangle:
        for p in (multiangle_image_paths or [])[:6]:
            if p and os.path.isfile(p):
                extra_paths.append(p)
    for p in (extra_reference_image_paths or [])[:8]:
        if p and os.path.isfile(p) and p not in extra_paths:
            extra_paths.append(p)

    raw = _call_gemini(
        prompt,
        image_path=image_path,
        image_paths=extra_paths if extra_paths else None,
        json_mode=True,
    )
    if not raw:
        logger.warning(
            "LLM QA evaluation failed (empty response); returning retryable failure (score=0)"
        )
        return _retryable_llm_qa_failure(
            "LLM evaluation unavailable — retry required",
            "API call returned empty response; marking QA as failed so orchestrator retry logic can regenerate/evaluate again",
        )

    try:
        text = _strip_markdown_fence(raw)
        result = json.loads(text)
        return _normalize_llm_qa_result(result, d1_max, has_multiangle)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse LLM QA response: %s; raw: %s", exc, raw[:400])
        # 定位 char 116 固定失败点：输出出错位置前后内容
        if hasattr(exc, "pos") and exc.pos is not None:
            start = max(0, exc.pos - 20)
            end = min(len(text), exc.pos + 40)
            logger.debug(
                "JSON parse error at char %d, context: %r", exc.pos, text[start:end]
            )
        repaired = _try_repair_json(text)
        if repaired is not None:
            logger.info("JSON repair succeeded for LLM QA response")
            return _normalize_llm_qa_result(repaired, d1_max, has_multiangle)
        return _retryable_llm_qa_failure(
            "Failed to parse LLM response — retry required",
            str(exc),
        )


def _calibrate_single_image_quality_score(
    *,
    delivery_score: float,
    group_scores: dict[str, float],
    issues: list,
    present_dimensions: int,
    total_dimensions: int,
) -> dict:
    score = max(0.0, min(100.0, float(delivery_score)))
    penalties: list[str] = []
    issue_count = len(issues or [])
    if issue_count:
        penalty = min(12.0, issue_count * 3.0)
        score -= penalty
        penalties.append(f"issues_penalty={penalty:g}")
    if present_dimensions < total_dimensions:
        penalty = min(10.0, (total_dimensions - present_dimensions) * 1.0)
        score -= penalty
        penalties.append(f"incomplete_dimensions_penalty={penalty:g}")
    if group_scores.get("D", 0) and group_scores.get("D", 0) < 22:
        score -= 3.0
        penalties.append("minor_consistency_penalty=3")
    if score >= 99.0 and (issue_count or present_dimensions < total_dimensions):
        score = 94.0
        penalties.append("perfect_score_cap=94")
    return {
        "quality_score": round(max(0.0, min(100.0, score)), 1),
        "quality_score_raw": float(delivery_score),
        "quality_score_calibration": "delivery gate score adjusted for issues, incomplete dimensions, and minor consistency risk",
        "quality_score_penalties": penalties,
    }


def run_qa_checks(slot_plan_id: int) -> list[QARecord]:
    """Goal-driven LLM QA evaluation. Creates a single QARecord with check_name='llm_qa'."""
    session = get_session()
    try:
        slot_plan = session.get(SlotPlan, slot_plan_id)
        if slot_plan is None:
            raise ValueError(f"E_QA_001: SlotPlan with id={slot_plan_id} not found")

        asset = (
            session.query(PromptAsset)
            .filter_by(project_id=slot_plan.project_id, slot_index=slot_plan.slot_index)
            .filter(PromptAsset.image_path.isnot(None))
            .order_by(PromptAsset.id.desc())
            .first()
        )
        if asset is None:
            raise ValueError(
                f"E_QA_001: No generated image found for SlotPlan id={slot_plan_id}"
            )

        image_path = asset.image_path
        if not os.path.isfile(image_path):
            raise ValueError(f"E_QA_001: Image file does not exist: {image_path}")
        slot_project_id = slot_plan.project_id
        slot_index = slot_plan.slot_index
        slot_intent_tag = slot_plan.intent_tag
        slot_tenant_id = getattr(slot_plan, "tenant_id", None)
        slot_angle_tag = _optional_str(getattr(slot_plan, "angle_tag", None))
        slot_generated_angle = _optional_str(getattr(slot_plan, "generated_angle", None))
        asset_id = asset.id
        asset_model_name_raw = getattr(asset, "model_name", None)

        # Load goal brief from ImageBrief if available
        from pipeline.models.image_brief import ImageBrief

        brief = (
            session.query(ImageBrief)
            .filter_by(project_id=slot_project_id, slot_index=slot_index)
            .first()
        )
        goal_brief = brief.brief_json if brief and brief.brief_json else ""

        # Load brand profile from project notes (JSON) if available
        from pipeline.models.project import Project

        project = session.get(Project, slot_project_id)
        brand_profile = None
        if project and project.notes:
            try:
                brand_profile = json.loads(project.notes)
            except (json.JSONDecodeError, TypeError):
                pass

        # 从 customer_brief 提取参考图、用户要求和 listing 数据
        customer_brief: dict = {}
        reference_assets: dict[str, list[str]] = {}
        custom_requirements: dict = {}
        extra_reference_paths: list[str] = []
        if project:
            try:
                from pipeline.layers.custom_requirement_parser import parse_custom_requirements
                from pipeline.layers.project_constraints import enrich_customer_brief, load_customer_brief
                from pipeline.layers.reference_asset_normalizer import normalize_reference_assets
                from pipeline.layers.reference_policy import select_reference_paths

                customer_brief = enrich_customer_brief(load_customer_brief(project))
                reference_assets = normalize_reference_assets(customer_brief)
                custom_requirements = parse_custom_requirements(customer_brief)
                extra_reference_paths = select_reference_paths(
                    reference_assets, slot_intent_tag
                )
            except Exception:
                try:
                    customer_brief = json.loads(project.customer_brief or "{}")
                except (json.JSONDecodeError, TypeError):
                    customer_brief = {}

        reference_identity_mode = _normalize_reference_identity_mode(
            str(
                customer_brief.get(
                    "reference_identity_mode",
                    os.environ.get("QA_REFERENCE_IDENTITY_MODE", "strict"),
                )
            )
        )
        white_bg_list = reference_assets.get("white_bg", [])
        white_bg_image_path = white_bg_list[0] if white_bg_list else customer_brief.get("white_bg_image_path") or None
        multiangle_image_paths = reference_assets.get("multiangle")[:6] or None
        listing_data = {
            k: customer_brief[k]
            for k in ("product_name", "key_selling_points", "asin", "product_category")
            if customer_brief.get(k)
        } or None

        session.close()
        session = None

        llm_result = llm_qa_evaluate(
            image_path=image_path,
            goal_brief=goal_brief,
            brand_profile=brand_profile,
            white_bg_image_path=white_bg_image_path,
            multiangle_image_paths=multiangle_image_paths,
            listing_data=listing_data,
            intent_tag=slot_intent_tag,
            extra_reference_image_paths=extra_reference_paths,
            custom_requirements=custom_requirements,
            reference_identity_mode=reference_identity_mode,
        )

        dims = llm_result.get("dimensions", {})
        group_scores = {
            "A": dims.get("A1", 0) + dims.get("A2", 0) + dims.get("A3", 0),
            "B": dims.get("B1", 0) + dims.get("B2", 0),
            "C": dims.get("C1", 0)
            + dims.get("C2", 0)
            + dims.get("C3", 0)
            + dims.get("C4", 0)
            + dims.get("C5", 0),
            "D": dims.get("D1", 0) + dims.get("D2", 0),
            "E": dims.get("E1", 0) + dims.get("E2", 0),
        }
        # 以各维度加总为权威分值，避免 LLM 自报 score 与 dimensions 不一致
        # 但如果维度不完整（<14个），说明 JSON 截断导致部分维度缺失，
        # 此时回退用 LLM 自报 score，避免被截断的 C/D/E 组拉低总分
        _all_dim_keys = (
            "A1",
            "A2",
            "A3",
            "B1",
            "B2",
            "C1",
            "C2",
            "C3",
            "C4",
            "C5",
            "D1",
            "D2",
            "E1",
            "E2",
        )
        _present_dims = sum(1 for k in _all_dim_keys if k in dims)
        if _present_dims < len(_all_dim_keys):
            logger.warning(
                "LLM QA dimensions incomplete (%d/14 present); using llm_reported score=%s instead of computed=%s",
                _present_dims,
                llm_result["score"],
                sum(group_scores.values()),
            )
            computed_score = float(llm_result["score"])
        else:
            computed_score = float(sum(group_scores.values()))

        try:
            from pipeline.layers.delivery_status import is_product_fact_intent

            _product_fact_required = is_product_fact_intent(slot_intent_tag)
        except Exception:
            _product_fact_required = False
        _d_dims_present = "D1" in dims and "D2" in dims
        _consistency_repair: dict = {}
        if _product_fact_required and not _d_dims_present:
            _consistency_repair = _repair_consistency_dimensions(
                image_path=image_path,
                white_bg_image_path=white_bg_image_path,
                multiangle_image_paths=multiangle_image_paths,
                intent_tag=slot_intent_tag,
                d1_max=18 if multiangle_image_paths else 25,
                has_multiangle=bool(multiangle_image_paths),
            )
            if "D1" in _consistency_repair and "D2" in _consistency_repair:
                dims["D1"] = _consistency_repair["D1"]
                dims["D2"] = _consistency_repair["D2"]
                group_scores["D"] = dims["D1"] + dims["D2"]
                _d_dims_present = True
                if _present_dims < len(_all_dim_keys):
                    computed_score = float(llm_result["score"])
                    if computed_score < 70 and group_scores["D"] >= 18:
                        computed_score = 70.0
        _consistency_issue = None
        consistency_threshold = 10 if reference_identity_mode == "silhouette" else 18
        if _product_fact_required and (not _d_dims_present or group_scores["D"] < consistency_threshold):
            gate_name = "silhouette/material" if reference_identity_mode == "silhouette" else "strict D1/D2"
            _consistency_issue = f"Product-fact image failed {gate_name} consistency gate"
            computed_score = min(computed_score, 59.0)
            llm_result["issues"] = list(llm_result.get("issues", [])) + [_consistency_issue]

        _quality = _calibrate_single_image_quality_score(
            delivery_score=computed_score,
            group_scores=group_scores,
            issues=llm_result.get("issues", []),
            present_dimensions=_present_dims,
            total_dimensions=len(_all_dim_keys),
        )
        _qa_details = {
            **group_scores,
            **_quality,
            "A1": dims.get("A1", 0),
            "A2": dims.get("A2", 0),
            "A3": dims.get("A3", 0),
            "B1": dims.get("B1", 0),
            "B2": dims.get("B2", 0),
            "C1": dims.get("C1", 0),
            "C2": dims.get("C2", 0),
            "C3": dims.get("C3", 0),
            "C4": dims.get("C4", 0),
            "C5": dims.get("C5", 0),
            "D1": dims.get("D1", 0),
            "D2": dims.get("D2", 0),
            "E1": dims.get("E1", 0),
            "E2": dims.get("E2", 0),
            "issues": llm_result["issues"],
            "reasoning": llm_result["reasoning"],
            "contains_cjk_text": bool(llm_result.get("contains_cjk_text", False)),
            "reference_identity_mode": reference_identity_mode,
        }
        if _consistency_repair:
            _qa_details["consistency_repair"] = _consistency_repair
        try:
            from pipeline.layers.reference_asset_normalizer import _dedupe
            from pipeline.layers.reference_policy import select_reference_paths

            _ref_paths = _dedupe(extra_reference_paths or [])
            _product_fact_ref_paths = _dedupe(
                (multiangle_image_paths or [])
                + select_reference_paths(
                    reference_assets,
                    slot_intent_tag,
                    product_fact_only=True,
                )
            )
            _layout_ref_paths = [p for p in _ref_paths if p not in _product_fact_ref_paths]
        except Exception:
            _ref_paths = list(extra_reference_paths or [])
            _product_fact_ref_paths = list(multiangle_image_paths or []) + _ref_paths
            _layout_ref_paths = []
        _target_angle = slot_angle_tag
        _actual_angle = slot_generated_angle
        _angle_matches_target = None
        if _target_angle and _actual_angle:
            try:
                from pipeline.layers.visual_quality_reviewer import angles_match_target

                _angle_matches_target = angles_match_target(_target_angle, _actual_angle)
            except Exception:
                _angle_matches_target = _target_angle.lower() == _actual_angle.lower()
        _qa_details.update(
            {
                "target_angle": _target_angle,
                "actual_angle": _actual_angle,
                "angle_matches_target": _angle_matches_target,
            }
        )
        try:
            from pipeline.layers.visual_quality_reviewer import build_visual_quality_review

            _qa_details["visual_quality"] = build_visual_quality_review(
                qa_details=_qa_details,
                intent_tag=slot_intent_tag,
                target_angle=_target_angle,
                actual_angle=_actual_angle,
            )
        except Exception as _vq_exc:
            logger.warning("visual quality review failed for asset %s: %s", asset.id, _vq_exc)
        try:
            from pipeline.layers.delivery_status import listing_delivery_metadata, merge_visual_tags

            session = get_session()
            asset = (
                session.query(PromptAsset)
                .filter_by(id=asset_id)
                .order_by(PromptAsset.id.desc())
                .first()
            )
            if asset is None:
                asset = (
                    session.query(PromptAsset)
                    .filter_by(project_id=slot_project_id, slot_index=slot_index)
                    .filter(PromptAsset.image_path.isnot(None))
                    .order_by(PromptAsset.id.desc())
                    .first()
                )
            if asset is None:
                raise ValueError(f"E_QA_001: Asset disappeared for SlotPlan id={slot_plan_id}")
            slot_plan_for_record = slot_plan
            _model_name = asset_model_name_raw if isinstance(asset_model_name_raw, str) else None
            _delivery = listing_delivery_metadata(
                passed=computed_score >= 70,
                score=computed_score,
                qa_details=_qa_details,
                intent_tag=slot_intent_tag,
                reference_paths=_ref_paths,
                model_name=_model_name,
                product_fact_reference_paths=_product_fact_ref_paths,
                layout_reference_paths=_layout_ref_paths,
                reference_identity_mode=reference_identity_mode,
                target_angle=_target_angle,
                actual_angle=_actual_angle,
                angle_matches_target=_angle_matches_target,
            )
            _qa_details.update(_delivery)
            asset.status = _delivery["delivery_status"]
            _visual_metadata = {**_delivery, "visual_quality": _qa_details.get("visual_quality")}
            asset.visual_tags = merge_visual_tags(asset.visual_tags, _visual_metadata)
        except Exception as _delivery_exc:
            logger.warning("delivery status classification failed for asset %s: %s", asset.id, _delivery_exc)
        rec = QARecord(
            prompt_asset_id=asset.id,
            check_type="llm_qa",
            passed=1 if computed_score >= 70 else 0,
            score=computed_score,
            details=json.dumps(_qa_details, ensure_ascii=False),
            tenant_id=slot_tenant_id,
        )
        session.add(rec)
        session.flush()
        try:
            from pipeline.layers.flywheel_observation import record_listing_qa_observation

            record_listing_qa_observation(session, asset, rec, slot_plan_for_record)
        except Exception as _obs_exc:
            logger.warning("flywheel observation write failed for asset %s: %s", asset.id, _obs_exc)
        commit_with_retry(session)
        session.refresh(rec)
        session.expunge_all()
        logger.info(
            "LLM QA for SlotPlan %d: score=%.1f (llm_reported=%s), passed=%s",
            slot_plan_id,
            computed_score,
            llm_result["score"],
            rec.passed,
        )
        return [rec]
    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()


def run_qa_checks_legacy(slot_plan_id: int) -> list[QARecord]:
    session = get_session()
    try:
        slot_plan = session.get(SlotPlan, slot_plan_id)
        if slot_plan is None:
            raise ValueError(f"E_QA_001: SlotPlan with id={slot_plan_id} not found")

        asset = (
            session.query(PromptAsset)
            .filter_by(project_id=slot_plan.project_id, slot_index=slot_plan.slot_index)
            .filter(PromptAsset.image_path.isnot(None))
            .order_by(PromptAsset.id.desc())
            .first()
        )
        if asset is None:
            raise ValueError(
                f"E_QA_001: No generated image found for SlotPlan id={slot_plan_id}"
            )

        image_path = asset.image_path
        if not os.path.isfile(image_path):
            raise ValueError(f"E_QA_001: Image file does not exist: {image_path}")

        checks: list[tuple[str, bool, str]] = []

        res_ok = check_resolution(image_path)
        checks.append(
            (
                "resolution",
                res_ok,
                "long side >= 1600px" if res_ok else "long side < 1600px",
            )
        )

        ar_ok = check_aspect_ratio(image_path)
        checks.append(
            ("aspect_ratio", ar_ok, "matches 1:1" if ar_ok else "does not match 1:1")
        )

        bg_score = check_background(image_path)
        bg_ok = bg_score >= 0.5
        checks.append(("background", bg_ok, f"white_ratio={bg_score:.2f}"))

        size_score = check_image_size(image_path)
        size_ok = size_score >= 0.5
        checks.append(("image_size", size_ok, f"size_score={size_score:.2f}"))

        text_found = check_text_overlay(image_path)
        text_ok = not text_found
        checks.append(
            (
                "text_overlay",
                text_ok,
                "no text detected" if text_ok else "text detected",
            )
        )

        brand_score = check_brand_consistency(image_path)
        brand_ok = brand_score >= 0.5
        checks.append(("brand_consistency", brand_ok, f"brand_score={brand_score:.2f}"))

        text_score = check_text_accuracy(image_path)
        text_acc_ok = text_score >= 0.5
        checks.append(("text_accuracy", text_acc_ok, f"text_score={text_score:.2f}"))

        records: list[QARecord] = []
        total_score = 0.0
        pts_per_check = 100.0 / len(checks) if checks else 0.0
        for check_name, passed, details in checks:
            pts = pts_per_check if passed else 0.0
            total_score += pts
            rec = QARecord(
                prompt_asset_id=asset.id,
                check_type=check_name,
                passed=1 if passed else 0,
                score=pts,
                details=details,
                tenant_id=getattr(slot_plan, "tenant_id", None),
            )
            session.add(rec)
            records.append(rec)

        logger.info(
            "QA for SlotPlan %d: score=%.0f/100, passed=%s",
            slot_plan_id,
            total_score,
            total_score >= 70,
        )
        session.commit()
        for rec in records:
            session.refresh(rec)
        session.expunge_all()
        return records
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# QA Gate – 5 Hard Doors
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_MIN_DIM = 1000
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def check_compliance(project_id: int, image_path: str) -> dict:
    """Gate 1: file format, dimensions >=1000x1000, size <=10 MB."""
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return {
            "status": "FAIL",
            "gate": "compliance",
            "details": f"Bad format {ext}; allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        }
    try:
        size = os.path.getsize(image_path)
    except OSError as exc:
        return {"status": "FAIL", "gate": "compliance", "details": str(exc)}
    if size > _MAX_FILE_SIZE:
        return {
            "status": "FAIL",
            "gate": "compliance",
            "details": f"File {size} bytes exceeds 10 MB",
        }
    try:
        with Image.open(image_path) as img:
            w, h = img.size
    except Exception as exc:
        return {"status": "FAIL", "gate": "compliance", "details": str(exc)}
    if w < _MIN_DIM or h < _MIN_DIM:
        return {
            "status": "FAIL",
            "gate": "compliance",
            "details": f"Dimensions {w}x{h} below {_MIN_DIM}x{_MIN_DIM}",
        }
    return {"status": "PASS", "gate": "compliance", "details": "OK"}


def check_visual_anchor(project_id: int, image_path: str) -> dict:
    """Gate 2: basic visual anchor check (image opens and is not degenerate)."""
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            if w == 0 or h == 0:
                return {
                    "status": "FAIL",
                    "gate": "visual_anchor",
                    "details": "Degenerate image dimensions",
                }
        return {"status": "PASS", "gate": "visual_anchor", "details": "OK"}
    except Exception as exc:
        return {"status": "FAIL", "gate": "visual_anchor", "details": str(exc)}


def check_reference_chain(project_id: int, image_path: str) -> dict:
    """Gate 3: ReferencePack must exist for the project."""
    from pipeline.models.reference_pack import ReferencePack

    session = get_session()
    try:
        rp = session.query(ReferencePack).filter_by(project_id=project_id).first()
        if rp is None:
            return {
                "status": "FAIL",
                "gate": "reference_chain",
                "details": f"No ReferencePack for project {project_id}",
            }
        return {"status": "PASS", "gate": "reference_chain", "details": "OK"}
    finally:
        session.close()


def check_consistency(project_id: int, image_path: str) -> dict:
    """Gate 4: ConsistencyProfile must exist and be fully populated."""
    from pipeline.layers.consistency_system import validate_consistency

    try:
        ok, missing = validate_consistency(project_id)
    except Exception as exc:
        return {"status": "FAIL", "gate": "consistency", "details": str(exc)}
    if not ok:
        return {
            "status": "FAIL",
            "gate": "consistency",
            "details": f"Missing fields: {missing}",
        }
    return {"status": "PASS", "gate": "consistency", "details": "OK"}


def compute_gate5_score(
    tag_layers: list[str] | None = None,
    brand_profile: dict | None = None,
    image_tags: list[str] | None = None,
    width: int | None = None,
    height: int | None = None,
) -> tuple[float, dict]:
    """Gate 5 LLM 评分公式。

    score = 0.4 * tag_coverage_norm + 0.4 * brand_consistency + 0.2 * resolution_pass

    - tag_coverage_norm: 已有标签层数 / 5（5层: INTENT/ROLE/COLOR/LAYOUT/STYLE）
    - brand_consistency: brand_profile 与 image_tags 匹配度，无数据时默认 0.5
    - resolution_pass: 分辨率 ≥ 1024x1024 则 1.0，否则 0.0；无数据时默认 1.0

    返回 (score, details_dict)。
    """
    # --- tag_coverage_norm ---
    _ALL_LAYERS = {"INTENT", "ROLE", "COLOR", "LAYOUT", "STYLE"}
    if tag_layers:
        present = {t.upper() for t in tag_layers} & _ALL_LAYERS
        tag_coverage_norm = len(present) / 5.0
    else:
        tag_coverage_norm = 0.0

    # --- brand_consistency ---
    if brand_profile and image_tags:
        # 计算 brand_profile 中颜色/风格关键词与 image_tags 的重叠度
        brand_keywords: set[str] = set()
        for v in brand_profile.values():
            if isinstance(v, str):
                brand_keywords.update(w.lower() for w in v.split())
            elif isinstance(v, list):
                for item in v:
                    brand_keywords.update(w.lower() for w in str(item).split())
        if brand_keywords:
            img_kw = {t.lower() for t in image_tags}
            matches = len(brand_keywords & img_kw)
            brand_consistency = min(1.0, matches / len(brand_keywords))
        else:
            brand_consistency = 0.5
    else:
        brand_consistency = 0.5

    # --- resolution_pass ---
    if width is not None and height is not None:
        resolution_pass = 1.0 if (width >= 1024 and height >= 1024) else 0.0
    else:
        resolution_pass = 1.0

    score = 0.4 * tag_coverage_norm + 0.4 * brand_consistency + 0.2 * resolution_pass
    details = {
        "tag_coverage_norm": round(tag_coverage_norm, 4),
        "brand_consistency": round(brand_consistency, 4),
        "resolution_pass": resolution_pass,
        "score": round(score, 4),
    }
    return score, details


def _collect_gate5_inputs(project_id: int, image_path: str) -> dict:
    """从数据库收集 Gate 5 所需的输入数据。"""
    from pipeline.models.tag_assignment import TagAssignment
    from pipeline.models.project import Project

    session = get_session()
    try:
        # 收集标签层
        tags = (
            session.query(TagAssignment)
            .filter_by(entity_type="project", entity_id=project_id)
            .all()
        )
        tag_layers = list({t.tag_layer for t in tags}) if tags else None
        image_tags = [t.tag_code for t in tags] if tags else None

        # 收集 brand_profile
        project = session.get(Project, project_id)
        brand_profile = None
        if project and project.notes:
            try:
                brand_profile = json.loads(project.notes)
            except (json.JSONDecodeError, TypeError):
                pass

        # 收集分辨率
        width, height = None, None
        if image_path and os.path.isfile(image_path):
            try:
                w, h = _read_image_dimensions(image_path)
                width, height = w, h
            except Exception:
                logger.warning("Failed to read image dimensions", exc_info=True)

        return {
            "tag_layers": tag_layers,
            "brand_profile": brand_profile,
            "image_tags": image_tags,
            "width": width,
            "height": height,
        }
    finally:
        session.close()


def run_qa_gate(project_id: int, image_path: str) -> dict:
    """Run all 5 QA gates. Any FAIL -> overall FAIL."""
    gate_1 = check_compliance(project_id, image_path)
    gate_2 = check_visual_anchor(project_id, image_path)
    gate_3 = check_reference_chain(project_id, image_path)
    gate_4 = check_consistency(project_id, image_path)

    # Gate 5: LLM 评分公式
    try:
        inputs = _collect_gate5_inputs(project_id, image_path)
        score, details = compute_gate5_score(**inputs)
        status = "PASS" if score >= 0.6 else "FAIL"
        gate_5 = {"status": status, "gate": "llm_qa", "details": details}
    except Exception as exc:
        logger.error("Gate 5 评估异常，降级为 PASS: %s", exc)
        gate_5 = {
            "status": "PASS",
            "gate": "llm_qa",
            "details": f"评估异常（降级）: {exc}",
        }

    gates = {
        "gate_1": gate_1,
        "gate_2": gate_2,
        "gate_3": gate_3,
        "gate_4": gate_4,
        "gate_5": gate_5,
    }
    overall = "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL"
    return {"overall": overall, **gates}


_REQUIRED_SET_INTENTS = {
    "INT_HERO": "缺少主图图位",
    "INT_LIFESTYLE": "缺少生活方式图位",
    "INT_DETAIL": "缺少细节图位",
    "INT_INFOGRAPHIC": "缺少信息图位",
    "INT_PACKAGING": "缺少包装/配件图位",
}


def evaluate_set_intent_structure(slot_summaries: list[dict]) -> dict:
    intents = [str(slot.get("intent") or "") for slot in slot_summaries]
    intent_counts = {intent: intents.count(intent) for intent in set(intents)}
    issues = [message for intent, message in _REQUIRED_SET_INTENTS.items() if intent_counts.get(intent, 0) == 0]

    if intent_counts.get("INT_PACKAGING", 0) > 1:
        issues.append("包装/配件图位过多，配件内容可能污染套图")
    if intent_counts.get("INT_HERO", 0) > 2:
        issues.append("主图/封面图位过多，套图叙事重复")
    if intent_counts.get("INT_LIFESTYLE", 0) > 2 and intent_counts.get("INT_DETAIL", 0) == 0:
        issues.append("生活方式图重复但缺少细节图位")

    return {
        "passed": not issues,
        "issues": issues,
        "intent_counts": intent_counts,
    }


def _calibrate_series_scores(
    raw_scores: dict[str, int], issues: list, suggestions: list
) -> dict[str, int]:
    scores = {key: max(0, min(100, int(raw_scores.get(key, 0) or 0))) for key in ("S1", "S2", "S3", "S4", "S5")}
    text = " ".join(str(item).lower() for item in [*issues, *suggestions])
    category_terms = {
        "S1": ("color", "temperature", "色温", "白平衡", "warm", "cool"),
        "S2": ("lighting", "light", "shadow", "曝光", "光照", "光线"),
        "S3": ("shot type", "close-up", "medium shot", "macro", "构图类型", "景别", "中景", "近景"),
        "S4": ("angle", "diversity", "3/4", "角度", "多样"),
        "S5": ("narrative", "complete", "coverage", "missing", "story", "叙事", "完整", "缺少"),
    }
    for key, terms in category_terms.items():
        if any(term in text for term in terms):
            scores[key] = min(scores[key], 94)
    if issues or suggestions:
        for key, value in list(scores.items()):
            if value == 100:
                scores[key] = 98
    return scores


def run_series_qa(project_id: int) -> dict:
    with get_session() as session:
        plans = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.slot_index)
            .all()
        )
        generated = [
            p
            for p in plans
            if getattr(p, "generated_lighting", None)
            or getattr(p, "generated_angle", None)
        ]

    if len(generated) < 2:
        return {"skipped": True, "reason": "generated slots < 2", "total": None}

    slot_summaries = [
        {
            "slot": p.slot_index,
            "intent": p.intent_tag or "",
            "lighting": getattr(p, "generated_lighting", None) or "",
            "angle": getattr(p, "generated_angle", None) or "",
            "shot_type": getattr(p, "generated_shot_type", None) or "",
            "color_temp": getattr(p, "generated_color_temp", None) or "",
            "saturation": getattr(p, "generated_saturation", None) or "",
            "bg_material": getattr(p, "generated_bg_material", None) or "",
        }
        for p in generated
    ]

    structure_result = evaluate_set_intent_structure(slot_summaries)
    if not structure_result["passed"]:
        return {
            "skipped": False,
            "total": 0,
            "S1": None,
            "S2": None,
            "S3": None,
            "S4": None,
            "S5": 0,
            "issues": structure_result["issues"],
            "suggestions": ["调整图位规划，确保主图、生活方式、细节、信息图、包装/配件图位都有明确分工"],
            "generated_slots": len(generated),
            "intent_structure": structure_result,
        }

    if not config.openai_api_key:
        return {"skipped": True, "reason": "no LLM API key", "total": None, "intent_structure": structure_result}

    slots_compact = json.dumps(
        slot_summaries, ensure_ascii=False, separators=(",", ":")
    )
    prompt = (
        f"QA reviewer for e-commerce photography. Evaluate {len(slot_summaries)} shots.\n"
        f"Data:{slots_compact}\n"
        "Score 0-100 each: S1=color_temp_consistency,S2=lighting_consistency,"
        "S3=shot_type_coherence,S4=angle_diversity,S5=narrative_completeness.\n"
        "Use calibrated scoring: 95-100 only for exceptional consistency with no visible minor issue; "
        "85-94 strong but with small imperfections; 70-84 acceptable; 50-69 weak; <50 fail. "
        "Never output 100 for any category if there is any issue or suggestion touching that category.\n"
        # 要求紧凑单行 JSON，避免思考 token 过多导致输出被截断
        'Output ONLY compact JSON no spaces: {"S1":N,"S2":N,"S3":N,"S4":N,"S5":N,"issues":[],"suggestions":[]}'
    )

    endpoint = f"{config.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.openai_model or "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        # gemini-2.5-flash 使用思考 token，需要足够大的 max_tokens 保证输出不被截断
        "max_tokens": 8192,
        "temperature": 0.2,
    }

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # 去掉 LLM 可能返回的 markdown 代码围栏
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("run_series_qa LLM call failed: %s", exc)
        return {"skipped": True, "reason": str(exc), "total": None}

    raw_scores = {k: int(data.get(k, 0) or 0) for k in ("S1", "S2", "S3", "S4", "S5")}
    issues = data.get("issues", []) or []
    suggestions = data.get("suggestions", []) or []
    calibrated_scores = _calibrate_series_scores(raw_scores, issues, suggestions)
    scores = [calibrated_scores[k] for k in ("S1", "S2", "S3", "S4", "S5")]
    total = round(sum(scores) / len(scores))
    angle_diversity_risk = calibrated_scores.get("S4", 100) < 70

    return {
        "skipped": False,
        "total": total,
        "S1": calibrated_scores.get("S1"),
        "S2": calibrated_scores.get("S2"),
        "S3": calibrated_scores.get("S3"),
        "S4": calibrated_scores.get("S4"),
        "S5": calibrated_scores.get("S5"),
        "angle_diversity_risk": angle_diversity_risk,
        "raw_scores": raw_scores,
        "score_calibration": "100 requires no visible minor issue; issue-linked categories are capped below 100",
        "issues": issues,
        "suggestions": suggestions,
        "generated_slots": len(generated),
    }
