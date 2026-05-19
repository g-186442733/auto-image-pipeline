from pipeline.layers.custom_requirement_parser import (
    build_user_requirement_lock,
    requirements_for_intent,
)
from pipeline.layers.prompt_engine import (
    _MARKETPLACE_LANGUAGE_POLICY,
    _intent_composition_lock,
    _intent_negative_constraints,
    _sanitize_cjk_for_image_prompt,
    _text_constraint,
)
from pipeline.layers.qa_gate import evaluate_set_intent_structure


def test_must_show_accessory_bundle_only_applies_to_packaging():
    req = {
        "must_show": [
            "USB-C接口",
            "保护盒和全部配件",
            "黑色主款",
            "柔软耳罩材质",
            "24小时续航信息",
        ],
    }

    hero_lock = build_user_requirement_lock(req, "INT_HERO")
    packaging_lock = build_user_requirement_lock(req, "INT_PACKAGING")

    assert "black main product variant" in hero_lock
    assert "carrying case and complete accessory bundle" not in hero_lock
    assert "Deferred to other intent slots" in hero_lock
    assert "carrying case and complete accessory bundle" in packaging_lock
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in hero_lock + packaging_lock)


def test_feature_and_material_requirements_apply_to_relevant_intents():
    req = {
        "must_show": ["USB-C接口", "柔软耳罩材质", "24小时续航信息"],
    }

    detail_lock = build_user_requirement_lock(req, "INT_DETAIL")
    infographic_lock = build_user_requirement_lock(req, "INT_INFOGRAPHIC")
    comparison_lock = build_user_requirement_lock(req, "INT_COMPARISON")

    assert "USB-C port" in detail_lock
    assert "soft ear cushion material" in detail_lock
    assert "battery life information in hours" not in detail_lock
    assert "USB-C port" in infographic_lock
    assert "battery life information in hours" in infographic_lock
    assert "soft ear cushion material" not in infographic_lock
    assert "battery life information in hours" in comparison_lock
    assert not any(
        "\u4e00" <= ch <= "\u9fff"
        for ch in detail_lock + infographic_lock + comparison_lock
    )


def test_user_requirement_lock_normalizes_chinese_business_context_to_english():
    req = {
        "project_direction": "高端商务科技风，克制、干净、可信赖",
        "raw_text": "严格保持真实上传白底图和角度图中的耳机外观、比例、颜色、耳罩形状和 BOSE 标识位置。Hero 主图不得展示保护盒、线材、配件全家福。Packaging/In-box 图位才展示保护盒、USB-C 线、音频线、安全说明。Detail 图位聚焦接口、按钮、耳罩材质。生成构图参考图只能用于 layout，不得当作真实产品照片。",
        "must_show": ["黑色主款"],
        "must_not_show": ["虚构配件", "儿童场景"],
    }

    lock = build_user_requirement_lock(req, "INT_HERO")

    assert "premium business technology style" in lock
    assert "Hero image must not show the carrying case" in lock
    assert "black main product variant" in lock
    assert "invented accessories" in lock
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in lock)


def test_hero_raw_instruction_does_not_leak_to_detail_or_infographic():
    req = {
        "raw_text": "Hero 主图不得展示保护盒、线材、配件全家福。Detail 图位聚焦接口、按钮、耳罩材质。Packaging/In-box 图位才展示保护盒、USB-C 线、音频线、安全说明。",
    }

    detail_lock = build_user_requirement_lock(req, "INT_DETAIL")
    infographic_lock = build_user_requirement_lock(req, "INT_INFOGRAPHIC")

    assert "Hero image must not show" not in detail_lock
    assert "Hero image must not show" not in infographic_lock
    assert "Detail slot should focus on ports" in detail_lock
    assert "Only the Packaging/In-box slot" not in detail_lock


def test_qa_requirements_for_intent_filters_raw_text_scope():
    req = {
        "raw_text": "Hero 主图不得展示保护盒、线材、配件全家福。Detail 图位聚焦接口、按钮、耳罩材质。Packaging/In-box 图位才展示保护盒、USB-C 线、音频线、安全说明。",
        "must_show": ["USB-C接口", "保护盒和全部配件", "柔软耳罩材质"],
        "generation_policy": {"strict_product_identity": True},
    }

    detail_req = requirements_for_intent(req, "INT_DETAIL")
    infographic_req = requirements_for_intent(req, "INT_INFOGRAPHIC")

    assert "Hero 主图" not in detail_req["raw_text"]
    assert "Packaging/In-box" not in detail_req["raw_text"]
    assert "Detail 图位" in detail_req["raw_text"]
    assert "柔软耳罩材质" in detail_req["must_show"]
    assert "保护盒和全部配件" not in detail_req["must_show"]
    assert "Hero 主图" not in infographic_req["raw_text"]
    assert "Packaging/In-box" not in infographic_req["raw_text"]


def test_marketplace_language_policy_for_amazon_us():
    assert "Amazon US" in _MARKETPLACE_LANGUAGE_POLICY
    assert "English only" in _MARKETPLACE_LANGUAGE_POLICY
    assert "Chinese characters" in _MARKETPLACE_LANGUAGE_POLICY
    assert "English only" in _text_constraint("INT_INFOGRAPHIC")
    assert "Do not copy Chinese source text" in _text_constraint("INT_INFOGRAPHIC")


def test_sanitize_cjk_for_image_prompt_translates_or_removes_chinese_context():
    prompt = """
    Project direction: 高端商务科技风，克制、干净、可信赖.
    User special instructions: 严格保持真实上传白底图和角度图中的耳机外观、比例、颜色、耳罩形状和 BOSE 标识位置。
    Must show in this intent slot: USB-C接口; 黑色主款; 24小时续航信息.
    Must not show: Hero主图出现保护盒或线材; 不存在的颜色; 虚构配件; 儿童场景; 宠物场景; 竞品品牌名; 电竞灯效.
    """

    sanitized = _sanitize_cjk_for_image_prompt(prompt)

    assert "premium business technology style" in sanitized
    assert "USB-C port" in sanitized
    assert "black main product variant" in sanitized
    assert "battery life" in sanitized
    assert "invented accessories" in sanitized
    assert not any("\u3400" <= ch <= "\u9fff" for ch in sanitized)


def test_intent_negative_constraints_prevent_accessory_spread():
    hero_constraints = _intent_negative_constraints("INT_HERO")
    lifestyle_constraints = _intent_negative_constraints("INT_LIFESTYLE")
    detail_constraints = _intent_negative_constraints("INT_DETAIL")
    comparison_constraints = _intent_negative_constraints("INT_COMPARISON")

    assert "accessories" in hero_constraints
    assert "case" in hero_constraints
    assert "cables" in hero_constraints
    assert "flat-lay accessory bundle" in lifestyle_constraints
    assert "full accessory spread" in detail_constraints
    assert "packaging bundle" in comparison_constraints


def test_detail_infographic_and_lifestyle_have_hard_angle_composition_locks():
    lifestyle_lock = _intent_composition_lock("INT_LIFESTYLE")
    detail_lock = _intent_composition_lock("INT_DETAIL")
    infographic_lock = _intent_composition_lock("INT_INFOGRAPHIC")

    assert "lifestyle use scene only" in lifestyle_lock
    assert "visible person" in lifestyle_lock
    assert "never output a product-only image" in lifestyle_lock
    assert "never use a pure white studio product background" in lifestyle_lock
    assert "never use an isolated 3/4 product render" in lifestyle_lock
    assert "true macro close-up only" in detail_lock
    assert "never use a medium shot" in detail_lock
    assert "never use a 3/4" in detail_lock
    assert "orthographic front-facing" in infographic_lock
    assert "never use a 3/4" in infographic_lock


def test_set_intent_structure_flags_missing_packaging_slot():
    plans = [
        {"slot": 1, "intent": "INT_HERO"},
        {"slot": 2, "intent": "INT_LIFESTYLE"},
        {"slot": 3, "intent": "INT_DETAIL"},
    ]

    result = evaluate_set_intent_structure(plans)

    assert result["passed"] is False
    assert "缺少包装/配件图位" in result["issues"]


def test_set_intent_structure_flags_duplicate_lifestyle_without_packaging():
    plans = [
        {"slot": 1, "intent": "INT_HERO"},
        {"slot": 2, "intent": "INT_LIFESTYLE"},
        {"slot": 3, "intent": "INT_LIFESTYLE"},
        {"slot": 4, "intent": "INT_PACKAGING"},
    ]

    result = evaluate_set_intent_structure(plans)

    assert result["passed"] is False
    assert "缺少细节图位" in result["issues"]


def test_set_intent_structure_passes_minimum_complete_intent_mix():
    plans = [
        {"slot": 1, "intent": "INT_HERO"},
        {"slot": 2, "intent": "INT_LIFESTYLE"},
        {"slot": 3, "intent": "INT_DETAIL"},
        {"slot": 4, "intent": "INT_INFOGRAPHIC"},
        {"slot": 5, "intent": "INT_COMPARISON"},
        {"slot": 6, "intent": "INT_PACKAGING"},
    ]

    result = evaluate_set_intent_structure(plans)

    assert result["passed"] is True
    assert result["issues"] == []
