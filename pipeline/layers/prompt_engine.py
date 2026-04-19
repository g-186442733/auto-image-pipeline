"""Prompt assembly engine — combines PromptAsset templates with variables."""

from __future__ import annotations

from jinja2 import Environment, BaseLoader, TemplateSyntaxError

import json
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.constants.tags import SLOT_MAPPING
from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.image_brief import ImageBrief
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.slot_plan import SlotPlan
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.prompt_engine")

__all__ = ["assemble_prompt", "build_prompt", "generate_slot_prompts"]

REQUIRED_VARIABLE_KEYS = frozenset(
    ["composition", "subject", "environment", "camera", "tone", "constraints"]
)

_jinja_env = Environment(loader=BaseLoader())


def assemble_prompt(
    prompt_asset_id: int,
    variables: dict,
    brand_profile: BrandProfile | None = None,
    reference_pack: dict | None = None,
) -> str:
    """Assemble a final prompt string.

    Renders PromptAsset.prompt_text as a Jinja2 template with *variables*,
    appends brand constraints (if provided), then appends negative_prompt.

    Six-dimension variable skeleton (variables dict keys):
        composition, subject, environment, camera, tone, constraints

    Raises:
        ValueError E_PROMPT_003 — prompt_asset_id not found
        ValueError E_ENGINE_001 — variables missing required keys
    """
    missing = REQUIRED_VARIABLE_KEYS - set(variables)
    if missing:
        raise ValueError(
            f"E_ENGINE_001: variables missing required keys: {sorted(missing)}"
        )

    with get_session() as session:
        asset = session.get(PromptAsset, prompt_asset_id)
        if asset is None:
            raise ValueError(
                f"E_PROMPT_003: prompt_asset_id {prompt_asset_id} not found"
            )

        try:
            template = _jinja_env.from_string(asset.prompt_text)
            rendered = template.render(**variables)
        except TemplateSyntaxError:
            logger.warning(
                "Jinja2 syntax error in PromptAsset %s, falling back to raw text",
                prompt_asset_id,
            )
            rendered = asset.prompt_text

        parts = [rendered.strip()]

        if brand_profile is not None:
            brand_parts: list[str] = []
            if brand_profile.brand_tone:
                brand_parts.append(f"Brand tone: {brand_profile.brand_tone}")
            if brand_profile.color_system:
                brand_parts.append(f"Brand colors: {brand_profile.color_system}")
            if brand_profile.guidelines:
                brand_parts.append(brand_profile.guidelines)
            if brand_parts:
                parts.append(" ".join(brand_parts))

        if reference_pack:
            rp_parts: list[str] = []
            if "product_truth" in reference_pack:
                pt = reference_pack["product_truth"]
                if isinstance(pt, dict) and pt.get("name"):
                    rp_parts.append(f"Product: {pt['name']}")
            if "brand_rules" in reference_pack:
                br = reference_pack["brand_rules"]
                if isinstance(br, dict) and br.get("tone"):
                    rp_parts.append(f"Brand: {br['tone']}")
            if rp_parts:
                parts.append("Reference: " + " | ".join(rp_parts))

        if asset.negative_prompt:
            parts.append(f"--no {asset.negative_prompt.strip()}")

        return "\n".join(parts)


def build_prompt(
    project_id: int, slot_index: int, session: Optional[Session] = None
) -> str:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        brief = (
            session.query(ImageBrief)
            .filter(
                ImageBrief.project_id == project_id,
                ImageBrief.slot_index == slot_index,
            )
            .first()
        )
        if brief is None:
            raise ValueError(
                f"E_BUILD_001: No ImageBrief for project {project_id} slot {slot_index}"
            )

        try:
            brief_data = json.loads(brief.brief_json)
        except (json.JSONDecodeError, TypeError):
            brief_data = {}

        tags = brief_data.get("target_tags", {})
        concept = brief_data.get("concept", "")

        brand = (
            session.query(BrandProfile)
            .filter(BrandProfile.project_id == project_id)
            .first()
        )

        competitor = (
            session.query(CompetitorListing)
            .filter(CompetitorListing.project_id == project_id)
            .first()
        )

        parts: list[str] = []

        slot_desc = SLOT_MAPPING.get(slot_index, f"Slot {slot_index}")
        parts.append(f"Slot {slot_index}: {slot_desc}")

        if concept:
            parts.append(f"Concept: {concept}")
        if tags:
            parts.append(
                f"Style: {tags.get('intent_tag', '')} {tags.get('layout_tag', '')} "
                f"{tags.get('style_tag', '')} {tags.get('color_tag', '')}"
            )

        if competitor:
            comp_parts = []
            if competitor.title:
                comp_parts.append(f"Competitor: {competitor.title}")
            if competitor.bullet_points:
                comp_parts.append(f"Key points: {competitor.bullet_points}")
            if comp_parts:
                parts.append(" | ".join(comp_parts))

        if brand:
            brand_parts = []
            if brand.brand_tone:
                brand_parts.append(f"Brand tone: {brand.brand_tone}")
            if brand.color_system:
                brand_parts.append(f"Brand colors: {brand.color_system}")
            if brand.guidelines:
                brand_parts.append(brand.guidelines)
            if brand_parts:
                parts.append(" ".join(brand_parts))

        return "\n".join(parts)
    finally:
        if owns_session:
            session.close()


def _slot_label(slot_index: int) -> str:
    desc = SLOT_MAPPING.get(slot_index, "")
    return desc.split("—")[0].strip() if "—" in desc else f"SLOT{slot_index}"


def generate_slot_prompts(project_id: int) -> dict[str, str]:
    """Generate prompts for every slot in a project's SlotPlan.

    Returns dict mapping slot label (MAIN/ALT1/...) to assembled prompt.

    Raises:
        ValueError E_ENGINE_002 — project has no SlotPlan records
    """
    with get_session() as session:
        plans = (
            session.query(SlotPlan)
            .filter(SlotPlan.project_id == project_id)
            .order_by(SlotPlan.slot_index)
            .all()
        )

        if not plans:
            raise ValueError(
                f"E_ENGINE_002: project {project_id} has no SlotPlan "
                "(run slot_planner first)"
            )

        result: dict[str, str] = {}
        for plan in plans:
            asset = (
                session.query(PromptAsset)
                .filter(
                    PromptAsset.project_id == project_id,
                    PromptAsset.slot_index == plan.slot_index,
                )
                .order_by(PromptAsset.version.desc())
                .first()
            )

            if asset is None:
                logger.warning(
                    "No PromptAsset for project %s slot %s, skipping",
                    project_id,
                    plan.slot_index,
                )
                continue

            variables = {
                "composition": plan.layout_tag or "",
                "subject": plan.description or "",
                "environment": "",
                "camera": "",
                "tone": plan.style_tag or "",
                "constraints": plan.color_tag or "",
            }

            label = _slot_label(plan.slot_index)
            try:
                result[label] = assemble_prompt(asset.id, variables)
            except ValueError as exc:
                logger.warning("Skipping slot %s: %s", plan.slot_index, exc)

        return result
