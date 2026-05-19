from pipeline.layers.delivery_status import (
    CONCEPT_ONLY,
    FAILED,
    FINAL,
    aplus_delivery_metadata,
    has_generated_composition_reference,
    listing_delivery_metadata,
    reference_basis,
)
from pipeline.layers.reference_policy import (
    reference_keys_for_intent,
    select_reference_paths,
)


def test_generated_composition_reference_detection():
    paths = [
        "uploads/1/real_white_bg.webp",
        "uploads/1/generated_packaging_composition_reference_gpt_image_2.webp",
    ]

    assert has_generated_composition_reference(paths) is True
    assert reference_basis(paths) == [
        "real_product_reference",
        "generated_composition_reference",
    ]


def test_product_fact_reference_policy_excludes_generated_layout_refs(tmp_path):
    white = tmp_path / "real_white_bg.webp"
    front = tmp_path / "real_front_view.webp"
    scale = tmp_path / "generated_scale_composition_reference.webp"
    for p in (white, front, scale):
        p.write_bytes(b"x")

    refs = {
        "white_bg": [str(white)],
        "front_view": [str(front)],
        "scale_ref": [str(scale)],
    }

    assert reference_keys_for_intent("INT_INFOGRAPHIC") == [
        "front_diagram_canvas",
        "front_orthographic",
        "front_view",
        "white_bg",
    ]
    selected = select_reference_paths(refs, "INT_INFOGRAPHIC", product_fact_only=True)
    assert str(scale) not in selected
    assert selected == [str(front), str(white)]


def test_reference_metadata_can_separate_generation_refs_from_fact_refs():
    from pipeline.layers.delivery_status import listing_delivery_metadata

    meta = listing_delivery_metadata(
        passed=True,
        score=93,
        qa_details={"D": 25},
        intent_tag="INT_HERO",
        reference_paths=["uploads/817/real_white_bg.webp"],
        product_fact_reference_paths=[
            "uploads/817/real_multiangle_costco_black_front_controls.webp",
            "uploads/817/real_white_bg.webp",
        ],
        layout_reference_paths=[],
    )

    assert meta["delivery_status"] == FINAL
    assert meta["reference_paths"] == ["uploads/817/real_white_bg.webp"]
    assert meta["product_fact_reference_paths"] == [
        "uploads/817/real_multiangle_costco_black_front_controls.webp",
        "uploads/817/real_white_bg.webp",
    ]


def test_angle_specific_reference_policy_prefers_target_angle_refs(tmp_path):
    white = tmp_path / "real_white_bg_3q.webp"
    multi = tmp_path / "real_multiangle_3q.webp"
    front = tmp_path / "real_front_view.webp"
    front_canvas = tmp_path / "generated_front_diagram_canvas_reference.webp"
    front_ortho = tmp_path / "real_front_orthographic_crop.webp"
    side = tmp_path / "real_side_view.webp"
    macro = tmp_path / "real_macro_detail.webp"
    macro_crop = tmp_path / "real_macro_detail_crop.webp"
    usage = tmp_path / "real_usage_context.webp"
    for p in (
        white,
        multi,
        front,
        front_canvas,
        front_ortho,
        side,
        macro,
        macro_crop,
        usage,
    ):
        p.write_bytes(b"x")

    refs = {
        "white_bg": [str(white)],
        "multiangle": [str(multi)],
        "front_view": [str(front)],
        "front_diagram_canvas": [str(front_canvas)],
        "front_orthographic": [str(front_ortho)],
        "side_view": [str(side)],
        "macro_view": [str(macro)],
        "macro_crop": [str(macro_crop)],
        "usage_context": [str(usage)],
    }

    assert select_reference_paths(refs, "INT_HERO") == [str(front), str(white)]
    assert select_reference_paths(refs, "INT_LIFESTYLE") == [str(usage), str(side)]
    assert select_reference_paths(refs, "INT_DETAIL") == [str(macro_crop)]
    assert select_reference_paths(refs, "INT_INFOGRAPHIC") == [
        str(front_canvas),
        str(front_ortho),
        str(front),
        str(white),
    ]
    assert select_reference_paths(refs, "INT_INFOGRAPHIC", product_fact_only=True) == [
        str(macro),
        str(front),
        str(white),
    ]


def test_packaging_reference_policy_uses_accessory_facts_but_excludes_generated_layout_from_fact_refs(
    tmp_path,
):
    white = tmp_path / "real_white_bg.webp"
    case = tmp_path / "real_accessory_case.webp"
    cable = tmp_path / "real_accessory_usb_c.webp"
    composition = tmp_path / "generated_packaging_composition_reference.webp"
    for p in (white, case, cable, composition):
        p.write_bytes(b"x")

    refs = {
        "white_bg": [str(white)],
        "packaging": [str(case)],
        "detail_closeup": [str(cable)],
        "inbox_flatlay": [str(composition)],
    }

    assert reference_keys_for_intent("INT_PACKAGING") == [
        "packaging",
        "detail_closeup",
        "inbox_flatlay",
        "white_bg",
    ]
    assert reference_keys_for_intent("INT_PACKAGING", product_fact_only=True) == [
        "packaging",
        "detail_closeup",
        "white_bg",
    ]

    selected_for_generation = select_reference_paths(
        refs, "INT_PACKAGING", product_fact_only=False
    )
    selected_for_facts = select_reference_paths(
        refs, "INT_PACKAGING", product_fact_only=True
    )

    assert selected_for_generation == [
        str(case),
        str(cable),
        str(composition),
        str(white),
    ]
    assert selected_for_facts == [str(case), str(cable), str(white)]
    assert str(composition) not in selected_for_facts


def test_listing_delivery_final_when_product_consistency_passes():
    meta = listing_delivery_metadata(
        passed=True,
        score=91,
        qa_details={"D": 25},
        intent_tag="INT_HERO",
        reference_paths=["uploads/1/real_white_bg.webp"],
        model_name="gpt_image",
    )

    assert meta["delivery_status"] == FINAL
    assert meta["consistency_status"] == "pass"


def test_listing_delivery_metadata_includes_angle_review_fields():
    meta = listing_delivery_metadata(
        passed=True,
        score=91,
        qa_details={"D": 25},
        intent_tag="INT_HERO",
        reference_paths=["uploads/1/real_white_bg.webp"],
        target_angle="front_10deg",
        actual_angle="front_10deg",
        angle_matches_target=True,
    )

    assert meta["delivery_status"] == FINAL
    assert meta["target_angle"] == "front_10deg"
    assert meta["actual_angle"] == "front_10deg"
    assert meta["angle_matches_target"] is True


def test_listing_delivery_concept_when_angle_target_mismatch_persists():
    meta = listing_delivery_metadata(
        passed=True,
        score=99,
        qa_details={"D": 25},
        intent_tag="INT_DETAIL",
        reference_paths=["uploads/1/real_detail.webp"],
        target_angle="macro close-up",
        actual_angle="3/4角",
        angle_matches_target=False,
    )

    assert meta["delivery_status"] == CONCEPT_ONLY
    assert meta["consistency_status"] == "warning"
    assert "Angle target mismatch" in meta["delivery_reason"]


def test_listing_delivery_final_when_generated_reference_is_layout_only():
    meta = listing_delivery_metadata(
        passed=True,
        score=91,
        qa_details={"D": 25},
        intent_tag="INT_PACKAGING",
        reference_paths=[
            "uploads/1/real_white_bg.webp",
            "uploads/1/generated_packaging_composition_reference_gpt_image_2.webp",
        ],
        product_fact_reference_paths=["uploads/1/real_white_bg.webp"],
        layout_reference_paths=[
            "uploads/1/generated_packaging_composition_reference_gpt_image_2.webp"
        ],
        model_name="gpt_image",
    )

    assert meta["delivery_status"] == FINAL
    assert meta["consistency_status"] == "pass"
    assert meta["product_fact_reference_paths"] == ["uploads/1/real_white_bg.webp"]
    assert meta["layout_reference_paths"] == [
        "uploads/1/generated_packaging_composition_reference_gpt_image_2.webp"
    ]


def test_listing_delivery_final_in_silhouette_mode_with_lower_consistency_score():
    meta = listing_delivery_metadata(
        passed=True,
        score=82,
        qa_details={"D": 11},
        intent_tag="INT_HERO",
        reference_paths=["uploads/1/real_white_bg.webp"],
        reference_identity_mode="silhouette",
    )

    assert meta["delivery_status"] == FINAL
    assert meta["consistency_status"] == "pass"
    assert meta["reference_identity_mode"] == "silhouette"
    assert meta["consistency_threshold"] == 10


def test_listing_delivery_concept_when_strict_mode_consistency_low():
    meta = listing_delivery_metadata(
        passed=True,
        score=82,
        qa_details={"D": 11},
        intent_tag="INT_HERO",
        reference_paths=["uploads/1/real_white_bg.webp"],
        reference_identity_mode="strict",
    )

    assert meta["delivery_status"] == CONCEPT_ONLY
    assert meta["consistency_status"] == "warning"
    assert meta["reference_identity_mode"] == "strict"
    assert meta["consistency_threshold"] == 18


def test_listing_delivery_concept_when_product_fact_uses_generated_reference():
    meta = listing_delivery_metadata(
        passed=True,
        score=91,
        qa_details={"D": 25},
        intent_tag="INT_PACKAGING",
        reference_paths=[
            "uploads/1/real_white_bg.webp",
            "uploads/1/generated_packaging_composition_reference_gpt_image_2.webp",
        ],
        model_name="gpt_image",
    )

    assert meta["delivery_status"] == CONCEPT_ONLY
    assert meta["consistency_status"] == "warning"


def test_listing_delivery_failed_when_qa_fails():
    meta = listing_delivery_metadata(
        passed=False,
        score=59,
        qa_details={"D": 25},
        intent_tag="INT_HERO",
        reference_paths=["uploads/1/real_white_bg.webp"],
    )

    assert meta["delivery_status"] == FAILED


def test_aplus_delivery_concept_when_l5_low_for_product_fact_module():
    meta = aplus_delivery_metadata(
        passed=True,
        score=78,
        breakdown={"L5_consistency": 6},
        module_type="DETAIL",
        reference_paths=["uploads/1/real_white_bg.webp"],
    )

    assert meta["delivery_status"] == CONCEPT_ONLY
    assert meta["product_fact_required"] is True


def test_aplus_lifestyle_can_be_final_with_good_score():
    meta = aplus_delivery_metadata(
        passed=True,
        score=82,
        breakdown={"L4_intent": 20, "L5_consistency": 7},
        module_type="LIFESTYLE",
        reference_paths=["uploads/1/generated_style_reference.webp"],
    )

    assert meta["delivery_status"] == FINAL
    assert meta["product_fact_required"] is False


def test_aplus_delivery_failed_when_module_intent_is_too_low():
    meta = aplus_delivery_metadata(
        passed=True,
        score=76,
        breakdown={"L4_intent": 5, "L5_consistency": 10},
        module_type="DETAIL",
        reference_paths=["uploads/1/real_detail.webp"],
    )

    assert meta["delivery_status"] == FAILED
    assert meta["consistency_status"] == "fail"
    assert "module intent" in meta["delivery_reason"]


def test_aplus_delivery_failed_when_product_fact_module_has_no_reference():
    meta = aplus_delivery_metadata(
        passed=True,
        score=73,
        breakdown={"L4_intent": 20, "L5_consistency": 10},
        module_type="COMPARISON",
        reference_paths=[],
    )

    assert meta["delivery_status"] == FAILED
    assert meta["product_fact_required"] is True
    assert "real product reference" in meta["delivery_reason"]
