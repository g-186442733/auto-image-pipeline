import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline.adapters.registry import get_adapter


def main():
    print("=== Smoke Test: gemini-2.5-flash vision analysis via 147AI ===")

    adapter = get_adapter("gemini_vision")
    print(f"Adapter created: {type(adapter).__name__}")

    img_dir = Path("data/images/gpt_image")
    images = sorted(img_dir.glob("*.png"))
    if not images:
        print("No gpt_image output found. Run smoke_test_gpt_image.py first.")
        sys.exit(1)

    image_path = str(images[-1])
    print(f"Analyzing image: {image_path}")

    prompt = "Describe this image in detail. What objects are shown? What colors are used? What style is it?"
    print(f"Prompt: {prompt[:80]}...")

    print("Calling API...")
    result = adapter.analyze(image_path, prompt)

    print(f"Analysis: {result['analysis'][:300]}...")
    print(f"Model: {result['model']}")
    print(f"Prompt tokens: {result['prompt_tokens']}")
    print(f"Completion tokens: {result['completion_tokens']}")

    assert result["analysis"], "Empty analysis"
    assert len(result["analysis"]) > 20, "Analysis too short"

    print("\n✅ SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
