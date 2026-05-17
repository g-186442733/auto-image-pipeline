import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline.adapters.registry import get_adapter
from pipeline.adapters.base import JobStatus


def main():
    print("=== Smoke Test: gemini-2.5-flash-image-preview via 147AI ===")

    adapter = get_adapter("gemini_image")
    print(f"Adapter created: {type(adapter).__name__}")

    prompt = "Generate a simple flat-design icon of a red shopping cart on a white background, clean vector style, no text"
    print(f"Prompt: {prompt[:80]}...")

    print("Calling API...")
    result = adapter.generate(prompt)

    print(f"Status: {result.status}")
    print(f"Job ID: {result.job_id}")
    print(f"Image path: {result.image_path}")
    print(f"Error: {result.error}")
    print(f"Metadata: {result.metadata}")

    assert result.status == JobStatus.COMPLETED, (
        f"Expected COMPLETED, got {result.status}. Error: {result.error}"
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
