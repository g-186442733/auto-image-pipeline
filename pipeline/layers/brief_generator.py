import json
import logging
import os
import re
from typing import List

import httpx

from pipeline.config import config
from pipeline.models.image_brief import ImageBrief
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.qa_entry import QAEntry
from pipeline.models.customer_brief import CustomerBrief

log = logging.getLogger(__name__)

_DEFAULT_BRIEF = json.dumps(
    {
        "slots": [
            {
                "slot_index": 0,
                "concept": "Main product hero image",
                "direction": "",
                "diff": "",
                "copy_overlay": "",
                "visual_style": "standard",
            }
        ]
    }
)

_BRIEF_PROMPT = (
    "You are an Amazon listing image strategist. Given the brand profile, product profile, "
    "competitor listing data, review clusters, and Q&A entries below, generate an image brief "
    "with slots for the product listing images.\n\n"
    "{knowledge_section}"
    "<brand_profile>\n{brand_text}\n</brand_profile>\n\n"
    "<product_profile>\n{product_text}\n</product_profile>\n\n"
    "<competitor_listing>\n"
    "<title>{title}</title>\n"
    "<bullets>{bullets}</bullets>\n"
    "<selling_points>{selling_points}</selling_points>\n"
    "<description>{description}</description>\n"
    "<social_proof>rating={rating}, reviews={review_count}, category_rank={category_rank}</social_proof>\n"
    "</competitor_listing>\n\n"
    "<review_clusters>\n{clusters_text}\n</review_clusters>\n\n"
    "<customer_qa>\n{qa_text}\n</customer_qa>\n\n"
    "Return a JSON object with a 'slots' array. Each slot has:\n"
    "- slot_index (int)\n"
    "- reasoning (brief chain-of-thought: why this concept serves brand + customer need)\n"
    "- concept (image concept description)\n"
    "- direction (creative scene/context direction for this slot, e.g. '办公场景感', '户外运动', "
    "'家居生活'; be specific and distinct across slots)\n"
    "- diff (one-sentence visual differentiation vs competitors, e.g. '比竞品更有质感', "
    "'突出环保材质'; what makes this image stand out)\n"
    "- copy_overlay (text overlay suggestion)\n"
    "- visual_style (lifestyle/detail/infographic/comparison)\n"
    "- target_tags (object with: intent_tag from [INT_HERO, INT_LIFESTYLE, INT_INFOGRAPHIC, "
    "INT_COMPARISON, INT_DETAIL, INT_PACKAGING], layout_tag from [LAY_CENTER, LAY_RULE3, "
    "LAY_FLAT, LAY_SPLIT, LAY_GRID], style_tag from [STY_MINIMAL, STY_PREMIUM, STY_PLAYFUL, "
    "STY_TECH, STY_NATURAL, STY_BOLD], color_tag from [CLR_WHITE, CLR_LIGHT, CLR_DARK, "
    "CLR_WARM, CLR_COOL, CLR_BRAND]).\n\n"
    "Return ONLY valid JSON, no markdown fences."
)


_STYLE_EXTRACT_PROMPT = (
    "Analyze this reference image and extract its visual style characteristics. "
    "Return a concise comma-separated list of style descriptors covering: "
    "lighting style, color tone, background type, composition, mood, and photography style. "
    "Example: 'warm tones, soft bokeh background, center composition, lifestyle mood, natural lighting'. "
    "Return ONLY the comma-separated descriptors, no other text."
)

_PRODUCT_ANALYSIS_PROMPT = (
    "Analyze this product image and extract key visual attributes for AI image generation. "
    "Return a concise comma-separated list covering: "
    "1) product category (e.g. skincare bottle, electronics device), "
    "2) primary colors using descriptive terms (e.g. matte black, pearl white, rose gold), "
    "3) material and surface finish (e.g. brushed aluminum, soft-touch plastic, glass), "
    "4) shape and silhouette (e.g. cylindrical, rectangular, tapered), "
    "5) key visual features (e.g. gold logo on front center, transparent cap, embossed pattern). "
    "Example: 'skincare serum bottle, pearl white, frosted glass, cylindrical tapered, gold metallic pump top, minimalist label'. "
    "Return ONLY the comma-separated descriptors, no other text."
)

_DETAIL_CLOSEUP_PROMPT = (
    "Analyze this product detail/closeup image and extract fine-grained attributes. "
    "Focus on: material texture (e.g. woven fabric, brushed metal, matte coating), "
    "surface finish quality, stitching or joining details, embossing or printing, "
    "and any unique craftsmanship features visible at close range. "
    "Return ONLY a concise comma-separated list of descriptors, no other text."
)

_PACKAGING_PROMPT = (
    "Analyze this product packaging image and extract key information. "
    "Return a concise comma-separated list covering: "
    "brand name (if visible), product name or model, key claims or certifications printed on pack "
    "(e.g. 'cruelty-free', 'FDA approved', 'patented'), packaging material and color scheme, "
    "and any distinctive packaging design elements. "
    "Return ONLY the comma-separated descriptors, no other text."
)

_SCALE_REF_PROMPT = (
    "Analyze this scale-reference image showing the product alongside a common object or hand. "
    "Describe the product's apparent size relative to the reference object "
    "(e.g. 'fits in one hand, roughly the size of a smartphone', "
    "'taller than a standard water bottle', 'palm-sized, compact'). "
    "Return ONLY a single concise sentence describing the product size, no other text."
)

_USAGE_CONTEXT_PROMPT = (
    "Analyze this usage-context or lifestyle image and extract scene information. "
    "Return a concise comma-separated list covering: "
    "usage scenario (e.g. home office, outdoor workout, kitchen cooking), "
    "apparent user demographic (e.g. young professional, parent, athlete), "
    "mood and lighting style (e.g. warm natural light, bright airy, moody dramatic), "
    "and any notable props or environment elements. "
    "Return ONLY the comma-separated descriptors, no other text."
)

_INBOX_FLATLAY_PROMPT = (
    "Analyze this inbox/flatlay image showing the product and all included accessories. "
    "List every distinct item visible (e.g. 'main unit, USB-C charging cable, user manual, "
    "silicone carrying case, 3 replacement tips'). "
    "Return ONLY a comma-separated list of included items, no other text."
)

_COLOR_VARIANT_PROMPT = (
    "Analyze this image showing multiple color variants of the product. "
    "List all visible color options using precise descriptive terms "
    "(e.g. 'matte black, pearl white, sage green, dusty rose, navy blue'). "
    "Return ONLY the comma-separated color names, no other text."
)


def _extract_style_from_images(image_sources: list[str]) -> str:
    if not image_sources:
        return ""
    try:
        from pipeline.adapters.gemini_vision_adapter import GeminiVisionAdapter

        adapter = GeminiVisionAdapter()
    except Exception:
        return ""

    import tempfile
    import urllib.request

    descriptors = []
    for src in image_sources[:3]:
        src = src.strip()
        if not src:
            continue
        tmp_path = None
        try:
            if src.startswith("http://") or src.startswith("https://"):
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp_path = tmp.name
                urllib.request.urlretrieve(src, tmp_path)
                local_path = tmp_path
            else:
                local_path = src if os.path.isabs(src) else os.path.abspath(src)
                if not os.path.exists(local_path):
                    log.warning(
                        "_extract_style_from_images: file not found: %s", local_path
                    )
                    continue

            result = adapter.analyze(local_path, _STYLE_EXTRACT_PROMPT)
            analysis = (
                result.get("analysis", "") if isinstance(result, dict) else str(result)
            )
            if analysis:
                descriptors.append(analysis.strip())
        except Exception as exc:
            log.warning("_extract_style_from_images: failed for %s: %s", src, exc)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    return "; ".join(descriptors)


def _analyze_product_images(
    white_bg_path: str,
    multiangle_paths: list[str],
    *,
    detail_closeup_paths: list[str] | None = None,
    packaging_path: str | None = None,
    scale_ref_path: str | None = None,
    usage_context_paths: list[str] | None = None,
    inbox_flatlay_path: str | None = None,
    color_variant_paths: list[str] | None = None,
) -> str:
    try:
        from pipeline.adapters.gemini_vision_adapter import GeminiVisionAdapter

        adapter = GeminiVisionAdapter()
    except Exception:
        return ""

    # (prompt, path) pairs in priority order: product appearance first, then supplemental
    sources: list[tuple[str, str]] = []
    if white_bg_path and white_bg_path.strip():
        sources.append((_PRODUCT_ANALYSIS_PROMPT, white_bg_path.strip()))
    for p in multiangle_paths[:3]:
        if p and p.strip():
            sources.append((_PRODUCT_ANALYSIS_PROMPT, p.strip()))
    for p in (detail_closeup_paths or [])[:2]:
        if p and p.strip():
            sources.append((_DETAIL_CLOSEUP_PROMPT, p.strip()))
    if packaging_path and packaging_path.strip():
        sources.append((_PACKAGING_PROMPT, packaging_path.strip()))
    if scale_ref_path and scale_ref_path.strip():
        sources.append((_SCALE_REF_PROMPT, scale_ref_path.strip()))
    for p in (usage_context_paths or [])[:2]:
        if p and p.strip():
            sources.append((_USAGE_CONTEXT_PROMPT, p.strip()))
    if inbox_flatlay_path and inbox_flatlay_path.strip():
        sources.append((_INBOX_FLATLAY_PROMPT, inbox_flatlay_path.strip()))
    for p in (color_variant_paths or [])[:3]:
        if p and p.strip():
            sources.append((_COLOR_VARIANT_PROMPT, p.strip()))

    descriptors = []
    for prompt, src in sources:
        local_path = src if os.path.isabs(src) else os.path.abspath(src)
        if not os.path.exists(local_path):
            log.warning("_analyze_product_images: file not found: %s", local_path)
            continue
        try:
            result = adapter.analyze(local_path, prompt)
            analysis = (
                result.get("analysis", "") if isinstance(result, dict) else str(result)
            )
            if analysis:
                descriptors.append(analysis.strip())
        except Exception as exc:
            log.warning("_analyze_product_images: failed for %s: %s", src, exc)

    return "; ".join(descriptors)


def _call_gemini(prompt: str) -> str:
    api_key = config.api_key
    if not api_key:
        log.warning("brief_generator: 未配置 AIP_API_KEY，跳过 LLM 调用")
        return "{}"
    endpoint = f"{config.api_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.openai_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.7,
    }
    try:
        resp = httpx.post(endpoint, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.error("brief_generator: LLM 调用失败: %s", exc)
        return "{}"


def _strip_markdown_fence(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


def _parse_json_robust(raw: str) -> dict | None:
    cleaned = _strip_markdown_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def generate_brief(
    project_id: int,
    competitor_listing: CompetitorListing,
    review_clusters: List[ReviewCluster],
    qa_entries: List[QAEntry],
    session=None,
    brand_profile=None,
    product_profile=None,
    vision_insights: str = "",
    pipeline_run_id: int = None,
    price_analysis=None,
    promo_analysis=None,
    tenant_id: int = None,  # 租户 ID，写入 ImageBrief
) -> list[ImageBrief]:
    clusters_text = "\n".join(
        f"- {c.cluster_label} ({c.sentiment}, {c.count} reviews)"
        for c in review_clusters
    )
    qa_text = "\n".join(f"- Q: {q.question} A: {q.answer}" for q in qa_entries)

    if brand_profile is not None:
        bp_parts = []
        if brand_profile.brand_tone:
            bp_parts.append(f"<brand_tone>{brand_profile.brand_tone}</brand_tone>")
        if brand_profile.color_system:
            bp_parts.append(
                f"<color_system>{brand_profile.color_system}</color_system>"
            )
        if brand_profile.photo_style:
            bp_parts.append(f"<photo_style>{brand_profile.photo_style}</photo_style>")
        if brand_profile.scene_preference:
            bp_parts.append(
                f"<scene_preference>{brand_profile.scene_preference}</scene_preference>"
            )
        if brand_profile.composition_preference:
            bp_parts.append(
                f"<composition>{brand_profile.composition_preference}</composition>"
            )
        if brand_profile.model_type:
            bp_parts.append(f"<model_type>{brand_profile.model_type}</model_type>")
        if brand_profile.material_texture:
            bp_parts.append(
                f"<material_texture>{brand_profile.material_texture}</material_texture>"
            )
        if brand_profile.brand_story:
            bp_parts.append(f"<brand_story>{brand_profile.brand_story}</brand_story>")
        if brand_profile.messaging_pillars:
            bp_parts.append(
                f"<messaging_pillars>{brand_profile.messaging_pillars}</messaging_pillars>"
            )
        brand_text = "\n".join(bp_parts) if bp_parts else "N/A"
    else:
        brand_text = "N/A"

    if product_profile is not None:
        pp_parts = []
        if product_profile.product_category:
            pp_parts.append(f"<category>{product_profile.product_category}</category>")
        if product_profile.price_point:
            pp_parts.append(f"<price_point>{product_profile.price_point}</price_point>")
        if product_profile.key_features:
            pp_parts.append(
                f"<key_features>{product_profile.key_features}</key_features>"
            )
        if product_profile.visual_notes:
            pp_parts.append(
                f"<visual_notes>{product_profile.visual_notes}</visual_notes>"
            )
        product_text = "\n".join(pp_parts) if pp_parts else "N/A"
    else:
        product_text = "N/A"

    kb_query = ""
    if brand_profile and brand_profile.brand_tone:
        kb_query += brand_profile.brand_tone + " "
    if competitor_listing.title:
        kb_query += competitor_listing.title[:80]
    kb_query = kb_query.strip()

    knowledge_section = ""
    if session is not None:
        try:
            from pipeline.layers.knowledge_base import search_entries

            kb_entries = search_entries(
                session,
                kb_query or "amazon product image",
                category="prompt_pattern",
                limit=5,
            )
            if kb_entries:
                kb_lines = "\n".join(f"- {e.title}: {e.content}" for e in kb_entries)
                knowledge_section = (
                    "<knowledge_base_insights>\n"
                    + kb_lines
                    + "\n</knowledge_base_insights>\n\n"
                )
        except Exception:
            log.warning(
                "KB search failed for project %s, skipping enrichment",
                project_id,
                exc_info=True,
            )

    if vision_insights:
        knowledge_section += (
            "<competitor_vision_insights>\n"
            + vision_insights
            + "\n</competitor_vision_insights>\n\n"
        )

    # 价格定位信息：影响图片调性（高端 vs 大众）
    if price_analysis is not None:
        pa_parts = []
        if price_analysis.price_position:
            pa_parts.append(
                f"<price_position>{price_analysis.price_position}</price_position>"
            )
        if price_analysis.price_current is not None:
            pa_parts.append(
                f"<price_current>{price_analysis.price_current}</price_current>"
            )
        if price_analysis.competitor_prices:
            pa_parts.append(
                f"<competitor_prices>{price_analysis.competitor_prices}</competitor_prices>"
            )
        if pa_parts:
            knowledge_section += (
                "<price_analysis>\n" + "\n".join(pa_parts) + "\n</price_analysis>\n\n"
            )

    # 促销策略信息：决定是否需要专门的促销贴图 slot
    if promo_analysis is not None:
        pra_parts = []
        if promo_analysis.promo_pattern:
            pra_parts.append(
                f"<promo_pattern>{promo_analysis.promo_pattern}</promo_pattern>"
            )
        if promo_analysis.avg_discount_pct is not None:
            pra_parts.append(
                f"<avg_discount_pct>{promo_analysis.avg_discount_pct}</avg_discount_pct>"
            )
        if promo_analysis.promo_frequency is not None:
            pra_parts.append(
                f"<promo_frequency>{promo_analysis.promo_frequency}</promo_frequency>"
            )
        if pra_parts:
            knowledge_section += (
                "<promo_analysis>\n" + "\n".join(pra_parts) + "\n</promo_analysis>\n\n"
            )

    prompt = _BRIEF_PROMPT.format(
        knowledge_section=knowledge_section,
        brand_text=brand_text,
        product_text=product_text,
        title=competitor_listing.title or "",
        bullets=competitor_listing.bullet_points or "",
        selling_points=competitor_listing.selling_points_map or "",
        description=(competitor_listing.description or "")[:500],
        rating=competitor_listing.rating or "N/A",
        review_count=competitor_listing.review_count or "N/A",
        category_rank=competitor_listing.category_rank or "N/A",
        clusters_text=clusters_text,
        qa_text=qa_text,
    )

    if session is not None:
        try:
            cb = session.query(CustomerBrief).filter_by(project_id=project_id).first()
            if cb is not None:
                cb_section = cb.to_prompt_section()
                if cb_section:
                    prompt += "\n" + cb_section
        except Exception:
            log.warning(
                "CustomerBrief query failed for project %s, skipping",
                project_id,
                exc_info=True,
            )

        try:
            from pipeline.models.project import Project

            project_row = session.query(Project).filter_by(id=project_id).first()
            if project_row and project_row.customer_brief:
                cb_blob = (
                    json.loads(project_row.customer_brief)
                    if isinstance(project_row.customer_brief, str)
                    else project_row.customer_brief
                )
                if isinstance(cb_blob, dict):
                    blob_parts = []
                    for field, label in [
                        ("listing_title", "Listing Title"),
                        ("listing_keywords", "Listing Keywords"),
                        ("listing_bullets", "Listing Bullets"),
                        ("product_dimensions", "Dimensions"),
                        ("product_weight", "Weight"),
                        ("product_material", "Material"),
                        ("product_color", "Color"),
                        ("package_contents", "Package Contents"),
                        ("product_certifications", "Certifications"),
                        ("key_selling_points", "Key Selling Points"),
                        ("differentiation", "Differentiation"),
                        ("target_audience", "Target Audience"),
                        ("customer_pain_points", "Customer Pain Points"),
                        ("audience_scenarios", "Usage Scenarios"),
                        ("primary_color", "Brand Primary Color"),
                        ("brand_voice", "Brand Voice"),
                    ]:
                        val = cb_blob.get(field)
                        if val:
                            blob_parts.append(f"{label}: {val}")

                    image_sources = []
                    ref_paths = cb_blob.get("reference_image_paths", "")
                    if ref_paths:
                        image_sources.extend(
                            [p for p in ref_paths.split(",") if p.strip()]
                        )
                    ref_urls = cb_blob.get("reference_urls", "")
                    if ref_urls:
                        image_sources.extend(
                            [u for u in ref_urls.splitlines() if u.strip()]
                        )
                    if image_sources:
                        style_desc = _extract_style_from_images(image_sources)
                        if style_desc:
                            blob_parts.append(
                                f"Visual Style (from reference images): {style_desc}"
                            )

                    white_bg = cb_blob.get("white_bg_image_path", "")
                    multiangle_raw = cb_blob.get("multiangle_image_paths", "")
                    multiangle = (
                        [p for p in multiangle_raw.split(",") if p.strip()]
                        if multiangle_raw
                        else []
                    )
                    detail_raw = cb_blob.get("detail_closeup_image_paths", "")
                    detail_closeup = (
                        [p for p in detail_raw.split(",") if p.strip()]
                        if detail_raw
                        else []
                    )
                    usage_raw = cb_blob.get("usage_context_image_paths", "")
                    usage_context = (
                        [p for p in usage_raw.split(",") if p.strip()]
                        if usage_raw
                        else []
                    )
                    color_raw = cb_blob.get("color_variant_image_paths", "")
                    color_variants = (
                        [p for p in color_raw.split(",") if p.strip()]
                        if color_raw
                        else []
                    )
                    if (
                        white_bg
                        or multiangle
                        or detail_closeup
                        or usage_context
                        or color_variants
                        or cb_blob.get("packaging_image_path")
                        or cb_blob.get("scale_ref_image_path")
                        or cb_blob.get("inbox_flatlay_image_path")
                    ):
                        product_desc = _analyze_product_images(
                            white_bg,
                            multiangle,
                            detail_closeup_paths=detail_closeup,
                            packaging_path=cb_blob.get("packaging_image_path", ""),
                            scale_ref_path=cb_blob.get("scale_ref_image_path", ""),
                            usage_context_paths=usage_context,
                            inbox_flatlay_path=cb_blob.get(
                                "inbox_flatlay_image_path", ""
                            ),
                            color_variant_paths=color_variants,
                        )
                        if product_desc:
                            blob_parts.insert(
                                0, f"Product Visual Analysis: {product_desc}"
                            )

                    from pipeline.layers.custom_requirement_parser import (
                        build_user_requirement_lock,
                        parse_custom_requirements,
                    )

                    custom_requirements = parse_custom_requirements(cb_blob)
                    user_lock = build_user_requirement_lock(custom_requirements)
                    if user_lock:
                        blob_parts.insert(0, user_lock)

                    if blob_parts:
                        prompt += "\n\n--- Customer Product Info ---\n" + "\n".join(
                            blob_parts
                        )
        except Exception:
            log.warning(
                "customer_brief blob inject failed for project %s, skipping",
                project_id,
                exc_info=True,
            )

    raw = _call_gemini(prompt)

    parsed = _parse_json_robust(raw)
    if parsed is None:
        log.warning(
            "generate_brief: JSON parse failed for project %s (raw[:200]=%r), retrying once",
            project_id,
            raw[:200],
        )
        retry_prompt = (
            prompt
            + "\n\nIMPORTANT: Your previous response could not be parsed as JSON. Return ONLY a valid JSON object, no markdown, no code fences."
        )
        raw = _call_gemini(retry_prompt)
        parsed = _parse_json_robust(raw)

    if not (isinstance(parsed, dict) and "slots" in parsed):
        log.warning(
            "generate_brief: Gemini returned no slots for project %s, using default brief",
            project_id,
        )
        parsed = json.loads(_DEFAULT_BRIEF)
        raw = _DEFAULT_BRIEF

    brief_json = json.dumps(parsed) if not isinstance(raw, str) else json.dumps(parsed)

    data = parsed
    parsed_slots = data.get("slots", [])

    if not parsed_slots:
        log.warning("generate_brief: 0 slots returned for project %s", project_id)
        return []

    briefs: list[ImageBrief] = []
    for i, slot_data in enumerate(parsed_slots):
        b = ImageBrief(
            project_id=project_id,
            slot_index=i,
            brief_json=json.dumps(slot_data),
            source_analysis_ids=json.dumps([]),
            pipeline_run_id=pipeline_run_id,
            tenant_id=tenant_id,
        )
        briefs.append(b)

    if session is not None:
        for b in briefs:
            session.add(b)
        session.commit()

    return briefs
