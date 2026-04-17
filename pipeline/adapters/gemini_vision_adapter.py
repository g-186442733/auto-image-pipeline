"""Adapter for gemini-2.5-flash vision analysis (competitor listing analysis)."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

import httpx

from pipeline.adapters.base import BaseImageAdapter, ImageResult, JobStatus
from pipeline.config import config
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.adapter.gemini_vision")

__all__ = ["GeminiVisionAdapter"]


class GeminiVisionAdapter(BaseImageAdapter):
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

    def analyze(
        self,
        image_path: str,
        prompt: str,
        params: dict | None = None,
    ) -> dict:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        p = Path(image_path)
        if not p.exists():
            raise FileNotFoundError(f"E_ADAPTER_002: image not found: {image_path}")

        image_b64 = base64.b64encode(p.read_bytes()).decode()

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            },
        ]

        payload = {
            "model": params.get("model", config.vision_model)
            if params
            else config.vision_model,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
        }

        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
            **self._client_kwargs,
        )
        if resp.status_code >= 400:
            logger.error("API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        body = resp.json()

        reply = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})

        return {
            "analysis": reply,
            "model": config.vision_model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        return ImageResult(
            job_id=uuid.uuid4().hex[:12],
            status=JobStatus.FAILED,
            error="GeminiVisionAdapter is for analysis, not generation. Use analyze() instead.",
        )

    def check_status(self, job_id: str) -> JobStatus:
        return JobStatus.COMPLETED

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError("GeminiVisionAdapter does not generate images")
