from __future__ import annotations

import json
import os
import shutil

from sqlalchemy.orm import Session

from pipeline.models.delivery_version import DeliveryVersion

__all__ = [
    "create_version",
    "get_version_history",
    "get_version_diff",
    "rollback_version",
]


def _list_files(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    result = []
    for root, _dirs, files in os.walk(directory):
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), directory)
            result.append(rel)
    return sorted(result)


def create_version(
    session: Session,
    project_id: int,
    trigger: str,
    change_summary: str,
    output_dir: str = "output",
) -> DeliveryVersion:
    current_max = (
        session.query(DeliveryVersion.version_number)
        .filter_by(project_id=project_id)
        .order_by(DeliveryVersion.version_number.desc())
        .first()
    )
    version_number = (current_max[0] + 1) if current_max else 1

    project_dir = os.path.join(output_dir, str(project_id))
    version_dir = os.path.join(project_dir, "versions", f"v{version_number}")

    file_list: list[str] = []
    if os.path.isdir(project_dir):
        os.makedirs(version_dir, exist_ok=True)
        for item in os.listdir(project_dir):
            if item == "versions":
                continue
            src = os.path.join(project_dir, item)
            dst = os.path.join(version_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        file_list = _list_files(version_dir)

    dv = DeliveryVersion(
        project_id=project_id,
        version_number=version_number,
        trigger=trigger,
        change_summary=change_summary,
        file_manifest=json.dumps(file_list),
    )
    session.add(dv)
    session.commit()
    session.refresh(dv)
    return dv


def get_version_history(session: Session, project_id: int) -> list[DeliveryVersion]:
    return (
        session.query(DeliveryVersion)
        .filter_by(project_id=project_id)
        .order_by(DeliveryVersion.version_number.asc())
        .all()
    )


def get_version_diff(
    session: Session, project_id: int, v1: int, v2: int
) -> dict[str, list[str]]:
    dv1 = (
        session.query(DeliveryVersion)
        .filter_by(project_id=project_id, version_number=v1)
        .first()
    )
    dv2 = (
        session.query(DeliveryVersion)
        .filter_by(project_id=project_id, version_number=v2)
        .first()
    )
    files1 = set(json.loads(dv1.file_manifest)) if dv1 else set()
    files2 = set(json.loads(dv2.file_manifest)) if dv2 else set()

    return {
        "added": sorted(files2 - files1),
        "removed": sorted(files1 - files2),
        "modified": [],
    }


def rollback_version(
    session: Session,
    project_id: int,
    target_version: int,
    output_dir: str = "output",
) -> bool:
    project_dir = os.path.join(output_dir, str(project_id))
    version_dir = os.path.join(project_dir, "versions", f"v{target_version}")

    if not os.path.isdir(version_dir):
        return False

    for item in os.listdir(project_dir):
        if item == "versions":
            continue
        path = os.path.join(project_dir, item)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    for item in os.listdir(version_dir):
        src = os.path.join(version_dir, item)
        dst = os.path.join(project_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    return True
