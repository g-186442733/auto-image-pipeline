from __future__ import annotations

import base64
import json
import os

import httpx
from PIL import Image

from pipeline.config import config
from pipeline.models.base import get_session
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
    "check_text_overlay",
    "check_brand_consistency",
    "check_text_accuracy",
    "check_compliance",
    "check_visual_anchor",
    "check_reference_chain",
    "check_consistency",
    "compute_gate5_score",
]

logger = setup_logger("aip.qa_gate")

_MIN_DIMENSION = 500


def _read_image_dimensions(image_path: str) -> tuple[int, int]:
    with Image.open(image_path) as img:
        return img.size


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


def check_background(image_path: str) -> float:
    size = os.path.getsize(image_path)
    if size < 1024:
        return 0.95
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


_GEMINI_MODEL = "gemini-2.0-flash"


def _get_genai():
    import google.generativeai as genai

    return genai


def _call_gemini(prompt: str, image_path: str | None = None) -> str:
    """Call Gemini with optional image. Returns raw text or empty string on failure."""
    import base64

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return ""
    try:
        genai = _get_genai()
    except ImportError:
        return ""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(_GEMINI_MODEL)
        parts: list = [{"text": prompt}]
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                img_data = f.read()
            parts.append(
                {
                    "inline_data": {
                        "mime_type": _get_mime_type(image_path),
                        "data": base64.b64encode(img_data).decode("utf-8"),
                    }
                }
            )
        response = model.generate_content(parts)
        # Safely access text: check candidates exist and aren't blocked
        if not response.candidates:
            logger.warning("Gemini returned no candidates (possibly blocked)")
            return ""
        return response.text
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return ""


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


def llm_qa_evaluate(
    image_path: str,
    goal_brief: str = "",
    brand_profile: dict | None = None,
    expected_text: str | None = None,
) -> dict:
    """Goal-driven LLM QA evaluation using Gemini.

    Returns dict with keys: pass (bool), score (int 0-100), issues (list[str]), reasoning (str).
    On API failure returns a safe default (fail with score=0).
    """
    brand_desc = json.dumps(brand_profile) if brand_profile else "{}"
    expected_desc = expected_text or "(none)"

    prompt = (
        "You are a strict e-commerce image QA evaluator. Evaluate this product image against the goal brief.\n\n"
        f"**Goal Brief:** {goal_brief}\n"
        f"**Brand Profile:** {brand_desc}\n"
        f"**Expected Text:** {expected_desc}\n\n"
        "Score the image from 0-100 on overall quality, brand consistency, composition, and goal alignment.\n"
        "List any issues found.\n\n"
        "Reply ONLY with valid JSON:\n"
        '{"pass": true/false, "score": <int 0-100>, "issues": ["issue1", ...], "reasoning": "..."}\n'
        'Set "pass" to true if score >= 70, false otherwise.'
    )
    raw = _call_gemini(prompt, image_path)
    if not raw:
        logger.warning(
            "LLM QA evaluation failed (empty response); returning safe default"
        )
        return {
            "pass": False,
            "score": 0,
            "issues": ["LLM evaluation unavailable"],
            "reasoning": "API call returned empty response",
        }

    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
        return {
            "pass": bool(result.get("pass", False)),
            "score": int(result.get("score", 0)),
            "issues": list(result.get("issues", [])),
            "reasoning": str(result.get("reasoning", "")),
        }
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse LLM QA response: %s; raw: %s", exc, raw[:200])
        return {
            "pass": False,
            "score": 0,
            "issues": ["Failed to parse LLM response"],
            "reasoning": str(exc),
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

        # Load goal brief from ImageBrief if available
        from pipeline.models.image_brief import ImageBrief

        brief = (
            session.query(ImageBrief)
            .filter_by(project_id=slot_plan.project_id, slot_index=slot_plan.slot_index)
            .first()
        )
        goal_brief = brief.brief_json if brief and brief.brief_json else ""

        # Load brand profile from project notes (JSON) if available
        from pipeline.models.project import Project

        project = session.get(Project, slot_plan.project_id)
        brand_profile = None
        if project and project.notes:
            try:
                brand_profile = json.loads(project.notes)
            except (json.JSONDecodeError, TypeError):
                pass

        llm_result = llm_qa_evaluate(
            image_path=image_path,
            goal_brief=goal_brief,
            brand_profile=brand_profile,
        )

        rec = QARecord(
            prompt_asset_id=asset.id,
            check_type="llm_qa",
            passed=1 if llm_result["pass"] else 0,
            score=float(llm_result["score"]),
            details=json.dumps(
                {"issues": llm_result["issues"], "reasoning": llm_result["reasoning"]}
            ),
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)
        session.expunge_all()
        logger.info(
            "LLM QA for SlotPlan %d: score=%d, passed=%s",
            slot_plan_id,
            llm_result["score"],
            llm_result["pass"],
        )
        return [rec]
    except Exception:
        session.rollback()
        raise
    finally:
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
        logger.warning("Gate 5 evaluation failed: %s", exc)
        gate_5 = {"status": "PASS", "gate": "llm_qa", "details": f"Error: {exc}"}

    gates = {
        "gate_1": gate_1,
        "gate_2": gate_2,
        "gate_3": gate_3,
        "gate_4": gate_4,
        "gate_5": gate_5,
    }
    overall = "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL"
    return {"overall": overall, **gates}
