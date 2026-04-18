from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.models.base import get_session
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord

__all__ = ["build_delivery_package"]


def build_delivery_package(project_id: int, session: Optional[Session] = None) -> str:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        delivery_dir = os.path.join("output", str(project_id), "delivery")
        os.makedirs(delivery_dir, exist_ok=True)

        assets = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == project_id)
            .order_by(PromptAsset.slot_index)
            .all()
        )

        manifest_slots = []
        for asset in assets:
            qa_records = (
                session.query(QARecord)
                .filter(QARecord.prompt_asset_id == asset.id)
                .all()
            )
            scored = [r.score for r in qa_records if r.score is not None]
            if scored and sum(scored) < 70:
                continue

            if not asset.image_path or not os.path.exists(asset.image_path):
                continue

            dest = os.path.join(delivery_dir, f"slot_{asset.slot_index}.png")
            shutil.copy2(asset.image_path, dest)
            manifest_slots.append(
                {
                    "slot_index": asset.slot_index,
                    "image_path": dest,
                    "qa_status": "passed",
                }
            )

        manifest = {
            "project_id": project_id,
            "slots": manifest_slots,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = os.path.join(delivery_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return delivery_dir
    finally:
        if owns_session:
            session.close()
