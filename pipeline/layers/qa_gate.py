from __future__ import annotations

import base64
import json
import os
import struct

import httpx

from pipeline.config import config
from pipeline.models.base import get_session
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.slot_plan import SlotPlan
from pipeline.utils.logger import setup_logger

__all__ = [
    "run_qa_checks",
    "check_resolution",
    "check_aspect_ratio",
    "check_background",
    "check_text_overlay",
]

logger = setup_logger("aip.qa_gate")

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _read_png_dimensions(image_path: str) -> tuple[int, int]:
    with open(image_path, "rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE:
        raise ValueError(f"Not a valid PNG file: {image_path}")
    width = struct.unpack(">I", header[16:20])[0]
    height = struct.unpack(">I", header[20:24])[0]
    return width, height


def check_resolution(image_path: str) -> bool:
    w, h = _read_png_dimensions(image_path)
    long_side = max(w, h)
    logger.debug("Resolution %dx%d, long side %d", w, h, long_side)
    return long_side >= 1600


def check_aspect_ratio(image_path: str, expected: str = "1:1") -> bool:
    w, h = _read_png_dimensions(image_path)
    parts = expected.split(":")
    exp_w, exp_h = int(parts[0]), int(parts[1])
    expected_ratio = exp_w / exp_h
    actual_ratio = w / h if h > 0 else 0
    tolerance = 0.05
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
                            "url": f"data:image/png;base64,{img_b64}",
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


def run_qa_checks(slot_plan_id: int) -> list[QARecord]:
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
        bg_ok = bg_score >= 0.8
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

        records: list[QARecord] = []
        total_score = 0.0
        for check_name, passed, details in checks:
            pts = 25.0 if passed else 0.0
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
