import csv
import json
import threading
from typing import Optional

from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.ab_attribution")

CTR_WEIGHT = 0.6
CVR_WEIGHT = 0.4
RECOMMEND_THRESHOLD = 0.06

REQUIRED_FIELDS = {"prompt_asset_id", "ctr", "cvr"}


def import_performance_data(file_path: str, format: str = "csv") -> list[dict]:
    if format == "json":
        with open(file_path, "r") as f:
            data = json.load(f)
        for row in data:
            _validate_row(row)
            row["prompt_asset_id"] = int(row["prompt_asset_id"])
            row["ctr"] = float(row["ctr"])
            row["cvr"] = float(row["cvr"])
        return data

    with open(file_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        data = []
        for row in reader:
            _validate_row(row)
            data.append(
                {
                    "prompt_asset_id": int(row["prompt_asset_id"]),
                    "ctr": float(row["ctr"]),
                    "cvr": float(row["cvr"]),
                }
            )
    return data


def _validate_row(row: dict) -> None:
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise ValueError(f"缺少必要字段: {missing}")


def calculate_performance_score(ctr: float, cvr: float) -> float:
    return CTR_WEIGHT * ctr + CVR_WEIGHT * cvr


def apply_attribution(session, data: list[dict]) -> int:
    from pipeline.models.prompt_asset import PromptAsset
    from pipeline.layers.knowledge_base import promote_to_knowledge
    from sqlalchemy import text

    count = 0
    # 收集本次归因中被飞轮写入的 brand_profile_id，用于提交后触发重算
    updated_brand_ids: set[int] = set()

    for row in data:
        asset_id = row["prompt_asset_id"]
        asset = session.get(PromptAsset, asset_id)
        if asset is None:
            continue
        score = calculate_performance_score(row["ctr"], row["cvr"])
        is_rec = score >= RECOMMEND_THRESHOLD
        session.execute(
            text(
                "UPDATE prompt_assets SET performance_score = :score, "
                "is_recommended = :rec, ab_ctr = :ctr, ab_cvr = :cvr WHERE id = :id"
            ),
            {
                "score": score,
                "rec": is_rec,
                "ctr": row["ctr"],
                "cvr": row["cvr"],
                "id": asset_id,
            },
        )
        try:
            from pipeline.layers.flywheel_observation import record_ab_performance_observation

            record_ab_performance_observation(
                session,
                asset,
                ctr=row["ctr"],
                cvr=row["cvr"],
                performance_score=score,
            )
        except Exception as exc:
            logger.warning("AB performance observation failed for asset=%s: %s", asset_id, exc)
        if is_rec:
            session.refresh(asset)
            promote_to_knowledge(asset, session)
            brand_id = _flywheel_update_brand(asset, score, session)
            if brand_id is not None:
                updated_brand_ids.add(brand_id)
        count += 1

    session.commit()

    # 提交完成后，异步触发受影响 project 的 SlotPlan 重算
    # 此时 ELASTIC 字段已落库，regen_single_slot 能读到最新值
    for brand_id in updated_brand_ids:
        _trigger_flywheel_regen(brand_id)

    return count


def _flywheel_update_brand(asset, score: float, session) -> Optional[int]:
    import json
    from pipeline.models.product_profile import ProductProfile
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.layers.drift_detector import flywheel_update_with_drift_check
    from pipeline.utils.logger import setup_logger

    logger = setup_logger("aip.ab_attribution")

    if not asset.visual_tags:
        return None

    try:
        tags: dict = json.loads(asset.visual_tags)
    except Exception:
        return None

    elastic_updates: dict[str, str] = {
        k: v for k, v in tags.items() if isinstance(v, str)
    }
    if not elastic_updates:
        return None

    pp = session.query(ProductProfile).filter_by(project_id=asset.project_id).first()
    if not pp or not pp.brand_profile_id:
        return None

    brand = session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
    if brand is None:
        return None

    try:
        from pipeline.models.slot_plan import SlotPlan

        slot_plan = (
            session.query(SlotPlan)
            .filter_by(project_id=asset.project_id, slot_index=asset.slot_index)
            .first()
        )
        intent_tag = slot_plan.intent_tag if slot_plan else None

        applied = flywheel_update_with_drift_check(
            brand, elastic_updates, score, session, intent_tag=intent_tag
        )

        top_tags = ", ".join(f"{k}={v}" for k, v in elastic_updates.items())
        brand.ab_conclusions = f"score={score:.3f} tags=[{top_tags}]"

        logger.info(
            "飞轮回写 BrandProfile id=%s fields=%s score=%.3f",
            brand.id,
            list(elastic_updates.keys()),
            score,
        )

        return brand.id if applied else None

    except Exception as exc:
        logger.warning("飞轮回写失败 BrandProfile id=%s: %s", brand.id, exc)
        return None


def _trigger_flywheel_regen(brand_profile_id: int) -> None:
    def _regen_worker() -> None:
        from pipeline.models.base import get_session
        from pipeline.models.product_profile import ProductProfile
        from pipeline.models.project import Project
        from pipeline.models.slot_plan import SlotPlan
        from pipeline.layers.slot_planner import regen_single_slot
        from pipeline.utils.logger import setup_logger

        logger = setup_logger("aip.ab_attribution")
        session = get_session()
        try:
            # 查询该 brand_profile_id 下所有已完成的 project
            project_ids = (
                session.query(ProductProfile.project_id)
                .join(Project, Project.id == ProductProfile.project_id)
                .filter(
                    ProductProfile.brand_profile_id == brand_profile_id,
                    Project.status == "completed",
                )
                .all()
            )
            project_ids = [row[0] for row in project_ids if row[0] is not None]

            for pid in project_ids:
                slot_indices = (
                    session.query(SlotPlan.slot_index)
                    .filter_by(project_id=pid)
                    .distinct()
                    .all()
                )
                for (sidx,) in slot_indices:
                    try:
                        regen_single_slot(pid, sidx, session=session)
                        logger.info(
                            "飞轮触发 SlotPlan 重算 project_id=%s slot_index=%s brand_id=%s",
                            pid,
                            sidx,
                            brand_profile_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "飞轮 SlotPlan 重算失败 project_id=%s slot_index=%s: %s",
                            pid,
                            sidx,
                            exc,
                        )
            session.commit()
        except Exception as exc:
            logger.warning(
                "飞轮重算 worker 异常 brand_id=%s: %s", brand_profile_id, exc
            )
        finally:
            session.close()

    thread = threading.Thread(
        target=_regen_worker,
        daemon=True,
        name=f"flywheel-regen-{brand_profile_id}",
    )
    thread.start()
