"""
Test: seed_default_templates() + generate_slot_prompts()
Validates L3 prompt template loading and Jinja2 assembly.
"""

import os
import sys

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.models.base import create_all, get_session
from pipeline.models.project import Project
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.prompt_asset import PromptAsset
from pipeline.layers.prompt_manager import seed_default_templates
from pipeline.layers.prompt_engine import generate_slot_prompts


def main():
    print("=" * 60)
    print("TEST: Prompt Template Loading & Assembly")
    print("=" * 60)

    # --- Step 1: Init DB ---
    create_all()
    print("\n[1/4] DB tables created.")

    # --- Step 2: Seed templates ---
    count = seed_default_templates()
    print(f"[2/4] seed_default_templates() loaded {count} templates.")
    assert count == 8, f"Expected 8 templates, got {count}"

    # Verify in DB
    with get_session() as session:
        assets = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == 0)
            .order_by(PromptAsset.slot_index)
            .all()
        )
        print(f"      DB has {len(assets)} template records (project_id=0):")
        for a in assets:
            snippet = a.prompt_text[:60].replace("\n", " ")
            print(
                f"        slot {a.slot_index}: model={a.model_name} prompt='{snippet}...'"
            )
        assert len(assets) == 8

    print("      ✅ All 8 templates seeded successfully.")

    # --- Step 3: Create test project + slot plans + per-project prompt assets ---
    with get_session() as session:
        project = Project(
            name="Test Widget Pro",
            category="electronics",
            notes="A premium wireless Bluetooth speaker with RGB lighting",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        pid = project.id
        print(f"\n[3/4] Created test project id={pid}: '{project.name}'")

        # Create 8 slot plans with realistic tags
        slot_configs = [
            (
                1,
                "hero",
                "centered",
                "clean",
                "neutral",
                "Main hero shot of the Bluetooth speaker",
            ),
            (
                2,
                "lifestyle",
                "rule-of-thirds",
                "warm",
                "earth-tone",
                "Speaker on a wooden desk in living room",
            ),
            (
                3,
                "infographic",
                "split-screen",
                "modern",
                "brand-blue",
                "Feature callouts showing Bluetooth 5.3, 20hr battery",
            ),
            (
                4,
                "detail",
                "close-up",
                "minimal",
                "dark",
                "Close-up of the speaker grille texture",
            ),
            (
                5,
                "comparison",
                "side-by-side",
                "neutral",
                "gray",
                "Size comparison with a coffee mug",
            ),
            (
                6,
                "packaging",
                "flat-lay",
                "bright",
                "white",
                "Unboxing shot with all accessories",
            ),
            (
                7,
                "lifestyle",
                "environmental",
                "warm",
                "golden",
                "Person enjoying music outdoors with the speaker",
            ),
            (
                8,
                "video-thumb",
                "dynamic",
                "bold",
                "vibrant",
                "Cinematic thumbnail with speaker and RGB lights",
            ),
        ]

        for slot_idx, intent, layout, style, color, desc in slot_configs:
            sp = SlotPlan(
                project_id=pid,
                slot_index=slot_idx,
                intent_tag=intent,
                layout_tag=layout,
                style_tag=style,
                color_tag=color,
                description=desc,
            )
            session.add(sp)

        session.commit()
        print(f"      Created 8 SlotPlan records for project {pid}.")

    # Now create per-project PromptAssets by copying from templates (project_id=0)
    with get_session() as session:
        templates = session.query(PromptAsset).filter(PromptAsset.project_id == 0).all()
        for t in templates:
            pa = PromptAsset(
                project_id=pid,
                slot_index=t.slot_index,
                prompt_text=t.prompt_text,
                negative_prompt=t.negative_prompt,
                model_name=t.model_name,
                version=1,
            )
            session.add(pa)
        session.commit()
        print(f"      Copied 8 templates as project-specific PromptAssets.")

    # --- Step 4: Test generate_slot_prompts ---
    prompts = generate_slot_prompts(pid)
    print(f"\n[4/4] generate_slot_prompts({pid}) returned {len(prompts)} prompts:")
    for label, prompt_text in prompts.items():
        # Show first 120 chars
        snippet = prompt_text[:120].replace("\n", " ")
        has_neg = "--no " in prompt_text
        print(f"      {label:12s}: '{snippet}...' [neg={has_neg}]")

    assert len(prompts) == 8, f"Expected 8 prompts, got {len(prompts)}"

    # Validate Jinja2 rendered correctly (no raw {{ }} left)
    for label, text in prompts.items():
        assert "{{" not in text, f"Unrendered Jinja2 in {label}: {text[:80]}"
        assert "}}" not in text, f"Unrendered Jinja2 in {label}: {text[:80]}"

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
