from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from PIL import Image as PILImage
from sqlalchemy.orm import Session

from pipeline.models.base import get_session
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord

__all__ = [
    "build_delivery_package",
    "generate_preview_html",
    "generate_delivery_notes",
    "generate_version_log",
    "generate_spec_check",
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def _find_images(project_dir: str) -> list[str]:
    result = []
    for subdir in ("assets", ""):
        d = os.path.join(project_dir, subdir) if subdir else project_dir
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                result.append(os.path.join(d, fname))
    return result


def generate_preview_html(project_id: int, output_dir: str) -> str:
    project_dir = os.path.join(output_dir, str(project_id))
    delivery_dir = os.path.join(project_dir, "delivery")
    os.makedirs(delivery_dir, exist_ok=True)

    images = _find_images(project_dir)

    rows = []
    for img_path in images:
        fname = os.path.basename(img_path)
        try:
            with PILImage.open(img_path) as im:
                w, h = im.size
                fmt = im.format or os.path.splitext(fname)[1].upper().lstrip(".")
        except Exception:
            w, h, fmt = "?", "?", "?"
        rows.append(
            f'<tr><td><img src="../assets/{fname}" width="120"></td>'
            f"<td>{fname}</td><td>{w}x{h}</td><td>{fmt}</td></tr>"
        )

    html = (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>\n"
        "<title>Preview List</title>\n"
        '<link rel="stylesheet" href="../../../pipeline/web/static/style.css">\n'
        "</head><body>\n<h1>Image Preview</h1>\n"
        "<table><thead><tr><th>Preview</th><th>File</th><th>Size</th><th>Format</th></tr></thead>\n"
        "<tbody>\n" + "\n".join(rows) + "\n</tbody></table>\n</body></html>"
    )

    out_path = os.path.join(delivery_dir, "preview_list.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def generate_delivery_notes(
    project_id: int, output_dir: str, *, session: Optional[Session] = None
) -> str:
    delivery_dir = os.path.join(output_dir, str(project_id), "delivery")
    os.makedirs(delivery_dir, exist_ok=True)

    owns = session is None
    if owns:
        session = get_session()
    try:
        from pipeline.models.project import Project

        project = session.get(Project, project_id)
        name = project.name if project else f"Project {project_id}"
        asin = getattr(project, "asin", "") or ""
        category = getattr(project, "category", "") or ""
        notes = getattr(project, "notes", "") or ""
        brief = getattr(project, "customer_brief", "") or ""
    finally:
        if owns:
            session.close()

    md = (
        f"# Delivery Notes — {name}\n\n"
        f"- **Project ID**: {project_id}\n"
        f"- **ASIN**: {asin}\n"
        f"- **Category**: {category}\n\n"
        f"## Customer Brief\n\n{brief}\n\n"
        f"## Notes\n\n{notes}\n\n"
        f"## Generated\n\n{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )

    out_path = os.path.join(delivery_dir, "delivery_notes.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return out_path


def generate_version_log(
    project_id: int, output_dir: str, *, session: Optional[Session] = None
) -> str:
    delivery_dir = os.path.join(output_dir, str(project_id), "delivery")
    os.makedirs(delivery_dir, exist_ok=True)

    owns = session is None
    if owns:
        session = get_session()
    try:
        from pipeline.models.slot_plan import SlotPlan

        plans = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.created_at)
            .all()
        )
    finally:
        if owns:
            session.close()

    entries = []
    for p in plans:
        entries.append(
            {
                "type": "slot_plan",
                "slot_index": p.slot_index,
                "intent": p.intent_tag,
                "created_at": str(p.created_at) if p.created_at else None,
            }
        )
    data = {
        "project_id": project_id,
        "entries": entries,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = os.path.join(delivery_dir, "version_log.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return out_path


def generate_spec_check(project_id: int, output_dir: str) -> str:
    project_dir = os.path.join(output_dir, str(project_id))
    delivery_dir = os.path.join(project_dir, "delivery")
    os.makedirs(delivery_dir, exist_ok=True)

    images = _find_images(project_dir)
    specs = []
    for img_path in images:
        try:
            with PILImage.open(img_path) as im:
                w, h = im.size
                fmt = im.format or os.path.splitext(img_path)[1].upper().lstrip(".")
        except Exception:
            w, h, fmt = 0, 0, "unknown"
        specs.append(
            {
                "file": img_path,
                "width": w,
                "height": h,
                "format": fmt,
                "filesize_bytes": os.path.getsize(img_path),
            }
        )

    out_path = os.path.join(delivery_dir, "spec_check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(specs, f, indent=2)
    return out_path


def build_delivery_package(
    project_id: int,
    session: Optional[Session] = None,
    output_dir: str = "output",
) -> str:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        delivery_dir = os.path.join(output_dir, str(project_id), "delivery")
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

        generate_preview_html(project_id, output_dir)
        generate_delivery_notes(project_id, output_dir, session=session)
        generate_version_log(project_id, output_dir, session=session)
        generate_spec_check(project_id, output_dir)

        try:
            from pipeline.layers.version_manager import create_version

            create_version(session, project_id, "initial", "first delivery", output_dir)
        except Exception:
            pass

        return delivery_dir
    finally:
        if owns_session:
            session.close()
