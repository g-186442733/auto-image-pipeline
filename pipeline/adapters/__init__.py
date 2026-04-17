"""Image generation adapter abstraction layer."""

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.adapters.registry import get_adapter, register_adapter

__all__ = [
    "BaseImageAdapter",
    "ImageResult",
    "JobStatus",
    "get_adapter",
    "register_adapter",
]
