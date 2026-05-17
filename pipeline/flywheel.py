"""飞轮闭环：好图写回 PromptAsset + FlywheelExample，下轮生成时作为样本参考。"""

from __future__ import annotations

from pipeline.config import Config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.flywheel")

_QA_NORM_DIVISOR = 20.0
_FLYWHEEL_THRESHOLD_COLD = 3.5
_FLYWHEEL_THRESHOLD_WARM = 4.0
_FLYWHEEL_WARM_SAMPLE_COUNT = 30


def run_flywheel(
    project_id: int,
    session,
    config: Config | None = None,
    tenant_id: int | None = None,
) -> dict:
    if config is None:
        from pipeline.config import config as _default_config

        config = _default_config

    if not config.flywheel_enabled:
        return {"skipped": True, "reason": "disabled"}

    from pipeline.models.prompt_asset import PromptAsset
    from pipeline.models.qa_record import QARecord
    from pipeline.models.human_image_score import HumanImageScore
    from pipeline.models.flywheel_example import FlywheelExample
    from pipeline.models.product_profile import ProductProfile
    from pipeline.layers.flywheel_observation import (
        copy_visual_tags_to_flywheel_asset,
        record_listing_qa_observation,
        slot_label,
    )
    from pipeline.models.slot_plan import SlotPlan

    pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
    product_category = pp.product_category if pp else None

    if product_category:
        category_sample_count = (
            session.query(FlywheelExample)
            .filter(FlywheelExample.product_category == product_category)
            .count()
        )
    else:
        category_sample_count = session.query(FlywheelExample).count()

    threshold = (
        _FLYWHEEL_THRESHOLD_WARM
        if category_sample_count >= _FLYWHEEL_WARM_SAMPLE_COUNT
        else _FLYWHEEL_THRESHOLD_COLD
    )
    logger.info(
        "飞轮阈值 project=%d category=%s samples=%d threshold=%.1f",
        project_id,
        product_category,
        category_sample_count,
        threshold,
    )

    assets = (
        session.query(PromptAsset)
        .filter(PromptAsset.project_id == project_id)
        .filter((PromptAsset.source.is_(None)) | (PromptAsset.source != "flywheel"))
        .all()
    )

    archived = 0
    skipped = 0

    for asset in assets:
        qa_rec = (
            session.query(QARecord)
            .filter(
                QARecord.prompt_asset_id == asset.id,
                QARecord.passed == 1,
            )
            .first()
        )
        if qa_rec is None:
            skipped += 1
            continue

        qa_score_raw = qa_rec.score if qa_rec.score is not None else 0.0
        qa_norm = qa_score_raw / _QA_NORM_DIVISOR

        human_rec = (
            session.query(HumanImageScore)
            .filter(HumanImageScore.prompt_asset_id == asset.id)
            .first()
        )
        if human_rec is not None:
            if human_rec.overall_score is not None:
                avg_human = float(human_rec.overall_score)
            else:
                avg_human = (
                    (human_rec.score_fidelity or 0.0) * 0.30
                    + (human_rec.score_lighting or 0.0) * 0.25
                    + (human_rec.score_composition or 0.0) * 0.20
                    + (human_rec.score_material or 0.0) * 0.15
                    + (human_rec.score_commercial or 0.0) * 0.10
                )
            combined = (qa_norm + avg_human) / 2.0
        else:
            combined = qa_norm

        if combined < threshold:
            skipped += 1
            continue

        slot_type = slot_label(asset.slot_index) or str(asset.slot_index)
        slot_plan = (
            session.query(SlotPlan)
            .filter_by(project_id=project_id, slot_index=asset.slot_index)
            .first()
        )
        try:
            record_listing_qa_observation(session, asset, qa_rec, slot_plan)
        except Exception as obs_exc:
            logger.warning(
                "飞轮 observation 写入失败 project=%d asset=%d: %s",
                project_id,
                asset.id,
                obs_exc,
            )

        existing_asset = (
            session.query(PromptAsset)
            .filter(
                PromptAsset.project_id == project_id,
                PromptAsset.slot_type == slot_type,
                PromptAsset.prompt_text == asset.prompt_text,
                PromptAsset.source == "flywheel",
            )
            .first()
        )
        if existing_asset is None:
            flywheel_asset = PromptAsset(
                project_id=project_id,
                slot_index=-1,
                prompt_text=asset.prompt_text,
                negative_prompt=asset.negative_prompt,
                model_name=asset.model_name,
                slot_type=slot_type,
                source="flywheel",
                tenant_id=tenant_id,
            )
            copy_visual_tags_to_flywheel_asset(asset, flywheel_asset)
            session.add(flywheel_asset)
            session.flush()
            flywheel_asset_id = flywheel_asset.id
        else:
            flywheel_asset_id = existing_asset.id

        existing_example = (
            session.query(FlywheelExample)
            .filter(FlywheelExample.prompt_asset_id == asset.id)
            .first()
        )
        if existing_example is None:
            example = FlywheelExample(
                prompt_asset_id=asset.id,
                project_id=project_id,
                slot_index=asset.slot_index,
                slot_type=slot_type,
                prompt_text=asset.prompt_text,
                human_score=avg_human if human_rec is not None else None,
                qa_score=qa_norm,
                combined_score=combined,
                tenant_id=tenant_id,
            )
            session.add(example)

        if human_rec is not None and not human_rec.entered_flywheel:
            human_rec.entered_flywheel = True

        archived += 1
        logger.info(
            "飞轮归档 project=%d asset=%d slot_type=%s combined=%.2f",
            project_id,
            asset.id,
            slot_type,
            combined,
        )

    session.commit()
    logger.info(
        "飞轮完成 project=%d archived=%d skipped=%d", project_id, archived, skipped
    )
    return {"archived": archived, "skipped": skipped}


def check_flywheel_status(config: Config | None = None) -> dict:
    if config is None:
        from pipeline.config import config as _default_config

        config = _default_config

    return {
        "enabled": config.flywheel_enabled,
        "auto_deliver": config.flywheel_auto_deliver,
        "confidence_threshold": config.flywheel_confidence_threshold,
    }
