import re
from typing import Optional

from pipeline.models.base import get_session
from pipeline.models.project import Project
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.product_profile import ProductProfile
from pipeline.models.intake_checklist import IntakeChecklist
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.input_layer")

__all__ = ["create_project", "upsert_brand_profile", "get_intake_checklist"]

ASIN_PATTERN = re.compile(r"^B[0-9A-Z]{9}$")

INTAKE_CHECKLIST_FIELDS = (
    "product_photos",
    "brand_guide",
    "competitor_asins",
    "platform_requirements",
)


def create_project(brief: dict, intake_checklist: Optional[dict] = None) -> Project:
    required_fields = ("name", "category")
    missing = [f for f in required_fields if f not in brief or brief[f] is None]
    if missing:
        raise ValueError(f"E_INPUT_001: Missing required fields: {', '.join(missing)}")

    asin = brief.get("asin") or ""
    if asin and not ASIN_PATTERN.match(asin):
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
        session.flush()

        if intake_checklist is not None:
            checklist = IntakeChecklist(
                project_id=project.id,
                **{f: intake_checklist.get(f) for f in INTAKE_CHECKLIST_FIELDS},
            )
            session.add(checklist)
            logger.info("Created IntakeChecklist project_id=%s", project.id)

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
    project_id = data.get("project_id")

    session = get_session()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"E_INPUT_003: project_id={project_id} not found.")

        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        profile = None
        if pp and pp.brand_profile_id:
            profile = (
                session.query(BrandProfile).filter_by(id=pp.brand_profile_id).first()
            )

        optional_fields = (
            "brand_tone",
            "color_system",
            "font_preference",
            "photo_style",
            "model_type",
            "scene_preference",
            "composition_preference",
            "material_texture",
            "competitor_positioning",
            "brand_story",
            "messaging_pillars",
            "guidelines",
            "customer_profile_id",
        )

        if profile is not None:
            for field in optional_fields:
                if field in data:
                    setattr(profile, field, data[field])
            logger.info(
                "Updated BrandProfile id=%s project_id=%s", profile.id, project_id
            )
        else:
            profile = BrandProfile(
                **{f: data[f] for f in optional_fields if f in data},
            )
            session.add(profile)
            session.flush()

            from pipeline.layers.cold_start import warm_start_brand_profile

            warm_start_brand_profile(profile, project.category or "", session)

            if pp is None:
                pp = ProductProfile(
                    project_id=project_id, brand_profile_id=profile.id, tenant_id=1
                )
                session.add(pp)
            else:
                pp.brand_profile_id = profile.id
            logger.info("Created BrandProfile project_id=%s", project_id)

        session.commit()
        session.refresh(profile)
        return profile
    finally:
        session.close()


def get_intake_checklist(project_id: int) -> Optional[IntakeChecklist]:
    session = get_session()
    try:
        return (
            session.query(IntakeChecklist)
            .filter(IntakeChecklist.project_id == project_id)
            .first()
        )
    finally:
        session.close()
