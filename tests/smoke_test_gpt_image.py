import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline.adapters.registry import get_adapter
from pipeline.adapters.base import JobStatus


def main():
    print("=== Smoke Test: gpt-image-1 via 147AI ===")

    adapter = get_adapter("gpt_image")
    print(f"Adapter created: {type(adapter).__name__}")

    prompt = "A simple flat-design icon of a white coffee mug on a sky-blue background, centered, clean lines, no text"
    print(f"Prompt: {prompt[:80]}...")

    print("Calling API...")
    result = adapter.generate(prompt)

    print(f"Status: {result.status}")
    print(f"Job ID: {result.job_id}")
    print(f"Image path: {result.image_path}")
    print(f"Image URL: {result.image_url}")
    print(f"Metadata: {result.metadata}")

    assert result.status == JobStatus.COMPLETED, (
        f"Expected COMPLETED, got {result.status}"
    )

    if result.image_path:
        p = Path(result.image_path)
        assert p.exists(), f"Image file not found: {p}"
        size_kb = p.stat().st_size / 1024
        print(f"Image file size: {size_kb:.1f} KB")
        assert size_kb > 1, "Image file suspiciously small (<1KB)"

    print("\n✅ SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
