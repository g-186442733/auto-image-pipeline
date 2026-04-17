"""Adapter for gemini-2.5-flash-image-preview (image editing via chat completions)."""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

import httpx

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.config import config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.adapter.gemini_image")

__all__ = ["GeminiImageAdapter"]

_B64_IMG_PATTERN = re.compile(r"!\[.*?\]\(data:image/(\w+);base64,([A-Za-z0-9+/=]+)\)")


class GeminiImageAdapter(BaseImageAdapter):
    def __init__(self) -> None:
        if not config.api_key:
            raise RuntimeError("E_ADAPTER_001: AIP_API_KEY not set")
        self._base_url = config.api_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(120.0, connect=10.0)
        self._client_kwargs = {"timeout": self._timeout, "proxy": None}

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        return self.edit_image(image_b64=None, prompt=prompt, params=params)

    def edit_image(
        self,
        image_b64: str | None,
        prompt: str,
        params: dict | None = None,
        image_path: str | None = None,
    ) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        if image_path and not image_b64:
            p = Path(image_path)
            if not p.exists():
                raise FileNotFoundError(f"E_ADAPTER_002: image not found: {image_path}")
            image_b64 = base64.b64encode(p.read_bytes()).decode()

        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                }
            )

        payload = {
            "model": params.get("model", config.edit_model)
            if params
            else config.edit_model,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["text", "image"],
        }

        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
            **self._client_kwargs,
        )
        resp.raise_for_status()
        body = resp.json()

        reply = body["choices"][0]["message"]["content"]
        match = _B64_IMG_PATTERN.search(reply)

        job_id = uuid.uuid4().hex[:12]
        out_path: str | None = None

        if match:
            fmt = match.group(1)
            img_data = base64.b64decode(match.group(2))
            out_dir = Path(config.image_output_dir) / "gemini_image"
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / f"{job_id}.{fmt}"
            dest.write_bytes(img_data)
            out_path = str(dest)
            logger.info("Gemini image saved: %s (%d bytes)", dest, len(img_data))
        else:
            logger.warning("No image found in Gemini response for job %s", job_id)

        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED if out_path else JobStatus.FAILED,
            image_path=out_path,
            error=None if out_path else "No image in response",
            metadata={
                "adapter": "gemini_image",
                "model": config.edit_model,
                "text_reply": reply[:500] if not match else None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    def check_status(self, job_id: str) -> JobStatus:
        return JobStatus.COMPLETED

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError(
            "Gemini returns images inline; use generate()/edit_image() result directly"
        )
