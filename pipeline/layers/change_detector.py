from __future__ import annotations

import hashlib
import os

from sqlalchemy.orm import Session

from pipeline.models.image_snapshot import ImageSnapshot


def capture_snapshot(
    session: Session,
    project_id: int,
    asin: str,
    image_url: str,
    slot_position: int,
    tenant_id: int = None,
) -> ImageSnapshot:
    """Read image from local path or URL, compute sha256, store snapshot."""
    if os.path.isfile(image_url):
        with open(image_url, "rb") as f:
            data = f.read()
    else:
        import urllib.request

        with urllib.request.urlopen(image_url) as resp:
            data = resp.read()

    image_hash = hashlib.sha256(data).hexdigest()

    snap = ImageSnapshot(
        project_id=project_id,
        asin=asin,
        image_url=image_url,
        image_hash=image_hash,
        slot_position=slot_position,
        tenant_id=tenant_id,
    )
    session.add(snap)
    session.commit()
    session.refresh(snap)
    return snap


def detect_changes(session: Session, project_id: int, asin: str) -> list[dict]:
    """Compare latest two snapshots per slot_position, return changed slots."""
    snapshots = (
        session.query(ImageSnapshot)
        .filter_by(project_id=project_id, asin=asin)
        .order_by(ImageSnapshot.slot_position, ImageSnapshot.captured_at.desc())
        .all()
    )

    by_slot: dict[int, list[ImageSnapshot]] = {}
    for s in snapshots:
        by_slot.setdefault(s.slot_position, []).append(s)

    changes = []
    for slot_pos in sorted(by_slot):
        records = by_slot[slot_pos]
        if len(records) < 2:
            continue
        newest, previous = records[0], records[1]
        if newest.image_hash != previous.image_hash:
            changes.append(
                {
                    "slot_position": slot_pos,
                    "old_hash": previous.image_hash,
                    "new_hash": newest.image_hash,
                }
            )

    return changes


def get_change_history(
    session: Session, project_id: int, asin: str
) -> list[ImageSnapshot]:
    """Return all snapshots for a project+asin ordered by time."""
    return (
        session.query(ImageSnapshot)
        .filter_by(project_id=project_id, asin=asin)
        .order_by(ImageSnapshot.captured_at.desc())
        .all()
    )
