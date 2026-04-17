from dataclasses import dataclass


@dataclass(frozen=True)
class Tag:
    code: str
    name_cn: str
    name_en: str
    description: str


# ── Intent Tags (6) ─────────────────────────────────────────
INTENT_TAGS = (
    Tag("INT_HERO", "主图展示", "Hero Shot", "White-background main listing image"),
    Tag("INT_LIFESTYLE", "场景图", "Lifestyle", "Product in real-life context"),
    Tag(
        "INT_INFOGRAPHIC", "信息图", "Infographic", "Feature callouts and specs overlay"
    ),
    Tag("INT_COMPARISON", "对比图", "Comparison", "Before/after or vs-competitor"),
    Tag("INT_DETAIL", "细节图", "Detail Close-up", "Texture, material, zoom-in"),
    Tag("INT_PACKAGING", "包装图", "Packaging", "Box, bundle, what-you-get"),
)

# ── Role Tags (7) ───────────────────────────────────────────
ROLE_TAGS = (
    Tag("ROLE_BG", "背景", "Background", "Scene or solid background layer"),
    Tag("ROLE_PRODUCT", "产品主体", "Product", "The core product cutout"),
    Tag("ROLE_PROP", "道具", "Prop", "Supporting object in scene"),
    Tag("ROLE_MODEL", "模特", "Model", "Human model wearing/using product"),
    Tag("ROLE_TEXT", "文字", "Text Overlay", "Headlines, badges, callouts"),
    Tag("ROLE_ICON", "图标", "Icon/Badge", "Trust badges, award icons"),
    Tag(
        "ROLE_SHADOW",
        "阴影/反射",
        "Shadow/Reflection",
        "Ground shadow or mirror effect",
    ),
)

# ── Slot Mapping (8 slots) ──────────────────────────────────
SLOT_MAPPING = {
    1: "MAIN — hero shot, white background, no text",
    2: "ALT1 — secondary angle or lifestyle",
    3: "ALT2 — infographic with feature callouts",
    4: "ALT3 — detail / close-up",
    5: "ALT4 — comparison or size reference",
    6: "ALT5 — packaging / what-in-box",
    7: "ALT6 — lifestyle or model shot",
    8: "VIDEO_THUMB — video thumbnail frame",
}

# ── Color Tags (6) ──────────────────────────────────────────
COLOR_TAGS = (
    Tag("CLR_WHITE", "纯白", "Pure White", "#FFFFFF studio background"),
    Tag("CLR_LIGHT", "浅色", "Light Neutral", "Off-white, beige, light gray"),
    Tag("CLR_DARK", "深色", "Dark/Moody", "Black, charcoal, navy background"),
    Tag("CLR_WARM", "暖色", "Warm Tone", "Orange, gold, earthy palette"),
    Tag("CLR_COOL", "冷色", "Cool Tone", "Blue, teal, mint palette"),
    Tag("CLR_BRAND", "品牌色", "Brand Color", "Dominant brand palette"),
)

# ── Layout Tags (5) ─────────────────────────────────────────
LAYOUT_TAGS = (
    Tag("LAY_CENTER", "居中", "Centered", "Product centered, symmetrical"),
    Tag("LAY_RULE3", "三分法", "Rule of Thirds", "Product offset to a third"),
    Tag("LAY_FLAT", "平铺", "Flat Lay", "Top-down arrangement"),
    Tag("LAY_SPLIT", "分屏", "Split Screen", "Two halves comparison layout"),
    Tag("LAY_GRID", "网格", "Grid/Mosaic", "Multiple items in grid"),
)

# ── Style Tags (6) ──────────────────────────────────────────
STYLE_TAGS = (
    Tag("STY_MINIMAL", "极简", "Minimalist", "Clean, few elements"),
    Tag("STY_PREMIUM", "高端", "Premium/Luxury", "Rich textures, dramatic lighting"),
    Tag("STY_PLAYFUL", "活泼", "Playful/Fun", "Bright colors, casual vibe"),
    Tag("STY_TECH", "科技感", "Tech/Modern", "Sleek, gradients, futuristic"),
    Tag("STY_NATURAL", "自然", "Natural/Organic", "Earth tones, raw materials"),
    Tag("STY_BOLD", "大胆", "Bold/Graphic", "Strong typography, high contrast"),
)

ALL_TAGS = INTENT_TAGS + ROLE_TAGS + COLOR_TAGS + LAYOUT_TAGS + STYLE_TAGS
TAG_LOOKUP = {t.code: t for t in ALL_TAGS}
