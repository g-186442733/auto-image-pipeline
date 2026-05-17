"""Mock adapter for testing — generates placeholder images on disk."""

from __future__ import annotations

import os
import struct
import uuid
import zlib
from pathlib import Path

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.config import config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.adapter.mock")

__all__ = ["MockImageAdapter"]


def _minimal_png(width: int = 1600, height: int = 1600) -> bytes:
    """Create a minimal valid white PNG without Pillow."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # White RGB scanlines: filter byte 0 + width*3 bytes of 0xFF per row
    row = b"\x00" + b"\xff" * (width * 3)
    raw = b"".join(row for _ in range(height))
    idat = _chunk(b"IDAT", zlib.compress(raw, 1))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


class MockImageAdapter(BaseImageAdapter):
    def __init__(self) -> None:
        self._jobs: dict[str, ImageResult] = {}
        self._calls: list[dict] = []

    @property
    def calls(self) -> list[dict]:
        return list(self._calls)

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        job_id = uuid.uuid4().hex[:12]
        out_dir = Path(config.output_dir) / "mock"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{job_id}.png"
        dest.write_bytes(_minimal_png())

        result = ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=str(dest),
            metadata={"prompt": prompt, "params": params or {}, "adapter": "mock"},
        )
        self._jobs[job_id] = result
        self._calls.append({"method": "generate", "prompt": prompt, "params": params})
        logger.info("Mock generate job_id=%s path=%s", job_id, dest)
        return result

    def edit(
        self, image_paths: list[str], prompt: str, params: dict | None = None
    ) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        job_id = uuid.uuid4().hex[:12]
        out_dir = Path(config.output_dir) / "mock"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{job_id}.png"
        dest.write_bytes(_minimal_png())

        result = ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=str(dest),
            metadata={
                "prompt": prompt,
                "params": params or {},
                "adapter": "mock",
                "mode": "edit",
            },
        )
        self._jobs[job_id] = result
        self._calls.append(
            {
                "method": "edit",
                "prompt": prompt,
                "image_paths": image_paths,
                "params": params,
            }
        )
        logger.info("Mock edit job_id=%s path=%s", job_id, dest)
        return result

    def check_status(self, job_id: str) -> JobStatus:
        self._calls.append({"method": "check_status", "job_id": job_id})
        if job_id not in self._jobs:
            raise KeyError(f"E_ADAPTER_003: job {job_id} not found")
        return self._jobs[job_id].status

    def download_image(self, job_id: str, dest_path: str) -> str:
        self._calls.append(
            {"method": "download_image", "job_id": job_id, "dest_path": dest_path}
        )
        if job_id not in self._jobs:
            raise KeyError(f"E_ADAPTER_003: job {job_id} not found")
        result = self._jobs[job_id]
        if result.status != JobStatus.COMPLETED:
            raise RuntimeError(f"E_ADAPTER_004: job {job_id} not completed yet")
        if result.image_path and os.path.exists(result.image_path):
            import shutil

            shutil.copy2(result.image_path, dest_path)
        return dest_path
