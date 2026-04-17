"""E2E test: brief → slot plan → prompt assembly → real AI image generation.

Bypasses step_analyze (Keepa dependency) by inserting fake AmazonBenchmark rows.
Copies default templates (project_id=0) to project-specific PromptAssets.

Cost control: only generates 1 image (MAIN slot) by default.
Set E2E_ALL_SLOTS=1 to generate all 8.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.models.base import get_session, create_all
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.prompt_asset import PromptAsset
from pipeline.layers.input_layer import create_project
from pipeline.layers.slot_planner import generate_slot_plan
from pipeline.layers.prompt_engine import generate_slot_prompts
from pipeline.adapters.registry import get_adapter


def main():
    all_slots = os.environ.get("E2E_ALL_SLOTS", "0") == "1"
    slot_count = 8 if all_slots else 1

    print(f"=== E2E Real Generation Test (slots={slot_count}) ===\n")

    # 1. Init DB
    create_all()
    print("[1/6] DB initialized")

    # 2. Create project
    brief = {
        "name": "E2E Test Product",
        "asin": "B0E2ETEST0",
        "category": "Electronics",
        "notes": "End-to-end test with real AI image generation",
    }
    project = create_project(brief)
    pid = project.id
    print(f"[2/6] Project created: id={pid}, name={project.name}")

    # 3. Insert fake AmazonBenchmark rows (bypass Keepa)
    session = get_session()
    try:
        for i in range(1, 9):
            bm = AmazonBenchmark(
                project_id=pid,
                competitor_asin=f"B0FAKE{i:05d}",
                slot_index=i,
                image_url=f"https://example.com/fake_{i}.jpg",
                analysis=f"Fake benchmark for slot {i}",
                score=80 + i,
            )
            session.add(bm)
        session.commit()
        print(f"[3/6] Inserted 8 fake AmazonBenchmark rows")
    finally:
        session.close()

    # 4. Generate slot plan
    plans = generate_slot_plan(pid)
    print(f"[4/6] Slot plan generated: {len(plans)} slots")
    for p in plans:
        print(
            f"       slot {p.slot_index}: {p.intent_tag} / {p.layout_tag} / {p.style_tag}"
        )

    # 5. Copy default templates (project_id=0) → project-specific
    session = get_session()
    try:
        defaults = (
            session.query(PromptAsset)
            .filter(PromptAsset.project_id == 0)
            .order_by(PromptAsset.slot_index)
            .all()
        )
        if not defaults:
            # Seed them first
            from pipeline.layers.prompt_manager import seed_default_templates

            seed_default_templates()
            defaults = (
                session.query(PromptAsset)
                .filter(PromptAsset.project_id == 0)
                .order_by(PromptAsset.slot_index)
                .all()
            )

        copied = 0
        for tmpl in defaults:
            target_slot = tmpl.slot_index
            if not all_slots and target_slot != 1:
                continue
            pa = PromptAsset(
                project_id=pid,
                slot_index=target_slot,
                prompt_text=tmpl.prompt_text,
                negative_prompt=tmpl.negative_prompt,
                model_name=tmpl.model_name,
                version=1,
            )
            session.add(pa)
            copied += 1
        session.commit()
        print(f"[5/6] Copied {copied} prompt templates for project {pid}")
    finally:
        session.close()

    # 6. Generate prompts and call real AI adapter
    prompts = generate_slot_prompts(pid)
    print(f"\n[6/6] Assembled {len(prompts)} prompts. Calling gpt-image-1...\n")

    adapter = get_adapter("gpt_image")
    results = {}
    for label, prompt_text in prompts.items():
        print(f"  → Generating [{label}]...")
        print(f"    Prompt (first 120 chars): {prompt_text[:120]}...")
        try:
            result = adapter.generate(prompt_text)
            results[label] = result
            print(f"    ✅ job={result.job_id}  status={result.status}")
            print(f"    📁 image_path={result.image_path}")
            if result.metadata:
                tokens_in = result.metadata.get("input_tokens", "?")
                tokens_out = result.metadata.get("output_tokens", "?")
                print(f"    📊 tokens: in={tokens_in}, out={tokens_out}")
        except Exception as exc:
            print(f"    ❌ FAILED: {exc}")
            results[label] = None

    # Summary
    print("\n=== RESULTS ===")
    success = sum(1 for r in results.values() if r is not None and r.image_path)
    total = len(results)
    print(f"Generated: {success}/{total}")
    for label, r in results.items():
        if r and r.image_path:
            exists = Path(r.image_path).exists()
            size = Path(r.image_path).stat().st_size if exists else 0
            print(f"  {label}: {r.image_path} ({size:,} bytes, exists={exists})")
        else:
            print(f"  {label}: FAILED")

    if success == total:
        print("\n🎉 E2E TEST PASSED — all images generated successfully!")
        return 0
    else:
        print(f"\n⚠️  E2E TEST PARTIAL — {success}/{total} succeeded")
        return 1


if __name__ == "__main__":
    sys.exit(main())
