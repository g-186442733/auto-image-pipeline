"""Prompt assembly engine — combines PromptAsset templates with variables."""

from __future__ import annotations

from jinja2 import Environment, BaseLoader, TemplateSyntaxError

import json
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.constants.tags import SLOT_MAPPING, TAG_LOOKUP
from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.layers.brand_profiler import get_brand_hierarchy
from pipeline.models.image_brief import ImageBrief
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.slot_plan import SlotPlan
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.prompt_engine")

__all__ = ["assemble_prompt", "build_prompt", "generate_slot_prompts"]

# 允许文字出现的 intent_tag 集合（信息图/对比图/包装图）
_TEXT_ALLOWED_INTENTS = {"INT_INFOGRAPHIC", "INT_COMPARISON", "INT_PACKAGING"}


def _text_constraint(intent_tag: str | None) -> str:
    """根据 intent_tag 返回对应的文字约束句。

    - INT_INFOGRAPHIC / INT_COMPARISON / INT_PACKAGING：允许文字，要求拼写正确
    - 其他（主图/场景图/细节图）：严格禁止文字、水印、标注
    """
    if intent_tag and intent_tag in _TEXT_ALLOWED_INTENTS:
        return "Ensure all text in the image is correctly spelled and legible."
    return "Do not include any text, letters, numbers, words, labels, or watermarks in the image."


REQUIRED_VARIABLE_KEYS = frozenset(
    ["composition", "subject", "environment", "camera", "tone", "constraints"]
)

_jinja_env = Environment(loader=BaseLoader())


def _tag_text(code: str | None) -> str:
    if not code:
        return ""
    tag = TAG_LOOKUP.get(code)
    if tag is None:
        return code
    return f"{tag.name_en}, {tag.description}"


def assemble_prompt(
    prompt_asset_id: int,
    variables: dict,
    brand_profile: BrandProfile | None = None,
    reference_pack: dict | None = None,
    intent_tag: str | None = None,
) -> str:
    """[备用路径，生产流程不调用此函数，入口为 generate_slot_prompts()]

    Assemble a final prompt string.

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

        parts.append(_text_constraint(intent_tag))

        return "\n".join(parts)


def build_prompt(
    project_id: int, slot_index: int, session: Optional[Session] = None
) -> str:
    """[备用路径，生产流程不调用此函数，入口为 generate_slot_prompts()]"""
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

        hierarchy = get_brand_hierarchy(project_id)
        brand = hierarchy.get("brand")
        customer = hierarchy.get("customer")
        product = hierarchy.get("product")

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
                f"Style: {_tag_text(tags.get('intent_tag'))} {_tag_text(tags.get('layout_tag'))} "
                f"{_tag_text(tags.get('style_tag'))} {_tag_text(tags.get('color_tag'))}"
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

        if customer and customer.industry:
            parts.append(f"Industry: {customer.industry}")

        if product:
            prod_parts = []
            if product.product_name:
                prod_parts.append(f"Product: {product.product_name}")
            if product.product_category:
                prod_parts.append(f"Category: {product.product_category}")
            if product.visual_notes:
                prod_parts.append(product.visual_notes)
            if prod_parts:
                parts.append(" ".join(prod_parts))

        _intent_tag = tags.get("intent_tag")
        parts.append(_text_constraint(_intent_tag))

        return "\n".join(parts)
    finally:
        if owns_session:
            session.close()


def _slot_label(slot_index: int) -> str:
    desc = SLOT_MAPPING.get(slot_index, "")
    return desc.split("—")[0].strip() if "—" in desc else f"SLOT{slot_index}"


def generate_slot_prompts(
    project_id: int, slot_indices: list[int] | None = None
) -> dict[str, str]:
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

        if slot_indices is not None:
            plans = [p for p in plans if p.slot_index in slot_indices]

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

            if asset.user_edited:
                result[_slot_label(plan.slot_index)] = asset.prompt_text
                continue

            _comp = (
                session.query(CompetitorListing)
                .filter(CompetitorListing.project_id == project_id)
                .first()
            )
            _comp_bullets = (_comp.bullet_points or "")[:300] if _comp else ""

            variables = {
                "composition": " ".join(
                    filter(
                        None, [_tag_text(plan.layout_tag), _tag_text(plan.angle_tag)]
                    )
                ),
                "subject": " ".join(
                    filter(
                        None,
                        [
                            _tag_text(plan.intent_tag),
                            plan.visual_focus or plan.description,
                            getattr(plan, "subject_material", None),
                        ],
                    )
                ),
                "environment": " ".join(
                    filter(
                        None,
                        [_tag_text(plan.lighting_tag), _tag_text(plan.background_tag)],
                    )
                ),
                "camera": " ".join(
                    filter(
                        None,
                        [_tag_text(plan.dof_tag), getattr(plan, "shot_type", None)],
                    )
                ),
                "tone": " ".join(
                    filter(
                        None,
                        [
                            _tag_text(plan.style_tag),
                            plan.key_message,
                            getattr(plan, "overlay_text", None),
                        ],
                    )
                )[:300],
                "constraints": " ".join(
                    filter(
                        None,
                        [
                            _tag_text(plan.color_tag),
                            plan.competitor_contrast,
                            _comp_bullets,
                        ],
                    )
                )[:300],
            }

            _v_ordered = [
                variables["subject"],
                variables["composition"],
                variables["environment"],
                variables["camera"],
                variables["tone"],
                variables["constraints"],
            ]
            _prompt_core = ", ".join(p for p in _v_ordered if p and p.strip())

            if asset.negative_prompt:
                _prompt_core += f"\n--no {asset.negative_prompt.strip()}"

            _prompt_core += f"\n{_text_constraint(plan.intent_tag)}"

            label = _slot_label(plan.slot_index)
            try:
                prompt_text = _prompt_core
                if plan.gen_params:
                    from pipeline.config import config as _cfg

                    _model = (_cfg.image_model or "").lower()
                    if any(kw in _model for kw in ("midjourney", "mj-", "/mj")):
                        prompt_text = prompt_text + " " + plan.gen_params
                    else:
                        _p = plan.gen_params
                        _natural: list[str] = []
                        import re as _re

                        _ar = _re.search(r"--ar\s+([\d:]+)", _p)
                        if _ar:
                            _natural.append(f"aspect ratio {_ar.group(1)}")
                        if "--style raw" in _p:
                            _natural.append(
                                "raw photographic style, no artistic filter"
                            )
                        _st = _re.search(r"--stylize\s+(\d+)", _p)
                        if _st:
                            _v = int(_st.group(1))
                            if _v >= 600:
                                _natural.append("highly stylized")
                            elif _v >= 300:
                                _natural.append("moderately stylized")
                        if _natural:
                            prompt_text = prompt_text + ", " + ", ".join(_natural)
                result[label] = prompt_text
            except ValueError as exc:
                logger.warning("Skipping slot %s: %s", plan.slot_index, exc)

        return result
