"""Adapter for gemini-2.5-flash-image-preview (image editing via chat completions)."""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

import httpx
from PIL import Image as PilImage
import io

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

    def _save_image(self, img_data: bytes, fmt: str, out_dir: Path, job_id: str) -> str:
        target = config.image_output_size
        img = PilImage.open(io.BytesIO(img_data))
        if img.size != (target, target):
            img = img.resize((target, target), PilImage.Resampling.LANCZOS)
        dest = out_dir / f"{job_id}.{fmt}"
        img.save(str(dest))
        return str(dest)

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

        primary_model = (
            params.get("model", config.image_model) if params else config.image_model
        )
        payload = {
            "model": primary_model,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["text", "image"],
        }

        try:
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
            match = _B64_IMG_PATTERN.search(reply)
        except Exception as exc:
            logger.warning(
                "Gemini primary failed (%s), falling back to %s",
                exc,
                config.fallback_model,
            )
            from pipeline.adapters.gpt_image_adapter import GptImageAdapter

            fb_params = {"model": config.fallback_model}
            if image_b64:
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(base64.b64decode(image_b64))
                    tmp_path = tmp.name
                return GptImageAdapter().edit(tmp_path, prompt, params=fb_params)
            return GptImageAdapter().generate(prompt, params=fb_params)

        job_id = uuid.uuid4().hex[:12]
        out_path: str | None = None

        if match:
            fmt = match.group(1)
            img_data = base64.b64decode(match.group(2))
            out_dir = Path(config.image_output_dir) / "gemini_image"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._save_image(img_data, fmt, out_dir, job_id)
            logger.info(
                "Gemini image saved: %s (%dx%d)",
                out_path,
                config.image_output_size,
                config.image_output_size,
            )
        else:
            logger.warning(
                "No image in Gemini response for job %s, falling back to %s",
                job_id,
                config.fallback_model,
            )
            from pipeline.adapters.gpt_image_adapter import GptImageAdapter

            fb_params = {"model": config.fallback_model}
            if image_b64:
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(base64.b64decode(image_b64))
                    tmp_path = tmp.name
                return GptImageAdapter().edit(tmp_path, prompt, params=fb_params)
            return GptImageAdapter().generate(prompt, params=fb_params)

        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=out_path,
            error=None,
            metadata={
                "adapter": "gemini_image",
                "model": primary_model,
                "text_reply": None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    def edit(
        self,
        image_paths: list[str],
        prompt: str,
        params: dict | None = None,
    ) -> ImageResult:
        """接收多张图片路径（白底图 + 多角度图），一并发给 Gemini 进行图像编辑。

        Args:
            image_paths: 图片路径列表，第一张为白底图，其余为多角度参考图。
            prompt: 生图提示词。
            params: 可选的额外参数（如指定 model）。
        """
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")
        if not image_paths:
            raise ValueError("E_ADAPTER_003: image_paths must not be empty")

        content: list[dict] = [{"type": "text", "text": prompt}]

        for idx, img_path in enumerate(image_paths):
            p = Path(img_path)
            if not p.exists():
                logger.warning("图片不存在，跳过：%s", img_path)
                continue
            image_b64 = base64.b64encode(p.read_bytes()).decode()
            # 第一张是白底图，其余是多角度参考图，通过 detail 字段区分
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high" if idx == 0 else "low",
                    },
                }
            )

        primary_model = (
            params.get("model", config.image_model) if params else config.image_model
        )
        payload = {
            "model": primary_model,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["text", "image"],
        }

        try:
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
            match = _B64_IMG_PATTERN.search(reply)
        except Exception as exc:
            logger.warning(
                "Gemini edit primary failed (%s), falling back to %s",
                exc,
                config.fallback_model,
            )
            from pipeline.adapters.gpt_image_adapter import GptImageAdapter

            return GptImageAdapter().edit(
                image_paths, prompt, params={"model": config.fallback_model}
            )

        job_id = uuid.uuid4().hex[:12]
        out_path: str | None = None

        if match:
            fmt = match.group(1)
            img_data = base64.b64decode(match.group(2))
            out_dir = Path(config.image_output_dir) / "gemini_image"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._save_image(img_data, fmt, out_dir, job_id)
            logger.info(
                "Gemini edit image saved: %s (%dx%d), input images: %d",
                out_path,
                config.image_output_size,
                config.image_output_size,
                len(image_paths),
            )
        else:
            logger.warning(
                "No image in Gemini edit response for job %s, falling back to %s",
                job_id,
                config.fallback_model,
            )
            from pipeline.adapters.gpt_image_adapter import GptImageAdapter

            return GptImageAdapter().edit(
                image_paths, prompt, params={"model": config.fallback_model}
            )

        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=out_path,
            error=None,
            metadata={
                "adapter": "gemini_image",
                "model": primary_model,
                "text_reply": None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "input_image_count": len(image_paths),
            },
        )

    def check_status(self, job_id: str) -> JobStatus:
        return JobStatus.COMPLETED

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError(
            "Gemini returns images inline; use generate()/edit_image() result directly"
        )
