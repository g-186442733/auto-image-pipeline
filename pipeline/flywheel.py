"""全自动飞轮 — 基于置信度的自动交付触发器"""

from __future__ import annotations

from typing import Callable

from pipeline.config import Config
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.flywheel")


def run_flywheel(
    project_id: str,
    session,
    config: Config | None = None,
    qa_score: float | None = None,
    qa_score_fn: Callable[[], float] | None = None,
) -> dict:
    if config is None:
        from pipeline.config import config as _default_config

        config = _default_config

    if not config.flywheel_enabled:
        return {"skipped": True, "reason": "disabled"}

    if qa_score is None and qa_score_fn is not None:
        qa_score = qa_score_fn()
    if qa_score is None:
        return {"skipped": True, "reason": "no_score"}

    if qa_score < config.flywheel_confidence_threshold:
        return {"auto_delivered": False, "score": qa_score, "reason": "below_threshold"}

    if not config.flywheel_auto_deliver:
        return {
            "auto_delivered": False,
            "score": qa_score,
            "reason": "auto_deliver_disabled",
        }

    max_version = (
        session.query(DeliveryVersion.version_number)
        .filter(DeliveryVersion.project_id == project_id)
        .order_by(DeliveryVersion.version_number.desc())
        .first()
    )
    next_version = (max_version[0] + 1) if max_version else 1

    dv = DeliveryVersion(
        project_id=project_id,
        version_number=next_version,
        trigger="flywheel",
        auto_delivered=True,
        change_summary=f"auto-delivered at score {qa_score}",
    )
    session.add(dv)
    session.commit()

    logger.info(
        "飞轮自动交付 project %s version %d (score=%.1f)",
        project_id,
        next_version,
        qa_score,
    )
    return {"auto_delivered": True, "score": qa_score, "version": next_version}


def check_flywheel_status(config: Config | None = None) -> dict:
    if config is None:
        from pipeline.config import config as _default_config

        config = _default_config

    return {
        "enabled": config.flywheel_enabled,
        "auto_deliver": config.flywheel_auto_deliver,
        "confidence_threshold": config.flywheel_confidence_threshold,
    }
