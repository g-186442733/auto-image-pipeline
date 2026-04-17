"""
Prompt asset CRUD + template seeding for the auto-image-pipeline.
"""

import json
import os
from pipeline.models.base import get_session
from pipeline.models.project import Project
from pipeline.models.prompt_asset import PromptAsset
from pipeline.config import config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.prompt_manager")

__all__ = [
    "create_prompt_asset",
    "update_prompt_asset",
    "get_prompt_asset",
    "list_prompt_assets",
    "seed_default_templates",
]


def create_prompt_asset(
    project_id: int,
    slot_index: int,
    prompt_text: str,
    negative_prompt: str = "",
    model_name: str = "flux-1.1-pro",
) -> PromptAsset:
    """Create new prompt asset.
    Raises ValueError("E_PROMPT_001: ...") if project_id not found.
    Raises ValueError("E_PROMPT_002: ...") if slot_index not in 1-8.
    """
    if slot_index < 1 or slot_index > 8:
        raise ValueError(
            f"E_PROMPT_002: slot_index must be between 1 and 8, got {slot_index}"
        )

    with get_session() as session:
        # project_id=0 is a sentinel for templates without a real project
        if project_id != 0:
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"E_PROMPT_001: project_id {project_id} not found")

        asset = PromptAsset(
            project_id=project_id,
            slot_index=slot_index,
            prompt_text=prompt_text,
            negative_prompt=negative_prompt,
            model_name=model_name,
            version=1,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        logger.info(
            "Created PromptAsset id=%s project_id=%s slot=%s",
            asset.id,
            project_id,
            slot_index,
        )
        return asset


def update_prompt_asset(asset_id: int, **kwargs) -> PromptAsset:
    """Update existing prompt asset. Auto-increment version.
    Updatable fields: prompt_text, negative_prompt, model_name.
    Raises ValueError("E_PROMPT_003: ...") if asset_id not found.
    """
    allowed_fields = {"prompt_text", "negative_prompt", "model_name"}

    with get_session() as session:
        asset = session.get(PromptAsset, asset_id)
        if asset is None:
            raise ValueError(f"E_PROMPT_003: asset_id {asset_id} not found")

        updated = False
        for field, value in kwargs.items():
            if field in allowed_fields:
                setattr(asset, field, value)
                updated = True
            else:
                logger.warning(
                    "update_prompt_asset: ignoring unknown field '%s'", field
                )

        if updated:
            asset.version = (asset.version or 1) + 1

        session.commit()
        session.refresh(asset)
        logger.info("Updated PromptAsset id=%s new_version=%s", asset.id, asset.version)
        return asset


def get_prompt_asset(id_or_name, version=None) -> PromptAsset:
    """Get prompt asset by ID (int) or project name (str).
    If version is None, return latest version.
    Raises ValueError("E_PROMPT_003: ...") if not found.
    """
    with get_session() as session:
        if isinstance(id_or_name, int):
            if version is not None:
                asset = (
                    session.query(PromptAsset)
                    .filter(
                        PromptAsset.id == id_or_name,
                        PromptAsset.version == version,
                    )
                    .first()
                )
            else:
                asset = session.get(PromptAsset, id_or_name)

            if asset is None:
                raise ValueError(
                    f"E_PROMPT_003: PromptAsset with id {id_or_name}"
                    + (f" version {version}" if version is not None else "")
                    + " not found"
                )
            return asset

        elif isinstance(id_or_name, str):
            project = session.query(Project).filter(Project.name == id_or_name).first()
            if project is None:
                raise ValueError(
                    f"E_PROMPT_003: Project with name '{id_or_name}' not found"
                )

            query = session.query(PromptAsset).filter(
                PromptAsset.project_id == project.id
            )

            if version is not None:
                query = query.filter(PromptAsset.version == version)
            else:
                query = query.order_by(PromptAsset.version.desc())

            asset = query.first()
            if asset is None:
                raise ValueError(
                    f"E_PROMPT_003: PromptAsset for project '{id_or_name}'"
                    + (f" version {version}" if version is not None else "")
                    + " not found"
                )
            return asset

        else:
            raise ValueError(
                "E_PROMPT_003: id_or_name must be int (asset id) or str (project name)"
            )


def list_prompt_assets(category=None) -> list:
    """List prompt assets. If category provided, filter by project category."""
    with get_session() as session:
        if category is not None:
            assets = (
                session.query(PromptAsset)
                .join(Project, PromptAsset.project_id == Project.id)
                .filter(Project.category == category)
                .all()
            )
        else:
            assets = session.query(PromptAsset).all()

        logger.debug(
            "list_prompt_assets(category=%s) returned %d records",
            category,
            len(assets),
        )
        return assets


def seed_default_templates() -> int:
    """Load default templates from config.templates_dir (JSON files) into DB.
    Each JSON file should have: project_id (optional, default 0), slot_index,
    prompt_text, negative_prompt, model_name.
    Returns count of imported templates.
    If templates_dir doesn't exist or is empty, return 0 (no error).
    """
    templates_dir = getattr(config, "templates_dir", "templates")

    if not os.path.isdir(templates_dir):
        logger.info(
            "seed_default_templates: templates_dir '%s' does not exist, skipping",
            templates_dir,
        )
        return 0

    json_files = [f for f in os.listdir(templates_dir) if f.endswith(".json")]

    if not json_files:
        logger.info(
            "seed_default_templates: no JSON files found in '%s'", templates_dir
        )
        return 0

    count = 0
    for filename in json_files:
        filepath = os.path.join(templates_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            project_id = data.get("project_id", 0)
            slot_index = data["slot_index"]
            prompt_text = data["prompt_text"]
            negative_prompt = data.get("negative_prompt", "")
            model_name = data.get("model_name", "flux-1.1-pro")

            create_prompt_asset(
                project_id=project_id,
                slot_index=slot_index,
                prompt_text=prompt_text,
                negative_prompt=negative_prompt,
                model_name=model_name,
            )
            count += 1
            logger.info("Seeded template from '%s'", filename)

        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "seed_default_templates: skipping '%s' due to error: %s",
                filename,
                exc,
            )

    logger.info("seed_default_templates: imported %d template(s)", count)
    return count
