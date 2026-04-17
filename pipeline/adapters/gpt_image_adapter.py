"""Adapter for gpt-image-1 via 147AI (OpenAI-compatible API)."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

import httpx

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.config import config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.adapter.gpt_image")

__all__ = ["GptImageAdapter"]

_DEFAULT_PARAMS = {
    "size": "1024x1024",
    "quality": "medium",
    "background": "auto",
    "output_format": "b64_json",
    "n": 1,
}


class GptImageAdapter(BaseImageAdapter):
    def __init__(self) -> None:
        if not config.api_key:
            raise RuntimeError("E_ADAPTER_001: AIP_API_KEY not set")
        self._base_url = config.api_base_url.rstrip("/")
        self._headers = {
            "Authorization": config.api_key,
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(120.0, connect=10.0)

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        merged = {**_DEFAULT_PARAMS, **(params or {})}
        merged["model"] = config.image_model
        merged["prompt"] = prompt

        resp = httpx.post(
            f"{self._base_url}/images/generations",
            headers=self._headers,
            json=merged,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        job_id = uuid.uuid4().hex[:12]
        b64_data = body["data"][0].get("b64_json")
        image_url = body["data"][0].get("url")

        image_path: str | None = None
        if b64_data:
            out_dir = Path(config.image_output_dir) / "gpt_image"
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / f"{job_id}.png"
            dest.write_bytes(base64.b64decode(b64_data))
            image_path = str(dest)

        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_url=image_url,
            image_path=image_path,
            metadata={
                "adapter": "gpt_image",
                "model": config.image_model,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
        )

    def edit(
        self, image_path: str, prompt: str, params: dict | None = None
    ) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        p = Path(image_path)
        if not p.exists():
            raise FileNotFoundError(f"E_ADAPTER_002: image not found: {image_path}")

        merged = {**(params or {})}
        merged.setdefault("quality", "high")
        merged.setdefault("n", 1)
        merged.setdefault("size", "1024x1024")

        with p.open("rb") as f:
            files = {"image": (p.name, f, "image/png")}
            data = {
                "model": config.image_model,
                "prompt": prompt,
                **{k: str(v) for k, v in merged.items()},
            }
            headers = {"Authorization": config.api_key}
            resp = httpx.post(
                f"{self._base_url}/images/edits",
                headers=headers,
                data=data,
                files=files,
                timeout=self._timeout,
            )
        resp.raise_for_status()
        body = resp.json()

        job_id = uuid.uuid4().hex[:12]
        result_url = body["data"][0].get("url")
        result_b64 = body["data"][0].get("b64_json")

        out_path: str | None = None
        if result_b64:
            out_dir = Path(config.image_output_dir) / "gpt_image"
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / f"{job_id}_edit.png"
            dest.write_bytes(base64.b64decode(result_b64))
            out_path = str(dest)

        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_url=result_url,
            image_path=out_path,
            metadata={
                "adapter": "gpt_image",
                "mode": "edit",
                "model": config.image_model,
            },
        )

    def check_status(self, job_id: str) -> JobStatus:
        return JobStatus.COMPLETED

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError(
            "gpt-image-1 returns images inline; use generate() result directly"
        )
