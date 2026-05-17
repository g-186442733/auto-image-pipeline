"""Base adapter abstraction for AI image generation services."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


__all__ = ["JobStatus", "ImageResult", "BaseImageAdapter"]


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ImageResult:
    job_id: str
    status: JobStatus
    image_url: str | None = None
    image_path: str | None = None
    error: str | None = None
    metadata: dict | None = field(default_factory=dict)


class BaseImageAdapter:
    """Abstract base for image generation adapters.

    Error codes:
        E_ADAPTER_001 — adapter not configured
        E_ADAPTER_002 — parameter validation failed
        E_ADAPTER_003 — job not found
        E_ADAPTER_004 — job not completed yet
    """

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        raise NotImplementedError

    def check_status(self, job_id: str) -> JobStatus:
        raise NotImplementedError

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError
