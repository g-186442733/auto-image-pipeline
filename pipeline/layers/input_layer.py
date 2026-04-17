"""Input layer: project creation and brand profile upsert."""

import re

from pipeline.models.base import get_session
from pipeline.models.project import Project
from pipeline.models.brand import BrandProfile
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.input_layer")

__all__ = ["create_project", "upsert_brand_profile"]

ASIN_PATTERN = re.compile(r"^B[0-9A-Z]{9}$")


def create_project(brief: dict) -> Project:
    """Create new project.

    brief must contain: name (str), asin (str), category (str). Optional: notes (str).
    Returns Project with status="draft".
    Raises ValueError("E_INPUT_001: ...") if missing required fields.
    Raises ValueError("E_INPUT_002: ...") if ASIN format invalid (must match r'^B[0-9A-Z]{9}$').
    """
    required_fields = ("name", "asin", "category")
    missing = [f for f in required_fields if f not in brief or brief[f] is None]
    if missing:
        raise ValueError(f"E_INPUT_001: Missing required fields: {', '.join(missing)}")

    asin = brief["asin"]
    if not ASIN_PATTERN.match(asin):
        raise ValueError(
            f"E_INPUT_002: Invalid ASIN format '{asin}'. Must match r'^B0[A-Z0-9]{{8}}$'."
        )

    session = get_session()
    try:
        project = Project(
            name=brief["name"],
            asin=asin,
            category=brief["category"],
            status="draft",
            notes=brief.get("notes"),
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        logger.info(
            "Created project id=%s name=%s asin=%s",
            project.id,
            project.name,
            project.asin,
        )
        return project
    finally:
        session.close()


def upsert_brand_profile(data: dict) -> BrandProfile:
    """Create or update brand profile.

    data must contain: project_id (int), brand_name (str).
    Optional: color_palette, font_family, tone, logo_path, guidelines.
    If brand profile exists for project_id, update it. Otherwise create new.
    Raises ValueError("E_INPUT_003: ...") if project_id not found.
    """
    project_id = data.get("project_id")
    brand_name = data.get("brand_name")

    session = get_session()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"E_INPUT_003: project_id={project_id} not found.")

        profile = (
            session.query(BrandProfile)
            .filter(BrandProfile.project_id == project_id)
            .first()
        )

        optional_fields = (
            "color_palette",
            "font_family",
            "tone",
            "logo_path",
            "guidelines",
        )

        if profile is not None:
            if brand_name is not None:
                profile.brand_name = brand_name
            for field in optional_fields:
                if field in data:
                    setattr(profile, field, data[field])
            logger.info(
                "Updated BrandProfile id=%s project_id=%s", profile.id, project_id
            )
        else:
            profile = BrandProfile(
                project_id=project_id,
                brand_name=brand_name,
                **{f: data[f] for f in optional_fields if f in data},
            )
            session.add(profile)
            logger.info("Created BrandProfile project_id=%s", project_id)

        session.commit()
        session.refresh(profile)
        return profile
    finally:
        session.close()
