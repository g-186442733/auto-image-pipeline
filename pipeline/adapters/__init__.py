"""Image generation adapter abstraction layer."""

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.adapters.registry import get_adapter, register_adapter
from pipeline.adapters.gpt_image_adapter import GptImageAdapter
from pipeline.adapters.gemini_image_adapter import GeminiImageAdapter
from pipeline.adapters.gemini_vision_adapter import GeminiVisionAdapter
from pipeline.adapters.helium10_adapter import Helium10Adapter
from pipeline.adapters.jungle_scout_adapter import JungleScoutAdapter

__all__ = [
    "BaseImageAdapter",
    "ImageResult",
    "JobStatus",
    "get_adapter",
    "register_adapter",
    "GptImageAdapter",
    "GeminiImageAdapter",
    "GeminiVisionAdapter",
    "Helium10Adapter",
    "JungleScoutAdapter",
]
