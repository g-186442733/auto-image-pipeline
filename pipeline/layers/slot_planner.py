"""Slot plan generator – creates 8 SlotPlan records for a project."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from pipeline.constants.tags import SLOT_MAPPING
from pipeline.models.base import get_session
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.customer_brief import CustomerBrief
from pipeline.models.image_brief import ImageBrief
from pipeline.models.product_profile import ProductProfile
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.qa_record import QARecord
from pipeline.models.prompt_asset import PromptAsset
from pipeline.layers.tag_system import assign_tags
from pipeline.utils.logger import setup_logger
from collections import Counter
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.price_analysis import PriceAnalysis
from pipeline.models.promo_analysis import PromoAnalysis
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.qa_entry import QAEntry
from pipeline.models.knowledge_entry import KnowledgeEntry

__all__ = ["generate_slot_plan", "regen_single_slot"]

logger = setup_logger(__name__)

_SLOT_DEFAULTS: dict[int, tuple[str, str, str, str]] = {
    1: ("INT_HERO", "LAY_CENTER", "STY_MINIMAL", "CLR_WHITE"),
    2: ("INT_LIFESTYLE", "LAY_RULE3", "STY_NATURAL", "CLR_LIGHT"),
    3: ("INT_INFOGRAPHIC", "LAY_SPLIT", "STY_TECH", "CLR_LIGHT"),
    4: ("INT_DETAIL", "LAY_CENTER", "STY_PREMIUM", "CLR_DARK"),
    5: ("INT_COMPARISON", "LAY_SPLIT", "STY_BOLD", "CLR_WHITE"),
    6: ("INT_PACKAGING", "LAY_FLAT", "STY_MINIMAL", "CLR_WHITE"),
    7: ("INT_LIFESTYLE", "LAY_RULE3", "STY_PLAYFUL", "CLR_WARM"),
    8: ("INT_HERO", "LAY_CENTER", "STY_BOLD", "CLR_BRAND"),
}

_SLOT_ANGLE_TARGETS: dict[int, str] = {
    1: "front view",
    2: "side profile",
    3: "front view",
    4: "macro close-up",
    5: "45-degree angle",
    6: "overhead shot",
    7: "side profile",
    8: "45-degree angle",
}


def _angle_target_for_slot(slot_index: int, fallback: str | None = None) -> str | None:
    return _SLOT_ANGLE_TARGETS.get(slot_index) or fallback


def _tags_from_brief(brief: ImageBrief) -> tuple[str, str, str, str] | None:
    try:
        data = json.loads(brief.brief_json)
        tags = data.get("target_tags", {})
        intent = tags.get("intent_tag")
        layout = tags.get("layout_tag")
        style = tags.get("style_tag")
        color = tags.get("color_tag")
        if all((intent, layout, style, color)):
            return (intent, layout, style, color)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return None


BENCHMARK_SLOT_GROUPS: dict[int, list[int]] = {
    1: [1],
    2: [2, 3],
    3: [2, 3],
    4: [4, 5],
    5: [4, 5],
    6: [6, 7],
    7: [6, 7],
    8: [8, 9],
}

_BENCHMARK_FALLBACK_MIN = 3


def _build_context(project_id: int, session: Session, slot_index: int = 0) -> str:
    context_parts: list[str] = []

    # Project
    project = None
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        if project and project.name:
            context_parts.append(f"Product: {project.name}")
    except Exception:
        logger.warning("Failed to load project info", exc_info=True)

    # BrandProfile — 正确路径：project_id → ProductProfile.brand_profile_id → BrandProfile
    try:
        pp_for_brand = (
            session.query(ProductProfile)
            .filter(ProductProfile.project_id == project_id)
            .first()
        )
        bp = None
        if pp_for_brand and pp_for_brand.brand_profile_id:
            bp = (
                session.query(BrandProfile)
                .filter(BrandProfile.id == pp_for_brand.brand_profile_id)
                .first()
            )
        if bp:
            bp_parts = []
            if bp.brand_tone:
                bp_parts.append(f"<brand_tone>{bp.brand_tone}</brand_tone>")
            if bp.color_system:
                bp_parts.append(f"<color_system>{bp.color_system}</color_system>")
            if bp.photo_style:
                bp_parts.append(f"<photo_style>{bp.photo_style}</photo_style>")
            if bp.scene_preference:
                bp_parts.append(
                    f"<scene_preference>{bp.scene_preference}</scene_preference>"
                )
            if bp.composition_preference:
                bp_parts.append(
                    f"<composition>{bp.composition_preference}</composition>"
                )
            if bp.font_preference:
                bp_parts.append(f"<font>{bp.font_preference}</font>")
            if bp.model_type:
                bp_parts.append(f"<model_type>{bp.model_type}</model_type>")
            if bp.material_texture:
                bp_parts.append(
                    f"<material_texture>{bp.material_texture}</material_texture>"
                )
            if bp.competitor_positioning:
                bp_parts.append(
                    f"<competitor_positioning>{bp.competitor_positioning}</competitor_positioning>"
                )
            if bp.brand_story:
                bp_parts.append(f"<brand_story>{bp.brand_story}</brand_story>")
            if bp.messaging_pillars:
                bp_parts.append(
                    f"<messaging_pillars>{bp.messaging_pillars}</messaging_pillars>"
                )
            if bp.guidelines:
                bp_parts.append(f"<guidelines>{bp.guidelines}</guidelines>")
            if bp_parts:
                context_parts.append(
                    "<brand_profile>\n" + "\n".join(bp_parts) + "\n</brand_profile>"
                )
    except Exception:
        logger.warning("Failed to load brand profile", exc_info=True)

    # ProductProfile
    try:
        pp = session.query(ProductProfile).filter_by(project_id=project_id).first()
        if pp:
            pp_parts = []
            if pp.product_category:
                pp_parts.append(f"<category>{pp.product_category}</category>")
            if pp.price_point:
                pp_parts.append(f"<price_point>{pp.price_point}</price_point>")
            if pp.key_features:
                pp_parts.append(f"<key_features>{pp.key_features}</key_features>")
            if pp.visual_notes:
                pp_parts.append(f"<visual_notes>{pp.visual_notes}</visual_notes>")
            if pp_parts:
                context_parts.append(
                    "<product_profile>\n" + "\n".join(pp_parts) + "\n</product_profile>"
                )
    except Exception:
        logger.warning("Failed to load product profile", exc_info=True)

    # CustomerBrief
    try:
        if project and project.customer_brief:
            cb_data = (
                json.loads(project.customer_brief)
                if isinstance(project.customer_brief, str)
                else project.customer_brief
            )
            if isinstance(cb_data, dict):
                cb_parts = []
                if cb_data.get("listing_title"):
                    cb_parts.append(f"Listing Title: {cb_data['listing_title']}")
                if cb_data.get("listing_keywords"):
                    kw = cb_data["listing_keywords"]
                    if isinstance(kw, list):
                        kw = ", ".join(kw)
                    cb_parts.append(f"Keywords: {kw}")
                if cb_data.get("listing_bullets"):
                    bp_val = cb_data["listing_bullets"]
                    if isinstance(bp_val, list):
                        bp_val = " | ".join(bp_val[:3])
                    cb_parts.append(f"Bullet Points: {bp_val}")
                if cb_data.get("brand_voice"):
                    cb_parts.append(f"Brand Voice: {cb_data['brand_voice']}")
                if cb_data.get("campaign_goal"):
                    cb_parts.append(f"Campaign Goal: {cb_data['campaign_goal']}")
                if cb_data.get("target_audience"):
                    cb_parts.append(f"Target Audience: {cb_data['target_audience']}")
                if cb_data.get("customer_pain_points"):
                    cb_parts.append(
                        f"Customer Pain Points: {cb_data['customer_pain_points']}"
                    )
                if cb_data.get("audience_scenarios"):
                    cb_parts.append(
                        f"Use Case Scenarios: {cb_data['audience_scenarios']}"
                    )
                for field, label in [
                    ("product_dimensions", "Dimensions"),
                    ("product_weight", "Weight"),
                    ("product_material", "Material"),
                    ("product_color", "Color"),
                    ("package_contents", "Package Contents"),
                    ("product_certifications", "Certifications"),
                ]:
                    if cb_data.get(field):
                        cb_parts.append(f"{label}: {cb_data[field]}")
                if cb_parts:
                    context_parts.append("CustomerBrief: " + "; ".join(cb_parts))
    except Exception:
        logger.warning("Failed to load customer brief from JSON blob", exc_info=True)

    # CompetitorListing top 5
    try:
        listings = (
            session.query(CompetitorListing)
            .filter(CompetitorListing.project_id == project_id)
            .limit(5)
            .all()
        )
        for cl in listings:
            parts = []
            if cl.asin:
                parts.append(f"ASIN:{cl.asin}")
            if cl.title:
                parts.append(f"Title:{cl.title}")
            if cl.price:
                parts.append(f"Price:{cl.price}")
            if cl.rating:
                parts.append(f"Rating:{cl.rating}")
            if cl.review_count:
                parts.append(f"Reviews:{cl.review_count}")
            if cl.selling_points_map:
                try:
                    sp = (
                        json.loads(cl.selling_points_map)
                        if isinstance(cl.selling_points_map, str)
                        else cl.selling_points_map
                    )
                    if isinstance(sp, dict):
                        parts.append(f"SellingPoints:{list(sp.keys())[:3]}")
                except Exception:
                    pass
            if parts:
                context_parts.append("Competitor: " + "; ".join(parts))
    except Exception:
        logger.warning("Failed to load competitor listings", exc_info=True)

    # Vision aggregation：按 slot_index 对应的 Amazon 图位分组，无同位数据则跳过不降级全量
    try:
        target_slots = BENCHMARK_SLOT_GROUPS.get(slot_index, []) if slot_index else []
        bm_query = session.query(AmazonBenchmark).filter(
            AmazonBenchmark.project_id == project_id
        )
        if target_slots:
            # 优先取当前图位分组，有几条用几条（1 张也有参考价值），不退回全量
            bm_rows = (
                bm_query.filter(AmazonBenchmark.image_slot.in_(target_slots))
                .order_by(AmazonBenchmark.score.desc())
                .limit(9)
                .all()
            )
            # 当前图位完全没有数据时，才退回全量 Top-9
            if not bm_rows:
                bm_rows = bm_query.order_by(AmazonBenchmark.score.desc()).limit(9).all()
        else:
            bm_rows = bm_query.order_by(AmazonBenchmark.score.desc()).limit(9).all()
        lighting_counts: Counter = Counter()
        angle_counts: Counter = Counter()
        dof_counts: Counter = Counter()
        bg_counts: Counter = Counter()
        intent_counts: Counter = Counter()
        color_temp_counts: Counter = Counter()
        subject_material_counts: Counter = Counter()
        total_bm = len(bm_rows)
        for bm in bm_rows:
            if bm.analysis:
                try:
                    analysis = (
                        json.loads(bm.analysis)
                        if isinstance(bm.analysis, str)
                        else bm.analysis
                    )
                    if isinstance(analysis, dict):
                        if analysis.get("lighting"):
                            lighting_counts[analysis["lighting"]] += 1
                        if analysis.get("angle"):
                            angle_counts[analysis["angle"]] += 1
                        if analysis.get("dof"):
                            dof_counts[analysis["dof"]] += 1
                        if analysis.get("background_material"):
                            bg_counts[analysis["background_material"]] += 1
                        for intent_tag in analysis.get("intent_tags", []):
                            if intent_tag:
                                intent_counts[intent_tag] += 1
                        if analysis.get("color_temp"):
                            color_temp_counts[analysis["color_temp"]] += 1
                        if analysis.get("subject_material"):
                            subject_material_counts[analysis["subject_material"]] += 1
                except Exception:
                    pass
        vision_parts = []
        if intent_counts and total_bm > 0:
            intent_dist = ", ".join(
                f"{tag}({cnt}/{total_bm})" for tag, cnt in intent_counts.most_common(6)
            )
            vision_parts.append(f"IntentDist:[{intent_dist}]")
        if lighting_counts:
            vision_parts.append(f"TopLighting:{lighting_counts.most_common(2)}")
        if angle_counts:
            vision_parts.append(f"TopAngle:{angle_counts.most_common(2)}")
        if dof_counts:
            vision_parts.append(f"TopDOF:{dof_counts.most_common(2)}")
        if bg_counts:
            vision_parts.append(f"TopBackground:{bg_counts.most_common(2)}")
        if color_temp_counts:
            vision_parts.append(f"TopColorTemp:{color_temp_counts.most_common(2)}")
        if subject_material_counts:
            vision_parts.append(
                f"TopSubjectMaterial:{subject_material_counts.most_common(3)}"
            )
        if vision_parts:
            context_parts.append("VisionAggregation: " + "; ".join(vision_parts))
    except Exception:
        logger.warning("Failed to aggregate vision data", exc_info=True)

    # PriceAnalysis
    try:
        pa = session.query(PriceAnalysis).filter_by(project_id=project_id).first()
        if pa:
            pa_parts = []
            if pa.price_current:
                pa_parts.append(f"CurrentPrice:{pa.price_current}")
            if pa.price_avg_30d:
                pa_parts.append(f"Avg30d:{pa.price_avg_30d}")
            if pa.price_position:
                pa_parts.append(f"Position:{pa.price_position}")
            if pa.competitor_prices:
                pa_parts.append(f"CompetitorPrices:{pa.competitor_prices}")
            if pa_parts:
                context_parts.append("PriceAnalysis: " + "; ".join(pa_parts))
    except Exception:
        logger.warning("Failed to load price analysis", exc_info=True)

    # PromoAnalysis
    try:
        prom = session.query(PromoAnalysis).filter_by(project_id=project_id).first()
        if prom:
            prom_parts = []
            if prom.promo_frequency:
                prom_parts.append(f"PromoFreq:{prom.promo_frequency}")
            if prom.avg_discount_pct:
                prom_parts.append(f"AvgDiscount:{prom.avg_discount_pct}%")
            if prom.promo_pattern:
                prom_parts.append(f"Pattern:{prom.promo_pattern}")
            if prom_parts:
                context_parts.append("PromoAnalysis: " + "; ".join(prom_parts))
    except Exception:
        logger.warning("Failed to load promo analysis", exc_info=True)

    # ReviewCluster top 3
    try:
        clusters = (
            session.query(ReviewCluster)
            .filter(ReviewCluster.project_id == project_id)
            .order_by(ReviewCluster.count.desc())
            .limit(3)
            .all()
        )
        for rc in clusters:
            rc_parts = []
            if rc.cluster_label:
                rc_parts.append(f"Label:{rc.cluster_label}")
            if rc.sentiment:
                rc_parts.append(f"Sentiment:{rc.sentiment}")
            if rc.count:
                rc_parts.append(f"Count:{rc.count}")
            if rc_parts:
                context_parts.append("ReviewCluster: " + "; ".join(rc_parts))
    except Exception:
        logger.warning("Failed to load review clusters", exc_info=True)

    # QAEntry top 3 by frequency
    try:
        qa_entries = (
            session.query(QAEntry)
            .filter(QAEntry.project_id == project_id)
            .order_by(QAEntry.frequency.desc())
            .limit(3)
            .all()
        )
        for qa in qa_entries:
            if qa.question and qa.answer:
                context_parts.append(f"Q&A: Q:{qa.question[:80]} A:{qa.answer[:80]}")
    except Exception:
        logger.warning("Failed to load QA entries", exc_info=True)

    # KnowledgeEntry style rules
    try:
        from pipeline.layers.knowledge_base import get_popular_entries

        popular = get_popular_entries(session, category="style_rule", limit=5)
        hints = [e.content for e in popular if e.content]
        if hints:
            context_parts.append("StyleRules: " + "; ".join(hints[:3]))
    except Exception:
        logger.warning("Failed to load knowledge entries", exc_info=True)

    return "\n".join(context_parts)


def _call_llm_for_slot(
    slot_index: int,
    slot_desc: str,
    context: str,
    previous_reasoning: str | None = None,
    qa_issues: list | None = None,
) -> dict | None:
    import httpx
    from pipeline.config import config

    api_key = config.api_key
    if not api_key:
        logger.warning("No API key configured, cannot call LLM for slot regen")
        return None

    intent_options = "INT_HERO, INT_LIFESTYLE, INT_INFOGRAPHIC, INT_COMPARISON, INT_DETAIL, INT_PACKAGING"
    layout_options = "LAY_CENTER, LAY_RULE3, LAY_FLAT, LAY_SPLIT, LAY_GRID"
    style_options = (
        "STY_MINIMAL, STY_PREMIUM, STY_PLAYFUL, STY_TECH, STY_NATURAL, STY_BOLD"
    )
    color_options = "CLR_WHITE, CLR_LIGHT, CLR_DARK, CLR_WARM, CLR_COOL, CLR_BRAND"

    prompt = f"""You are an Amazon product image strategist. Given product context, assign optimal visual tags for a specific image slot.

SLOT: {slot_index} — {slot_desc}

PRODUCT CONTEXT:
{context}
"""

    if previous_reasoning or qa_issues:
        issues_text = (
            "\n".join(f"- {i}" for i in qa_issues) if qa_issues else "not specified"
        )
        reasoning_text = previous_reasoning or "not available"
        prompt += f"""
PREVIOUS ATTEMPT FEEDBACK (this slot was regenerated due to issues):
Previous reasoning: {reasoning_text}
QA issues found: {issues_text}
Improve on the previous attempt by directly addressing the issues above.
"""

    prompt += f"""
AVAILABLE TAGS (pick exactly one from each):
- intent_tag: {intent_options}
- layout_tag: {layout_options}
- style_tag: {style_options}
- color_tag: {color_options}

Return ONLY valid JSON with these fields:
{{"reasoning": "brief chain-of-thought explaining tag choices based on brand + slot goal", "intent_tag": "...", "layout_tag": "...", "style_tag": "...", "color_tag": "...", "description": "one-sentence rationale", "title": "short display title e.g. 主图-白底正面", "gen_params": "--ar 1:1 --stylize 200 --style raw", "visual_focus": "what to visually show", "key_message": "one-line selling point", "competitor_contrast": "visual differentiation direction", "lighting_tag": "one of: soft studio lighting/single side hard light/top-down overhead light/natural daylight/ring light", "angle_tag": "one of: front view/45-degree angle/overhead shot/side profile/macro close-up", "dof_tag": "one of: shallow depth of field/deep depth of field/standard depth of field", "background_tag": "one of: pure white background/gradient background/scene environment/textured background/transparent background", "color_temp_tag": "one of: warm/neutral/cool", "overlay_text": "text to overlay on image (empty if none)", "shot_type": "one of: close-up/wide-shot/full-body/half-body/macro/detail", "subject_material": "material description of the product surface (e.g. matte plastic, brushed aluminum)", "negative_prompt": "elements to avoid in image generation (empty if none)", "comparison_structure": "for INT_COMPARISON only: e.g. left=competitor,right=product or empty string"}}

gen_params: Midjourney generation parameters. Hero/main shots → "--ar 1:1 --stylize 200 --style raw". Infographic/comparison → "--ar 4:5 --stylize 150". Lifestyle/detail → "--ar 4:5 --stylize 200 --style raw". Use empty string if unsure.
visual_focus/key_message/competitor_contrast/overlay_text: MUST be written in English only. Do not use Chinese characters in these fields. Use empty string if unknown.
shot_type/subject_material: MUST be written in English only. Use empty string if unknown.
lighting_tag/angle_tag/dof_tag/background_tag/color_temp_tag: Use the English values listed above exactly as shown.
Angle diversity is mandatory across the listing set: slot 1 front view, slot 2 side profile, slot 3 front view/orthographic, slot 4 macro close-up, slot 6 overhead shot. Do not repeat 45-degree angle for multiple core slots.
        title: Short human-readable label for this slot. Always fill.
negative_prompt: What to exclude from the image. Fill for all slots.
comparison_structure: Only fill when intent_tag is INT_COMPARISON. Format: "left=X,right=Y". Empty string otherwise.
No markdown fences. No extra text."""

    endpoint = f"{config.api_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.openai_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.7,
    }

    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].strip()
        data = json.loads(raw)
        valid_intent = {
            t.code
            for t in __import__(
                "pipeline.constants.tags", fromlist=["INTENT_TAGS"]
            ).INTENT_TAGS
        }
        valid_layout = {
            t.code
            for t in __import__(
                "pipeline.constants.tags", fromlist=["LAYOUT_TAGS"]
            ).LAYOUT_TAGS
        }
        valid_style = {
            t.code
            for t in __import__(
                "pipeline.constants.tags", fromlist=["STYLE_TAGS"]
            ).STYLE_TAGS
        }
        valid_color = {
            t.code
            for t in __import__(
                "pipeline.constants.tags", fromlist=["COLOR_TAGS"]
            ).COLOR_TAGS
        }
        if (
            data.get("intent_tag") in valid_intent
            and data.get("layout_tag") in valid_layout
            and data.get("style_tag") in valid_style
            and data.get("color_tag") in valid_color
        ):
            return data
        logger.warning(
            "LLM returned invalid tag codes for slot %d: %s", slot_index, data
        )
        return None
    except Exception as exc:
        logger.warning("LLM call failed for slot %d: %s", slot_index, exc)
        return None


def _get_latest_qa_issues(project_id: int, slot_index: int, session: Session) -> list:
    """查询最新一次 QA 的 issues 列表，用于 regen 时注入反馈闭环。

    关联路径：PromptAsset(project_id + slot_index) → QARecord.details → issues[]
    若无 QA 记录或解析失败，返回空列表，不影响正常 regen 流程。
    """
    try:
        # 联表查询：找该 project+slot 下最新的 QARecord（跨 asset 版本）
        qa_record = (
            session.query(QARecord)
            .join(PromptAsset, QARecord.prompt_asset_id == PromptAsset.id)
            .filter(
                PromptAsset.project_id == project_id,
                PromptAsset.slot_index == slot_index,
            )
            .order_by(QARecord.id.desc())
            .first()
        )
        if qa_record is None or not qa_record.details:
            return []

        # 解析 details JSON，取 issues 列表
        details = (
            json.loads(qa_record.details)
            if isinstance(qa_record.details, str)
            else qa_record.details
        )
        issues = details.get("issues", [])
        return issues if isinstance(issues, list) else []
    except Exception as exc:
        logger.warning(
            "Failed to fetch QA issues for project %d slot %d: %s",
            project_id,
            slot_index,
            exc,
        )
        return []


def regen_single_slot(
    project_id: int, slot_index: int, session: Optional[Session] = None
) -> SlotPlan:
    from pipeline.models.project import Project

    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        project_name = project.name if project else f"Project {project_id}"

        context = _build_context(project_id, session, slot_index=slot_index)

        # 取当前 slot 的上次 reasoning 和 QA issues，用于定向改进
        existing_plan = (
            session.query(SlotPlan)
            .filter_by(project_id=project_id, slot_index=slot_index)
            .order_by(SlotPlan.id.desc())
            .first()
        )
        previous_reasoning = existing_plan.reasoning if existing_plan else None
        qa_issues = _get_latest_qa_issues(project_id, slot_index, session)

        slot_desc = SLOT_MAPPING.get(slot_index, f"Slot {slot_index}")
        llm_result = _call_llm_for_slot(
            slot_index,
            slot_desc,
            context,
            previous_reasoning=previous_reasoning,
            qa_issues=qa_issues,
        )

        if llm_result:
            intent = llm_result["intent_tag"]
            layout = llm_result["layout_tag"]
            style = llm_result["style_tag"]
            color = llm_result["color_tag"]
            description = llm_result.get("description", slot_desc)
            gen_params = llm_result.get("gen_params", "") or ""
            logger.info(
                "LLM regen slot %d for project %d: %s/%s/%s/%s",
                slot_index,
                project_id,
                intent,
                layout,
                style,
                color,
            )
        else:
            defaults = _SLOT_DEFAULTS.get(
                slot_index, ("INT_HERO", "LAY_CENTER", "STY_MINIMAL", "CLR_WHITE")
            )
            intent, layout, style, color = defaults
            description = slot_desc + " (fallback)"
            gen_params = ""
            logger.warning("LLM regen failed for slot %d, using defaults", slot_index)

        # 取最新一版（按 id desc），避免多版本残留导致改错行
        plan = (
            session.query(SlotPlan)
            .filter_by(project_id=project_id, slot_index=slot_index)
            .order_by(SlotPlan.id.desc())
            .first()
        )
        if plan is None:
            plan = SlotPlan(project_id=project_id, slot_index=slot_index)
            session.add(plan)
        plan.intent_tag = intent
        plan.layout_tag = layout
        plan.style_tag = style
        plan.color_tag = color
        plan.description = description
        plan.gen_params = gen_params or None
        plan.visual_focus = (
            llm_result.get("visual_focus") or None if llm_result else None
        )
        plan.key_message = llm_result.get("key_message") or None if llm_result else None
        plan.competitor_contrast = (
            llm_result.get("competitor_contrast") or None if llm_result else None
        )
        plan.lighting_tag = (
            llm_result.get("lighting_tag") or None if llm_result else None
        )
        llm_angle = llm_result.get("angle_tag") or None if llm_result else None
        plan.angle_tag = _angle_target_for_slot(slot_index, llm_angle)
        plan.dof_tag = llm_result.get("dof_tag") or None if llm_result else None
        plan.background_tag = (
            llm_result.get("background_tag") or None if llm_result else None
        )
        plan.overlay_text = (
            llm_result.get("overlay_text") or None if llm_result else None
        )
        plan.shot_type = llm_result.get("shot_type") or None if llm_result else None
        plan.subject_material = (
            llm_result.get("subject_material") or None if llm_result else None
        )
        plan.title = llm_result.get("title") or None if llm_result else None
        plan.negative_prompt = (
            llm_result.get("negative_prompt") or None if llm_result else None
        )
        plan.comparison_structure = (
            llm_result.get("comparison_structure") or None if llm_result else None
        )
        plan.reasoning = llm_result.get("reasoning") or None if llm_result else None
        plan.generated_lighting = plan.lighting_tag
        plan.generated_angle = plan.angle_tag
        plan.generated_shot_type = plan.shot_type
        plan.generated_bg_material = plan.background_tag
        plan.generated_color_temp = (
            llm_result.get("color_temp_tag") or None if llm_result else None
        )
        session.commit()
        session.refresh(plan)
        session.expunge(plan)
        return plan
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def generate_slot_plan(
    project_id: int,
    session: Optional[Session] = None,
    pipeline_run_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> list[SlotPlan]:
    """Generate 8 SlotPlan records for *project_id*.

    When *session* is ``None`` a new session is created via ``get_session()``.
    If ``ImageBrief`` rows exist for the project, slot tags are derived from
    ``brief_json["target_tags"]``; otherwise ``_SLOT_DEFAULTS`` is used.

    Raises ``ValueError`` with code ``E_PLANNER_001`` when no
    AmazonBenchmark rows exist for the project.
    """
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        bench_count = (
            session.query(AmazonBenchmark)
            .filter(AmazonBenchmark.project_id == project_id)
            .count()
        )
        if bench_count == 0:
            logger.warning(
                "E_PLANNER_001: No AmazonBenchmark rows for project %d — using default 7-slot plan (degraded mode)",
                project_id,
            )
            _DEFAULT_SLOT_NAMES = [
                ("主图", "INT_HERO", "LAY_CENTER", "STY_MINIMAL", "CLR_WHITE"),
                ("场景图", "INT_LIFESTYLE", "LAY_RULE3", "STY_NATURAL", "CLR_LIGHT"),
                ("功能图1", "INT_INFOGRAPHIC", "LAY_SPLIT", "STY_TECH", "CLR_LIGHT"),
                ("功能图2", "INT_INFOGRAPHIC", "LAY_CENTER", "STY_BOLD", "CLR_WHITE"),
                ("细节图1", "INT_DETAIL", "LAY_CENTER", "STY_PREMIUM", "CLR_DARK"),
                ("细节图2", "INT_DETAIL", "LAY_FLAT", "STY_MINIMAL", "CLR_WHITE"),
                ("对比图", "INT_COMPARISON", "LAY_SPLIT", "STY_BOLD", "CLR_WHITE"),
            ]
            fallback_plans: list[SlotPlan] = []
            for idx, (name, intent, layout, style, color) in enumerate(
                _DEFAULT_SLOT_NAMES, 1
            ):
                plan = SlotPlan(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    slot_index=idx,
                    intent_tag=intent,
                    layout_tag=layout,
                    style_tag=style,
                    color_tag=color,
                    description=f"{name} (default fallback)",
                    pipeline_run_id=pipeline_run_id,
                )
                session.add(plan)
                fallback_plans.append(plan)
            session.commit()
            for p in fallback_plans:
                session.refresh(p)
            session.expunge_all()
            logger.info(
                "Created %d default slot plans for project %d (degraded mode)",
                len(fallback_plans),
                project_id,
            )
            return fallback_plans

        briefs_q = session.query(ImageBrief).filter(ImageBrief.project_id == project_id)
        if pipeline_run_id is not None:
            briefs_q = briefs_q.filter(ImageBrief.pipeline_run_id == pipeline_run_id)
        briefs: dict[int, ImageBrief] = {b.slot_index: b for b in briefs_q.all()}

        brief_concepts: list[str] = []
        for idx in sorted(briefs.keys()):
            b = briefs[idx]
            try:
                bdata = json.loads(b.brief_json)
                concept = bdata.get("concept", "")
                direction = bdata.get("direction", "")
                diff = bdata.get("diff", "")
                visual_style = bdata.get("visual_style", "")
                copy_overlay = bdata.get("copy_overlay", "")
                parts = []
                if concept:
                    parts.append(concept)
                if direction:
                    parts.append(f"方向: {direction}")
                if diff:
                    parts.append(f"差异化: {diff}")
                if visual_style:
                    parts.append(f"视觉类型: {visual_style}")
                if copy_overlay:
                    parts.append(f"文字建议: {copy_overlay}")
                if parts:
                    brief_concepts.append(f"Slot {idx}: " + " | ".join(parts))
            except (json.JSONDecodeError, TypeError):
                pass
        brief_prefix = (
            "<brief_concepts>\n" + "\n".join(brief_concepts) + "\n</brief_concepts>\n\n"
            if brief_concepts
            else ""
        )

        existing_plans_q = session.query(SlotPlan).filter(SlotPlan.project_id == project_id)
        if pipeline_run_id is None:
            existing_plans_q = existing_plans_q.filter(SlotPlan.pipeline_run_id.is_(None))
        else:
            existing_plans_q = existing_plans_q.filter(SlotPlan.pipeline_run_id == pipeline_run_id)
        existing_plans_q.delete(synchronize_session=False)
        session.flush()

        plans: list[SlotPlan] = []
        for slot_index in range(1, 9):
            brief = briefs.get(slot_index)
            slot_desc = SLOT_MAPPING.get(slot_index, f"Slot {slot_index}")
            llm_context = brief_prefix + _build_context(
                project_id, session, slot_index=slot_index
            )

            llm_result = _call_llm_for_slot(slot_index, slot_desc, llm_context)
            if llm_result:
                intent = llm_result["intent_tag"]
                layout = llm_result["layout_tag"]
                style = llm_result["style_tag"]
                color = llm_result["color_tag"]
                description = llm_result.get("description", slot_desc)
                gen_params = llm_result.get("gen_params", "") or ""
            else:
                brief_tags = _tags_from_brief(brief) if brief else None
                if brief_tags:
                    intent, layout, style, color = brief_tags
                    description = slot_desc + " (brief)"
                else:
                    intent, layout, style, color = _SLOT_DEFAULTS[slot_index]
                    description = slot_desc + " (default)"
                gen_params = ""

            plan = SlotPlan(
                project_id=project_id,
                tenant_id=tenant_id,
                slot_index=slot_index,
                intent_tag=intent,
                layout_tag=layout,
                style_tag=style,
                color_tag=color,
                description=description,
                gen_params=gen_params or None,
                pipeline_run_id=pipeline_run_id,
                visual_focus=llm_result.get("visual_focus") or None
                if llm_result
                else None,
                key_message=llm_result.get("key_message") or None
                if llm_result
                else None,
                competitor_contrast=llm_result.get("competitor_contrast") or None
                if llm_result
                else None,
                lighting_tag=llm_result.get("lighting_tag") or None
                if llm_result
                else None,
                angle_tag=_angle_target_for_slot(
                    slot_index,
                    llm_result.get("angle_tag") or None,
                )
                if llm_result
                else None,
                dof_tag=llm_result.get("dof_tag") or None if llm_result else None,
                background_tag=llm_result.get("background_tag") or None
                if llm_result
                else None,
                overlay_text=llm_result.get("overlay_text") or None
                if llm_result
                else None,
                shot_type=llm_result.get("shot_type") or None if llm_result else None,
                subject_material=llm_result.get("subject_material") or None
                if llm_result
                else None,
                title=llm_result.get("title") or None if llm_result else None,
                negative_prompt=llm_result.get("negative_prompt") or None
                if llm_result
                else None,
                comparison_structure=llm_result.get("comparison_structure") or None
                if llm_result
                else None,
                reasoning=llm_result.get("reasoning") or None if llm_result else None,
                generated_lighting=llm_result.get("lighting_tag") or None
                if llm_result
                else None,
                generated_angle=_angle_target_for_slot(
                    slot_index,
                    llm_result.get("angle_tag") or None if llm_result else None,
                )
                if llm_result
                else None,
                generated_shot_type=llm_result.get("shot_type") or None
                if llm_result
                else None,
                generated_bg_material=llm_result.get("background_tag") or None
                if llm_result
                else None,
                generated_color_temp=llm_result.get("color_temp_tag") or None
                if llm_result
                else None,
            )
            session.add(plan)
            plans.append(plan)

        session.commit()
        for p in plans:
            session.refresh(p)
        session.expunge_all()

        try:
            assign_tags(project_id, project_id, session=session)
        except Exception:
            logger.warning(
                "Tag assignment failed for project %d", project_id, exc_info=True
            )

        logger.info("Created %d slot plans for project %d", len(plans), project_id)
        return plans
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
