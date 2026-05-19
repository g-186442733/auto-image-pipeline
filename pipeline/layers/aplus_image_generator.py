import json
import logging
import re
import textwrap
from pathlib import Path

from pipeline.layers.image_path_security import filter_external_image_paths
from pipeline.models.aplus_content import APlusContent

log = logging.getLogger(__name__)


# 需要专属宽幅图的模块类型：1:1 listing 图比例不适用
_WIDE_MODULE_TYPES = {"HERO", "LIFESTYLE", "BRAND_STORY"}

# Feature Tile 模块类型：需要 1:1 方形图，主题由 module.headline 驱动（T2 生图）
_GENERATE_TILE_TYPES = {"BENEFIT", "DETAIL", "COMPARISON", "CROSS_SELL"}

# 复用 slot 图的模块类型：当前为空。A+ COMPARISON / CROSS_SELL 必须生成符合模块意图的专属图片，
# 不能直接回填单张 Listing 图，否则会通过技术分数但完全不符合 A+ 模块语义。
_REUSE_SLOT_TYPES: set[str] = set()

# 向后兼容：合并两类 Tile 模块
_TILE_MODULE_TYPES = _GENERATE_TILE_TYPES | _REUSE_SLOT_TYPES

# 可直接复用 slot_index 所指 1:1 图的模块类型（保留向后兼容名）
_REUSE_MODULE_TYPES = _TILE_MODULE_TYPES

# 宽幅模块使用 1536x1024（OpenAI gpt-image 官方支持的横向尺寸，实际返回与请求一致）
_WIDE_SIZE = "1536x1024"

# Feature Tile 默认尺寸（1:1 方图）
_TILE_SIZE = "1024x1024"
_MAX_APLUS_IMAGE_BYTES = 2 * 1024 * 1024
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LANGUAGE_POLICY = (
    "Marketplace language policy: Amazon US English-only. "
    "Never render Chinese characters, CJK characters, bilingual headings, translated Chinese copy, or non-English labels. "
    "Any visible text must be concise, correctly spelled English and mobile-readable."
)


def _strip_cjk_text(value: str) -> str:
    text = (value or "").strip()
    if _CJK_RE.search(text):
        return ""
    return text


def _dedupe_paths(paths: list[str] | tuple[str, ...] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths or []:
        if path and path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Avenir Next.ttc",
    "/System/Library/Fonts/Supplemental/Helvetica Neue.ttc",
    "/Library/Fonts/Arial.ttf",
)
_BATTERY_24H_RE = re.compile(
    r"\b(?:up\s+to\s+)?24\s*(?:-|\s)?(?:h|hr|hrs|hour|hours)\b"
    r"(?=[^\n.;,]*(?:playtime|play\s*time|battery|charge|charging|listening|runtime))"
    r"|\b(?:playtime|play\s*time|battery|charge|charging|listening|runtime)\b"
    r"(?=[^\n.;,]*(?:up\s+to\s+)?24\s*(?:-|\s)?(?:h|hr|hrs|hour|hours)\b)",
    re.IGNORECASE,
)


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = _FONT_CANDIDATES if bold else tuple(
        path for path in _FONT_CANDIDATES if "Bold" not in path
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _is_claim_supported(source_text: str, required_terms: tuple[str, ...]) -> bool:
    normalized = source_text.lower()
    return all(term in normalized for term in required_terms)


def _has_24h_battery_fact(source_text: str) -> bool:
    return bool(_BATTERY_24H_RE.search(source_text)) or _is_claim_supported(
        source_text, ("24", "playtime")
    )


def _comparison_claim_rows(brand_ctx: dict) -> list[tuple[str, str, str]]:
    source_text = "\n".join(
        str(brand_ctx.get(key) or "")
        for key in ("listing_title", "listing_bullets", "product_usp")
    )
    rows: list[tuple[str, str, str]] = []
    if _is_claim_supported(source_text, ("noise",)):
        rows.append(("Noise Control", "Noise cancelling", "Basic isolation"))
    if _has_24h_battery_fact(source_text):
        rows.append(("Battery Life", "Up to 24 hours", "Often less"))
    if _is_claim_supported(source_text, ("comfort",)) or _is_claim_supported(source_text, ("cushion",)):
        rows.append(("Comfort", "Plush over-ear fit", "Standard padding"))
    if _is_claim_supported(source_text, ("usb-c",)) or _is_claim_supported(source_text, ("usb c",)):
        rows.append(("Charging", "USB-C charging", "Varies by model"))
    if not rows:
        rows.append(("Design", "Verified product details", "Generic design"))
    return rows[:3]


def _comparison_output_path(module: APlusContent) -> Path:
    out_dir = Path("data/images/aplus_programmatic")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"comparison_{module.project_id}_{module.id}.jpg"


def _draw_wrapped_text(draw, xy: tuple[int, int], text: str, font, fill, width: int, line_gap: int = 8) -> int:
    x, y = xy
    lines: list[str] = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(paragraph, width=width) or [""]
        lines.extend(wrapped)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def _render_comparison_module_image(module: APlusContent, brand_ctx: dict, session) -> None:
    from PIL import Image, ImageDraw

    try:
        rows = _comparison_claim_rows(brand_ctx)
        ref_image_paths = _collect_ref_image_paths(brand_ctx, "INT_COMPARISON")
        title_font = _font(52, bold=True)
        header_font = _font(38, bold=True)
        row_font = _font(34, bold=True)
        value_font = _font(30)
        small_font = _font(24)

        image = Image.new("RGB", (1024, 1024), "#f7f7f4")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((42, 40, 982, 984), radius=34, fill="#ffffff", outline="#d7d7d2", width=3)
        draw.text((88, 72), "Why It Stands Out", font=title_font, fill="#111111")
        draw.text((118, 150), "This Headphone", font=header_font, fill="#111111")
        draw.text((610, 150), "Typical Headphones", font=header_font, fill="#333333")
        draw.line((512, 128, 512, 900), fill="#d8d8d4", width=3)
        if ref_image_paths:
            try:
                with Image.open(ref_image_paths[0]) as ref_img:
                    thumb = ref_img.convert("RGBA")
                    thumb.thumbnail((270, 170), Image.Resampling.LANCZOS)
                    thumb_x = 118 + (330 - thumb.width) // 2
                    thumb_y = 205 + (150 - thumb.height) // 2
                    draw.rounded_rectangle((104, 190, 466, 370), radius=22, fill="#fafafa", outline="#deded8", width=2)
                    image.paste(thumb, (thumb_x, thumb_y), thumb)
            except Exception as exc:
                log.warning("Comparison product thumbnail failed module=%s: %s", module.id, exc)
        y = 405
        for label, this_value, typical_value in rows:
            draw.rounded_rectangle((88, y - 18, 936, y + 126), radius=20, fill="#f1f2ef")
            draw.text((118, y), label, font=row_font, fill="#111111")
            _draw_wrapped_text(draw, (118, y + 52), this_value, value_font, "#111111", 20)
            _draw_wrapped_text(draw, (610, y + 52), typical_value, value_font, "#555555", 20)
            y += 158
        draw.text(
            (88, 914),
            "Amazon US comparison based only on provided product facts.",
            font=small_font,
            fill="#555555",
        )
        out_path = _comparison_output_path(module)
        image.save(out_path, quality=94, optimize=True)
        _normalize_image_size(str(out_path), _TILE_SIZE)
        module.image_path = str(out_path)
        module.image_prompt = (
            "Programmatic Amazon US English-only comparison card with real product thumbnail. "
            "Claims are selected only from listing title, bullets, and product USP. "
            f"Rows: {rows}"
        )
        module.image_size = _TILE_SIZE
        module.reference_image_paths = ",".join(ref_image_paths)
        session.add(module)
        session.commit()
    except Exception:
        log.error("Programmatic comparison render failed module=%s", module.id, exc_info=True)
        session.rollback()
        session.expire_all()
        raise


def _parse_size(size: str) -> tuple[int, int]:
    width, height = size.split("x", 1)
    return int(width), int(height)


def _normalize_image_size(image_path: str | None, size: str) -> None:
    """Force generated A+ assets to declared pixels and Amazon's 2MB limit."""
    if not image_path:
        return
    path = Path(image_path)
    if not path.exists():
        return
    target = _parse_size(size)
    try:
        from PIL import Image

        with Image.open(path) as img:
            normalized = img.convert("RGB")
            if normalized.size != target:
                normalized = normalized.resize(target, Image.Resampling.LANCZOS)
            normalized.save(path)
        if path.stat().st_size <= _MAX_APLUS_IMAGE_BYTES:
            return
        quality = 92
        while quality >= 72:
            with Image.open(path) as img:
                img.convert("RGB").save(path, format="JPEG", quality=quality, optimize=True)
            if path.stat().st_size <= _MAX_APLUS_IMAGE_BYTES:
                return
            quality -= 5
    except Exception:
        log.warning("A+ image size normalization failed path=%s size=%s", image_path, size, exc_info=True)


# ── ELASTIC 字段默认值：brand_ctx 缺失时用合理默认填充，保证 prompt 始终完整 ──
_ELASTIC_DEFAULTS = {
    "photo_style": "studio commercial photography",
    "model_type": "no_model",
    "scene_preference": "neutral seamless backdrop",
    "composition_preference": "centered composition",
    "material_texture": "clean smooth surface",
}


def _elastic(brand_ctx: dict, key: str) -> str:
    """从 brand_ctx 中取 ELASTIC 字段，缺失/空值时回退到默认值"""
    val = (brand_ctx or {}).get(key)
    if val:
        return str(val)
    return _ELASTIC_DEFAULTS.get(key, "")


def _build_elastic_block(brand_ctx: dict) -> dict:
    """构造 ELASTIC 字段块，供六槽位框架按槽位使用"""
    return {
        "photo_style": _elastic(brand_ctx, "photo_style"),
        "model_type": _elastic(brand_ctx, "model_type"),
        "scene_preference": _elastic(brand_ctx, "scene_preference"),
        "composition_preference": _elastic(brand_ctx, "composition_preference"),
        "material_texture": _elastic(brand_ctx, "material_texture"),
    }


def _build_image_prompt(
    module: APlusContent,
    brand_ctx: dict,
    used_compositions: list[str] | None = None,
    constraint_prefix: str = "",
) -> str:
    """
    构建 A+ 模块图 Prompt（六槽位框架）：
        [subject] + [style] + [lighting] + [composition] + [mood] + [technical]

    - HERO/LIFESTYLE/BRAND_STORY：宽幅 lifestyle 场景，禁止文字叠加，底部 20% 安全区
    - BENEFIT/DETAIL（Feature Tile）：1:1 方图，subject 由 module.headline 驱动，
      body_text 提炼为 mood 关键词，禁止图内文字
    """
    listing_title = (brand_ctx or {}).get("listing_title") or "the product"
    brand_tone = (brand_ctx or {}).get("brand_tone", "")
    color_system = (brand_ctx or {}).get("color_system", "")

    elastic = _build_elastic_block(brand_ctx)
    module_type = (module.module_type or "").upper()
    headline = _strip_cjk_text(module.headline or "")
    body_text = _strip_cjk_text(module.body_text or "")

    # 通用槽位：style / lighting / technical
    style_slot = (
        f"style: {elastic['photo_style']}, {brand_tone} brand tone"
        if brand_tone
        else f"style: {elastic['photo_style']}"
    )
    if elastic["material_texture"]:
        style_slot += f", material: {elastic['material_texture']}"

    # 按模块类型注入专业灯光方案，覆盖六种常见商业摄影场景
    if module_type == "HERO":
        lighting_slot = (
            "lighting: key light 1000W LED at 45° camera-left, "
            "fill light 300W LED at 45° camera-right, "
            "rim light 500W LED behind subject, pure white seamless backdrop"
        )
    elif module_type == "LIFESTYLE":
        lighting_slot = (
            "lighting: soft natural window light from upper-left, "
            "fill reflector at right, warm golden-hour color temperature 5500K"
        )
    elif module_type == "BRAND_STORY":
        lighting_slot = (
            "lighting: cinematic soft box from upper-left, "
            "subtle rim light for depth, warm storytelling atmosphere 4500K"
        )
    elif module_type in ("BENEFIT", "COMPARISON", "CROSS_SELL"):
        lighting_slot = (
            "lighting: soft box 45° left, fill light at right, "
            "clean neutral product lighting, no harsh shadows"
        )
    elif module_type == "DETAIL":
        lighting_slot = (
            "lighting: ring flash macro lighting, even diffused illumination, "
            "deep focus, texture-revealing side light, no harsh shadows"
        )
    else:
        lighting_slot = (
            "lighting: professional three-point lighting, "
            "key light at 45°, fill light, rim light"
        )

    # ── HERO / LIFESTYLE / BRAND_STORY：宽幅 lifestyle 场景 ───────────────────
    if module_type in _WIDE_MODULE_TYPES:
        # 读取 Cosmo F2 所需的受众与核心卖点（有值才追加，避免空字符串污染 prompt）
        target_audience = (brand_ctx or {}).get("target_audience") or ""
        product_usp = (brand_ctx or {}).get("product_usp") or ""

        # subject 槽位：以产品为核心，HERO/LIFESTYLE 注入受众+USP（Cosmo F2）
        if module_type == "HERO":
            subject_slot = (
                f"subject: hero banner of {listing_title}, "
                f"product centered with premium presence"
            )
            if target_audience:
                subject_slot += f", used by {target_audience}"
            if product_usp:
                subject_slot += f", highlighting {product_usp}"
        elif module_type == "LIFESTYLE":
            subject_slot = (
                f"subject: real person actively wearing and using {listing_title} in an authentic everyday environment, not a product-only render"
            )
            if target_audience:
                subject_slot += f", used by {target_audience}"
        else:  # BRAND_STORY：品牌故事不适合打人群标签
            subject_slot = (
                f"subject: emotional Amazon A+ brand story scene for {listing_title}, premium quiet-focus moment, craftsmanship, trust, and calm productivity; show a distinct narrative moment such as preparing for focused work or thoughtful travel, not the same wearing-use scene as Lifestyle and not a plain product display"
            )

        if module_type == "LIFESTYLE":
            composition_slot = (
                "composition: wide horizontal 16:9 framing, visible person head-and-shoulders or travel/office context, headphones visibly worn on ears, natural environment depth, keep the primary product and wearer naturally inside the frame without obvious edge cut-off, bottom 20% safe zone reserved for downstream text overlay"
            )
        elif module_type == "BRAND_STORY":
            composition_slot = (
                "composition: wide horizontal 16:9 framing, narrative brand moment with product integrated naturally, include environmental cues for premium trust and craftsmanship, avoid duplicating the Lifestyle person-wearing-headphones composition, keep hero subject away from accidental edge cut-off, bottom 20% safe zone reserved for downstream text overlay"
            )
        else:
            composition_slot = (
                f"composition: {elastic['composition_preference']}, "
                f"wide horizontal framing with the full product completely inside the canvas, "
                f"scene set in {elastic['scene_preference']}, centered product hero composition, "
                f"minimum 8-12% clean white margin on all four sides, "
                f"bottom 20% safe zone reserved for downstream text overlay"
            )
        if elastic["model_type"] and elastic["model_type"] != "no_model":
            composition_slot += f", featuring {elastic['model_type']} model"

        # mood 槽位：根据品牌色系 + 模块氛围
        mood_parts = ["mood: lifestyle photography aesthetic"]
        if color_system:
            mood_parts.append(f"color palette {color_system}")
        if module_type == "BRAND_STORY":
            mood_parts.append("warm, authentic, heritage-driven atmosphere")
        elif module_type == "LIFESTYLE":
            mood_parts.append("vibrant everyday-use atmosphere")
        else:
            mood_parts.append("premium aspirational atmosphere")
        mood_slot = ", ".join(mood_parts)

        # 注入 listing_bullets 前2条卖点，强化 Cosmo F3 场景相关性
        raw_bullets = (brand_ctx or {}).get("listing_bullets") or ""
        if raw_bullets:
            bullet_lines = [
                l.strip().lstrip("-•").strip()
                for l in raw_bullets.split("\n")
                if l.strip()
            ]
            top_bullets = bullet_lines[:2]
            if top_bullets:
                mood_slot += ", conveying: " + "; ".join(top_bullets)

        technical_slot = (
            f"technical: 1536x1024 wide format, {_LANGUAGE_POLICY} "
            "85mm equivalent lens, f/8 aperture, ISO 100, "
            "correct exposure, accurate color reproduction, no overexposure, no muddy tones, "
            "magazine-quality commercial photography, hyperrealistic material texture, "
            "subject positioned in upper 60% of frame, "
            "full product and its soft shadow fully visible, no crop, no edge clipping, no part touching canvas boundaries, "
            "strong visual impact, high commercial appeal, "
            "no text overlays, no embedded captions, no logos baked into image, "
            "high resolution, sharp focus"
        )
        if used_compositions:
            avoid_str = "; ".join(used_compositions[:3])
            technical_slot += f", avoid duplicating composition: {avoid_str}"

        prompt = " | ".join(
            [
                subject_slot,
                style_slot,
                lighting_slot,
                composition_slot,
                mood_slot,
                technical_slot,
            ]
        )
        return f"{constraint_prefix}\n\n{prompt}" if constraint_prefix else prompt

    # ── BENEFIT / DETAIL（Feature Tile）：1:1 方图，headline 驱动主题 ─────────
    if module_type in _TILE_MODULE_TYPES:
        if module_type == "BENEFIT":
            subject_slot = (
                f"subject: benefit module for {listing_title}, show the headphones with 3 clear visual benefit zones for noise cancellation, plush comfort, and 24-hour battery life; use simple icons or short English labels only if needed for the BENEFIT module"
            )
        elif module_type == "DETAIL":
            subject_slot = (
                f"subject: extreme macro detail module for {listing_title}, close-up crop of USB-C port, control buttons, hinge, and soft ear cushion texture; the product detail must fill most of the square frame"
            )
        elif module_type == "COMPARISON":
            subject_slot = (
                f"subject: deterministic Amazon US comparison module for {listing_title}; two-column layout with left column labeled 'This Headphone' and right column labeled 'Typical Headphones'; use only 2 or 3 verified advantage rows, large English-only text, no Chinese, no competitor brand names, no unsupported claims"
            )
        elif module_type == "CROSS_SELL":
            subject_slot = (
                f"subject: cross-sell module for {listing_title}, organized bundle-style grid with the headphones plus only real referenced accessories such as carrying case and USB-C cable; do not invent extra products"
            )
        elif headline:
            subject_slot = (
                f'subject: visual representation of "{headline}" '
                f"applied to {listing_title}, "
                f"feature-focused tile illustrating this exact benefit/detail"
            )
        else:
            subject_slot = (
                f"subject: feature tile showcasing {listing_title} "
                f"({module_type.lower()} module)"
            )

        # mood 槽位：从 body_text 中提取关键词（截断防止过长污染 prompt）
        mood_parts = [f"mood: clean {module_type.lower()}-focused atmosphere"]
        if body_text:
            keywords = body_text.replace("\n", " ").strip()
            if len(keywords) > 200:
                keywords = keywords[:200] + "..."
            mood_parts.append(f"context keywords: {keywords}")
        if color_system:
            mood_parts.append(f"color palette {color_system}")
        mood_slot = ", ".join(mood_parts)

        if module_type == "DETAIL":
            composition_slot = (
                "composition: intentional macro crop, 1:1 square composition, target detail fills 70% of frame, the featured port/button/cushion detail must remain fully readable and not be cut off by the image edge, shallow but readable depth of field, neutral clean backdrop"
            )
        elif module_type == "COMPARISON":
            composition_slot = (
                "composition: deterministic two-column comparison card, 1024 square canvas, 2-3 large rows only, keep all text and product/benchmark elements inside a clear inner safe area with no edge clipping, minimum 36px equivalent text, high contrast, no bullet list, no tiny text, English-only headings and labels, product advantage on left, generic alternative silhouette or abstract benchmark on right"
            )
        elif module_type == "CROSS_SELL":
            composition_slot = (
                "composition: three-item product grid, main headphones largest, real referenced accessories smaller, balanced spacing for A+ cross-sell module, every item fully visible with clean inner padding"
            )
        elif module_type == "BENEFIT":
            composition_slot = (
                "composition: benefit infographic tile, product centered with three visual benefit callouts, clean inner safe area so icons/text/product do not touch or clip at canvas edges, mobile-readable hierarchy"
            )
        else:
            composition_slot = (
                f"composition: {elastic['composition_preference']}, "
                f"1:1 square composition, 20% margin around subject, "
                f"backdrop {elastic['scene_preference']}, "
                f"product clearly isolated for tile-grid display"
            )

        technical_slot = (
            f"technical: 1024x1024 square format, {_LANGUAGE_POLICY} "
            "85mm equivalent lens, f/5.6 aperture, ISO 100, "
            "correct exposure, accurate color reproduction, no overexposure, no muddy tones, "
            "product photography studio quality, hyperrealistic material texture, "
            "subject positioned in upper 60% of frame, "
            "strong visual impact, high commercial appeal, "
            "text allowed only for BENEFIT or COMPARISON modules when it is short, English-only, correctly spelled, and mobile-readable; no Chinese/CJK, no bilingual text, no small bullet lists; otherwise no captions or labels baked into pixels, "
            "high resolution, sharp focus on the feature subject"
        )

        prompt = " | ".join(
            [
                subject_slot,
                style_slot,
                lighting_slot,
                composition_slot,
                mood_slot,
                technical_slot,
            ]
        )
        return f"{constraint_prefix}\n\n{prompt}" if constraint_prefix else prompt

    # ── 兜底：未知模块类型 ──────────────────────────────────────────────────
    fallback_subject = f"subject: A+ module ({module_type}) for {listing_title}" + (
        f", concept: {headline}" if headline else ""
    )
    return " | ".join(
        [
            fallback_subject,
            style_slot,
            lighting_slot,
            f"composition: {elastic['composition_preference']}, scene {elastic['scene_preference']}",
            f"mood: {color_system or 'brand-aligned'} atmosphere",
            f"technical: 85mm lens, f/8, ISO 100, {_LANGUAGE_POLICY} no text overlays, hyperrealistic, high resolution",
        ]
    )


def _fetch_product_context(project_id: int, session) -> dict:
    """
    拉取项目级品牌/商品上下文。

    正确路径：Project → ProductProfile(filter project_id) → brand_profile_id → BrandProfile
    （Project 模型不含 brand_profile_id，必须通过 ProductProfile 中间表查询）

    返回字段：listing_title / brand_tone / color_system + 5 个 ELASTIC 字段
    （photo_style / model_type / scene_preference / composition_preference / material_texture）

    任何中间环节缺失时，对应字段返回空字符串；项目不存在时返回空 dict。
    """
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.models.product_profile import ProductProfile
    from pipeline.models.project import Project

    ctx: dict = {
        "listing_title": "",
        "brand_tone": "",
        "color_system": "",
        # ELASTIC 字段：飞轮可写入，缺失时由 _elastic() 兜底默认值
        "photo_style": "",
        "model_type": "",
        "scene_preference": "",
        "composition_preference": "",
        "material_texture": "",
        # 产品参考图路径（用于 adapter.edit，保证 A+ 图与套图外观一致）
        "white_bg_image_path": "",
        "multiangle_image_paths": [],
        "packaging_image_path": "",
        "inbox_flatlay_image_path": "",
        "detail_closeup_image_paths": [],
        "scale_ref_image_path": "",
        "usage_context_image_paths": [],
        "color_variant_image_paths": [],
        # Cosmo F2/F3 注入来源：受众信号 / 核心卖点 / Bullet 卖点
        "target_audience": "",
        "product_usp": "",
        "listing_bullets": "",
    }

    proj = session.query(Project).filter_by(id=project_id).first()
    if proj is None:
        return ctx

    # listing_title 从 project.customer_brief JSON 字段读取（customer_briefs 表从未写入）
    if proj.customer_brief:
        try:
            brief_data = json.loads(proj.customer_brief)
            ctx["listing_title"] = (
                brief_data.get("listing_title") or brief_data.get("product_name") or ""
            )
            ctx["white_bg_image_path"] = brief_data.get("white_bg_image_path") or ""
            raw_multi = brief_data.get("multiangle_image_paths") or ""
            ctx["multiangle_image_paths"] = (
                [p.strip() for p in raw_multi.split(",") if p.strip()]
                if isinstance(raw_multi, str)
                else list(raw_multi)
            )
            ctx["target_audience"] = brief_data.get("target_audience") or ""
            ctx["product_usp"] = brief_data.get("product_usp") or ""
            ctx["listing_bullets"] = brief_data.get("listing_bullets") or ""
            ctx["packaging_image_path"] = brief_data.get("packaging_image_path") or ""
            ctx["inbox_flatlay_image_path"] = (
                brief_data.get("inbox_flatlay_image_path") or ""
            )
            ctx["scale_ref_image_path"] = brief_data.get("scale_ref_image_path") or ""
            for multi_key in (
                "detail_closeup_image_paths",
                "usage_context_image_paths",
                "color_variant_image_paths",
            ):
                raw = brief_data.get(multi_key) or ""
                ctx[multi_key] = (
                    [p.strip() for p in raw.split(",") if p.strip()]
                    if isinstance(raw, str)
                    else list(raw)
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # 2) BrandProfile：通过 ProductProfile 中间表查询
    product_profile = (
        session.query(ProductProfile).filter_by(project_id=project_id).first()
    )
    brand_profile = None
    if product_profile and product_profile.brand_profile_id:
        brand_profile = (
            session.query(BrandProfile)
            .filter_by(id=product_profile.brand_profile_id)
            .first()
        )

    if brand_profile is None:
        # 中间环节缺失：返回当前 ctx（listing_title 可能已填充，品牌字段为空）
        return ctx

    # 3) FROZEN 字段
    ctx["brand_tone"] = getattr(brand_profile, "brand_tone", "") or ""
    ctx["color_system"] = getattr(brand_profile, "color_system", "") or ""

    # 4) ELASTIC 字段（5 个）
    ctx["photo_style"] = getattr(brand_profile, "photo_style", "") or ""
    ctx["model_type"] = getattr(brand_profile, "model_type", "") or ""
    ctx["scene_preference"] = getattr(brand_profile, "scene_preference", "") or ""
    ctx["composition_preference"] = (
        getattr(brand_profile, "composition_preference", "") or ""
    )
    ctx["material_texture"] = getattr(brand_profile, "material_texture", "") or ""

    return ctx


def _build_style_anchor(brand_ctx: dict) -> str:
    """生成 listing 级风格锚点，注入每个模块 prompt，保证同页面视觉统一。"""
    color_system = brand_ctx.get("color_system", "")
    brand_tone = brand_ctx.get("brand_tone", "")
    parts = ["consistent visual style across all modules"]
    if color_system:
        parts.append(f"color grading anchored to {color_system}")
    if brand_tone:
        parts.append(f"{brand_tone} brand aesthetic")
    parts.append(
        "same lighting color temperature throughout, unified product color rendering"
    )
    return ", ".join(parts)


_INTENT_REF_TYPES: dict[str, list[str]] = {
    "INT_HERO": ["white_bg_image_path"],
    "INT_LIFESTYLE": ["white_bg_image_path", "usage_context_image_paths"],
    "INT_DETAIL": ["detail_closeup_image_paths", "multiangle_image_paths"],
    "INT_INFOGRAPHIC": ["detail_closeup_image_paths", "scale_ref_image_path"],
    "INT_COMPARISON": ["white_bg_image_path", "color_variant_image_paths"],
    "INT_PACKAGING": ["packaging_image_path", "inbox_flatlay_image_path"],
}
_INTENT_REF_FALLBACK = ["white_bg_image_path"]

_MODULE_TYPE_TO_INTENT: dict[str, str] = {
    "HERO": "INT_HERO",
    "LIFESTYLE": "INT_LIFESTYLE",
    "BRAND_STORY": "INT_LIFESTYLE",
    "DETAIL": "INT_DETAIL",
    "BENEFIT": "INT_INFOGRAPHIC",
    "COMPARISON": "INT_COMPARISON",
    "CROSS_SELL": "INT_COMPARISON",
}


def _collect_ref_image_paths(
    product_context: dict, intent_tag: str | None = None
) -> list[str]:
    keys = _INTENT_REF_TYPES.get(intent_tag or "", _INTENT_REF_FALLBACK)
    candidates: list[str] = []
    for k in keys:
        val = product_context.get(k) or ""
        if isinstance(val, list):
            candidates.extend(str(p) for p in val if p)
        elif val:
            candidates.append(str(val))
    paths = _dedupe_paths(filter_external_image_paths(candidates))
    if not paths:
        fallback = product_context.get("white_bg_image_path") or ""
        paths = _dedupe_paths(filter_external_image_paths([str(fallback)] if fallback else []))
    return paths


def _generate_wide_module_image(
    module, prompt: str, adapter, session, ref_image_paths: list[str]
) -> None:
    """宽幅模块生图：必须传入产品参考图，调用 adapter.edit 保持产品外观；无参考图时直接报错。"""
    if not ref_image_paths:
        raise ValueError(
            f"宽幅模块 {module.id} 无产品参考图，拒绝生图（需要 white_bg_image_path）"
        )
    if not hasattr(adapter, "edit"):
        raise ValueError(f"adapter {type(adapter).__name__} 不支持 edit 接口")
    log.info(
        "宽幅生图 module=%s type=%s ref_count=%d",
        module.id,
        module.module_type,
        len(ref_image_paths),
    )
    # 拼接 PRESERVE 前缀：要求 AI 严格保持产品外形、品牌色、Logo 位置
    preserve_prefix = (
        "PRESERVE EXACTLY: product shape, brand colors, logo placement, "
        "product proportions. "
        "DO NOT alter: product identity, color scheme, structural elements. "
    )
    prompt_with_preserve = preserve_prefix + prompt
    try:
        result = adapter.edit(
            ref_image_paths, prompt_with_preserve, params={"size": _WIDE_SIZE}
        )
        _normalize_image_size(result.image_path, _WIDE_SIZE)
        module.image_path = result.image_path
        module.image_prompt = prompt_with_preserve
        module.image_size = _WIDE_SIZE
        module.reference_image_paths = ",".join(ref_image_paths)
        session.add(module)
        session.commit()
        log.info("宽幅图生成完成 module=%s path=%s", module.id, result.image_path)
    except Exception as exc:
        log.error("宽幅图生成失败 module=%s: %s", module.id, exc)
        session.rollback()
        session.expire_all()
        raise


def _generate_tile_module_image(
    module: APlusContent,
    brand_ctx: dict,
    adapter,
    session,
    ref_image_paths: list | None = None,
    prompt_override: str | None = None,
) -> None:
    """方形 A+ 模块：生成 1024x1024 方形图并持久化。

    传入 ref_image_paths 时走 adapter.edit，让 AI 基于真实产品图生成，
    保证方形 A+ 图的产品外观与实物一致；产品事实模块无参考图时直接失败。
    """
    prompt = prompt_override or _build_image_prompt(
        module, brand_ctx, constraint_prefix=brand_ctx.get("constraint_prefix", "")
    )
    log.info(
        "生成 Feature Tile 图 module=%s type=%s size=%s",
        module.id,
        module.module_type,
        _TILE_SIZE,
    )
    preserve_prefix = (
        "PRESERVE EXACTLY: product shape, brand colors, logo placement, "
        "product proportions. "
        "DO NOT alter: product identity, color scheme, structural elements. "
    )
    try:
        if ref_image_paths:
            result = adapter.edit(
                ref_image_paths, preserve_prefix + prompt, params={"size": _TILE_SIZE}
            )
        else:
            try:
                from pipeline.layers.delivery_status import is_product_fact_aplus_module

                product_fact_required = is_product_fact_aplus_module(module.module_type)
            except Exception:
                product_fact_required = False
            if product_fact_required:
                raise ValueError(
                    f"A+ product-fact tile module {module.id} missing real reference images"
                )
            result = adapter.generate(prompt, params={"size": _TILE_SIZE})
        _normalize_image_size(result.image_path, _TILE_SIZE)
        module.image_path = result.image_path
        module.image_prompt = (preserve_prefix + prompt) if ref_image_paths else prompt
        module.image_size = _TILE_SIZE
        if ref_image_paths:
            module.reference_image_paths = ",".join(ref_image_paths)
        session.add(module)
        session.commit()
        log.info(
            "Feature Tile 图生成完成 module=%s path=%s", module.id, result.image_path
        )
    except Exception as exc:
        log.error("Feature Tile 图生成失败 module=%s: %s", module.id, exc)
        session.rollback()
        session.expire_all()
        raise


def _backfill_reuse_module(module: APlusContent, session) -> None:
    """COMPARISON/CROSS_SELL 模块：从 PromptAsset 回填 slot_index 对应的 image_path"""
    from pipeline.models.prompt_asset import PromptAsset

    slot_idx = module.slot_index
    if slot_idx is None:
        log.warning(
            "回填跳过 module=%s（%s）：slot_index 为 None",
            module.id,
            module.module_type,
        )
        return

    asset = (
        session.query(PromptAsset)
        .filter_by(project_id=module.project_id, slot_index=slot_idx)
        .order_by(PromptAsset.id.desc())
        .first()
    )

    if asset is None or asset.image_path is None:
        log.warning(
            "回填跳过 module=%s（%s）：slot_index=%s 无对应 PromptAsset 图片",
            module.id,
            module.module_type,
            slot_idx,
        )
        module.image_path = None
        module.image_size = _TILE_SIZE
        session.add(module)
        session.commit()
        return

    module.image_path = asset.image_path
    module.image_size = _TILE_SIZE
    session.add(module)
    session.commit()
    log.info(
        "回填完成 module=%s（%s）slot_index=%s → %s",
        module.id,
        module.module_type,
        slot_idx,
        asset.image_path,
    )


def generate_single(
    aplus_content_id: int, session=None, adapter=None
) -> APlusContent | None:
    """重新生成单个 A+ 模块的图（供 QA Gate 重试调用）。

    根据 module_type 选择对应生图分支：
        - 宽幅类：调用 adapter.generate(_WIDE_SIZE)
        - Tile 生图类：复用 _generate_tile_module_image
        - Tile 复用类：复用 _backfill_reuse_module
    失败时抛出异常，让 QA Gate 记录失败并停止无效重试。
    """
    own_session = session is None
    if own_session:
        from pipeline.models.base import get_session

        session = get_session()
    if adapter is None:
        from pipeline.adapters.gpt_image_adapter import GptImageAdapter

        adapter = GptImageAdapter()

    try:
        module = session.query(APlusContent).filter_by(id=aplus_content_id).first()
        if module is None:
            log.warning("generate_single: APlusContent id=%s 不存在", aplus_content_id)
            return None

        product_context = _fetch_product_context(module.project_id, session)
        mtype = (module.module_type or "").upper()

        if mtype in _WIDE_MODULE_TYPES:
            intent_tag = _MODULE_TYPE_TO_INTENT.get(mtype)
            ref_image_paths = _collect_ref_image_paths(product_context, intent_tag)
            prompt = module.image_prompt or _build_image_prompt(module, product_context)
            try:
                _generate_wide_module_image(
                    module,
                    prompt,
                    adapter,
                    session,
                    ref_image_paths,
                )
            except Exception as exc:
                log.error("generate_single 宽幅图失败 id=%s: %s", aplus_content_id, exc)
                session.rollback()
                raise
        elif mtype in _GENERATE_TILE_TYPES:
            if mtype == "COMPARISON":
                _render_comparison_module_image(module, product_context, session)
            else:
                intent_tag = _MODULE_TYPE_TO_INTENT.get(mtype)
                ref_image_paths = _collect_ref_image_paths(product_context, intent_tag)
                prompt_override = module.image_prompt or None
                _generate_tile_module_image(
                    module,
                    product_context,
                    adapter,
                    session,
                    ref_image_paths,
                    prompt_override=prompt_override,
                )
        elif mtype in _REUSE_SLOT_TYPES:
            _backfill_reuse_module(module, session)
        else:
            log.warning(
                "generate_single: 未知 module_type=%s id=%s", mtype, aplus_content_id
            )

        return module
    finally:
        if own_session:
            session.close()


def generate_aplus_images(project_id: int, session, adapter=None) -> list[APlusContent]:
    if adapter is None:
        from pipeline.adapters.gpt_image_adapter import GptImageAdapter

        adapter = GptImageAdapter()

    modules: list[APlusContent] = (
        session.query(APlusContent)
        .filter_by(project_id=project_id)
        .order_by(APlusContent.position_index)
        .all()
    )

    if not modules:
        log.warning("generate_aplus_images: project %d 没有 A+ 模块，跳过", project_id)
        return []

    product_context = _fetch_product_context(project_id, session)
    try:
        from pipeline.layers.custom_requirement_parser import (
            build_user_requirement_lock,
            parse_custom_requirements,
        )
        from pipeline.layers.product_visual_anchor import (
            build_product_identity_lock,
            ensure_product_visual_anchor,
        )
        from pipeline.layers.project_constraints import load_customer_brief
        from pipeline.layers.reference_asset_normalizer import normalize_reference_assets
        from pipeline.models.project import Project

        _proj = session.get(Project, project_id)
        _brief = load_customer_brief(_proj) if _proj else {}
        _refs = normalize_reference_assets(_brief)
        _custom = parse_custom_requirements(_brief)
        _anchor = ensure_product_visual_anchor(_proj, session, _refs) if _proj else {}
        product_context["reference_assets"] = _refs
        product_context["custom_requirements"] = _custom
        product_context["product_visual_anchor"] = _anchor
    except Exception:
        log.warning("A+ 约束上下文加载失败 project=%s", project_id, exc_info=True)

    style_anchor = _build_style_anchor(product_context)
    if style_anchor:
        product_context["style_anchor"] = style_anchor

    results = []
    used_compositions: list[str] = []

    for module in modules:
        mtype = (module.module_type or "").upper()
        intent_tag = _MODULE_TYPE_TO_INTENT.get(mtype)
        try:
            from pipeline.layers.custom_requirement_parser import build_user_requirement_lock
            from pipeline.layers.product_visual_anchor import build_product_identity_lock
            from pipeline.layers.reference_policy import (
                build_intent_reference_rule,
                select_reference_paths,
            )

            try:
                from pipeline.layers.delivery_status import is_product_fact_aplus_module

                _product_fact_only = is_product_fact_aplus_module(mtype)
            except Exception:
                _product_fact_only = False
            ref_image_paths = _dedupe_paths(
                filter_external_image_paths(
                    select_reference_paths(
                        product_context.get("reference_assets", {}),
                        intent_tag,
                        product_fact_only=_product_fact_only,
                    )
                )
            )
            constraint_prefix = "\n\n".join(
                block
                for block in [
                    build_product_identity_lock(
                        product_context.get("product_visual_anchor", {}), intent_tag
                    ),
                    build_user_requirement_lock(
                        product_context.get("custom_requirements", {}), intent_tag
                    ),
                    build_intent_reference_rule(
                        intent_tag, product_context.get("reference_assets", {})
                    ),
                ]
                if block
            )
        except Exception:
            log.warning("A+ 参考图策略失败 module=%s", module.id, exc_info=True)
            ref_image_paths = _collect_ref_image_paths(product_context, intent_tag)
            constraint_prefix = ""
        product_context["constraint_prefix"] = constraint_prefix

        if mtype in _WIDE_MODULE_TYPES:
            prompt = _build_image_prompt(
                module, product_context, used_compositions, constraint_prefix=constraint_prefix
            )
            elastic_scene = _elastic(product_context, "scene_preference")
            used_compositions.append(f"{mtype.lower()} {elastic_scene}")
            try:
                _generate_wide_module_image(
                    module, prompt, adapter, session, ref_image_paths
                )
            except Exception:
                session.expire_all()
                module = session.query(APlusContent).filter_by(id=module.id).first()
                if module is None:
                    continue

        elif mtype in _GENERATE_TILE_TYPES:
            if mtype == "COMPARISON":
                _render_comparison_module_image(module, product_context, session)
            else:
                _generate_tile_module_image(
                    module, product_context, adapter, session, ref_image_paths
                )
            module = session.query(APlusContent).filter_by(id=module.id).first()
            if module is None:
                continue

        elif mtype in _REUSE_SLOT_TYPES:
            try:
                _backfill_reuse_module(module, session)
            except Exception as exc:
                log.error("回填失败 module=%s: %s", module.id, exc)
                try:
                    session.rollback()
                except Exception:
                    pass
                session.expire_all()
                module = session.query(APlusContent).filter_by(id=module.id).first()
                if module is None:
                    continue

        else:
            log.warning("未知模块类型 module=%s type=%s，跳过", module.id, mtype)

        results.append(module)

    # T6 / L4.8：每个模块图生成完毕后，统一跑 QA Gate（自动评分 + 重试）
    try:
        from pipeline.layers.aplus_qa_gate import APlusQAGate

        gate = APlusQAGate()
        for m in results:
            if not m.image_path:
                continue
            gate.run(m.id, session=session)
    except Exception as exc:
        log.error("A+ QA Gate 执行异常 project=%s err=%s", project_id, exc)

    return results


def regenerate_single_aplus_image(
    module_id: int, session, adapter=None
) -> APlusContent | None:
    """T4: 单模块重新生成图片（供 WebUI 调用）。

    复用与批量生成相同的分支逻辑（宽幅 / 方形 / 复用 slot），
    并在生成后单独跑一次 QA Gate。
    """
    if adapter is None:
        from pipeline.adapters.gpt_image_adapter import GptImageAdapter

        adapter = GptImageAdapter()

    module = session.query(APlusContent).filter_by(id=module_id).first()
    if module is None:
        log.warning("regenerate_single_aplus_image: module %d 不存在", module_id)
        return None

    product_context = _fetch_product_context(module.project_id, session)
    mtype = (module.module_type or "").upper()
    intent_tag = _MODULE_TYPE_TO_INTENT.get(mtype)
    try:
        from pipeline.layers.custom_requirement_parser import (
            build_user_requirement_lock,
            parse_custom_requirements,
        )
        from pipeline.layers.product_visual_anchor import (
            build_product_identity_lock,
            ensure_product_visual_anchor,
        )
        from pipeline.layers.project_constraints import load_customer_brief
        from pipeline.layers.reference_asset_normalizer import normalize_reference_assets
        from pipeline.layers.reference_policy import (
            build_intent_reference_rule,
            select_reference_paths,
        )
        from pipeline.models.project import Project

        _proj = session.get(Project, module.project_id)
        _brief = load_customer_brief(_proj) if _proj else {}
        _refs = normalize_reference_assets(_brief)
        _custom = parse_custom_requirements(_brief)
        _anchor = ensure_product_visual_anchor(_proj, session, _refs) if _proj else {}
        product_context["reference_assets"] = _refs
        product_context["custom_requirements"] = _custom
        product_context["product_visual_anchor"] = _anchor
        try:
            from pipeline.layers.delivery_status import is_product_fact_aplus_module

            _product_fact_only = is_product_fact_aplus_module(mtype)
        except Exception:
            _product_fact_only = False
        ref_image_paths = _dedupe_paths(
            filter_external_image_paths(
                select_reference_paths(
                    _refs, intent_tag, product_fact_only=_product_fact_only
                )
            )
        )
        product_context["constraint_prefix"] = "\n\n".join(
            block
            for block in [
                build_product_identity_lock(_anchor, intent_tag),
                build_user_requirement_lock(_custom, intent_tag),
                build_intent_reference_rule(intent_tag, _refs),
            ]
            if block
        )
    except Exception:
        log.warning("【单模块重生】约束上下文加载失败 module=%s", module_id, exc_info=True)
        ref_image_paths = _collect_ref_image_paths(product_context, intent_tag)

    module_ref_paths = filter_external_image_paths(
        [p.strip() for p in (module.reference_image_paths or "").split(",") if p.strip()]
    )
    if module_ref_paths:
        ref_image_paths = _dedupe_paths(module_ref_paths + ref_image_paths)
        log.info(
            "【单模块重生】注入模块级参考图 module=%s count=%d",
            module.id,
            len(module_ref_paths),
        )

    mtype = (module.module_type or "").upper()

    # 重置 QA 相关字段，确保重生后从头评估
    module.qa_score = None
    module.qa_passed = None
    module.qa_issues = None
    module.approved = False
    module.rejected = False

    if mtype in _WIDE_MODULE_TYPES:
        _constraint_prefix = product_context.get("constraint_prefix", "")
        _custom_prompt = (module.custom_prompt or "").strip()
        prompt = (
            f"{_constraint_prefix}\n\n{_custom_prompt}"
            if _custom_prompt and _constraint_prefix
            else _custom_prompt
            or _build_image_prompt(
                module,
                product_context,
                constraint_prefix=_constraint_prefix,
            )
        )
        log.info("【单模块重生】宽幅图 module=%s type=%s", module.id, mtype)
        try:
            _generate_wide_module_image(
                module, prompt, adapter, session, ref_image_paths
            )
        except Exception as exc:
            raise

    elif mtype in _GENERATE_TILE_TYPES:
        if mtype == "COMPARISON":
            _render_comparison_module_image(module, product_context, session)
        elif (module.custom_prompt or "").strip():
            try:
                _constraint_prefix = product_context.get("constraint_prefix", "")
                prompt = module.custom_prompt.strip()
                if _constraint_prefix:
                    prompt = f"{_constraint_prefix}\n\n{prompt}"
                if ref_image_paths and hasattr(adapter, "edit"):
                    result = adapter.edit(ref_image_paths, prompt, params={"size": _TILE_SIZE})
                else:
                    result = adapter.generate(prompt, params={"size": _TILE_SIZE})
                _normalize_image_size(result.image_path, _TILE_SIZE)
                module.image_path = result.image_path
                module.image_prompt = prompt
                module.image_size = _TILE_SIZE
                if ref_image_paths:
                    module.reference_image_paths = ",".join(_dedupe_paths(ref_image_paths))
                session.add(module)
                session.commit()
            except Exception as exc:
                log.error(
                    "【单模块重生】Tile 自定义 prompt 失败 module=%s: %s",
                    module.id,
                    exc,
                )
                session.rollback()
                raise
        else:
            _generate_tile_module_image(
                module, product_context, adapter, session, ref_image_paths
            )

    elif mtype in _REUSE_SLOT_TYPES:
        # 优先从 slot 回填；若回填后仍无图（slot_index=None 或无对应资产），
        # fallback 到 AI 生图（1:1 方图），使用 custom_prompt 或自动构建的 prompt
        _backfill_reuse_module(module, session)
        if not module.image_path:
            _constraint_prefix = product_context.get("constraint_prefix", "")
            _custom_prompt = (module.custom_prompt or "").strip()
            prompt = (
                f"{_constraint_prefix}\n\n{_custom_prompt}"
                if _custom_prompt and _constraint_prefix
                else _custom_prompt
                or _build_image_prompt(
                    module,
                    product_context,
                    constraint_prefix=_constraint_prefix,
                )
            )
            log.info(
                "【单模块重生】%s 回填失败，fallback AI 生图 module=%s prompt=%.80s",
                mtype,
                module.id,
                prompt,
            )
            try:
                result = adapter.generate(prompt, params={"size": _TILE_SIZE})
                _normalize_image_size(result.image_path, _TILE_SIZE)
                module.image_path = result.image_path
                module.image_prompt = prompt
                module.image_size = _TILE_SIZE
                session.add(module)
                session.commit()
            except Exception as exc:
                log.error(
                    "【单模块重生】%s fallback AI 生图失败 module=%s: %s",
                    mtype,
                    module.id,
                    exc,
                )
                session.rollback()
                raise

    else:
        log.warning("【单模块重生】未知模块类型 module=%s type=%s", module.id, mtype)
        return module

    # 跑一次 QA Gate
    try:
        from pipeline.layers.aplus_qa_gate import APlusQAGate

        if module.image_path:
            APlusQAGate().run(module.id, session=session)
    except Exception as exc:
        log.error("【单模块重生】QA Gate 异常 module=%s err=%s", module.id, exc)

    session.refresh(module)
    return module
