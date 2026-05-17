"""Adapter for gpt-image series via 147AI (OpenAI-compatible API).

gpt-image-2-client 走 /v1/chat/completions + tools=[image_generation]
其他 gpt-image-* 走 /v1/images/generations（标准路径）
"""

from __future__ import annotations

import base64
import re
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
    "n": 1,
}

_GPT_IMAGE_EXTRA_PARAMS = {
    "quality": "medium",
    "background": "auto",
    "output_format": "png",
}

_BASE64_PATTERN = re.compile(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)")


def _is_client_model(model: str) -> bool:
    return model.endswith("-client")


def _is_gpt_image_model(model: str) -> bool:
    return model.startswith("gpt-image")


def _is_gemini_model(model: str) -> bool:
    return "gemini" in model.lower()


def _extract_b64_from_content(content: str) -> str | None:
    m = _BASE64_PATTERN.search(content)
    return m.group(1) if m else None


def _save_b64(b64_data: str, out_dir: Path, suffix: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{job_id}{suffix}.png"
    dest.write_bytes(base64.b64decode(b64_data))
    return str(dest)


def _save_url(url: str, out_dir: Path, suffix: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{job_id}{suffix}.png"
    dl = httpx.get(url, timeout=60.0, follow_redirects=True)
    dl.raise_for_status()
    dest.write_bytes(dl.content)
    return str(dest)


class GptImageAdapter(BaseImageAdapter):
    def __init__(self) -> None:
        if not config.api_key:
            raise RuntimeError("E_ADAPTER_001: AIP_API_KEY not set")
        self._base_url = config.api_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(180.0, connect=10.0)
        self._client_kwargs = {"timeout": self._timeout, "proxy": None}
        self._out_dir = Path(config.image_output_dir) / "gpt_image"

    # ──────────────────────────────────────────────────────────────
    # 内部：chat completions 路径（gpt-image-2-client 专用）
    # ──────────────────────────────────────────────────────────────

    def _generate_via_chat(self, prompt: str, model: str, params: dict) -> ImageResult:
        size = params.get("size", "1024x1024")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "image_generation", "size": size}],
            "tool_choice": "required",
        }
        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
            **self._client_kwargs,
        )
        if resp.status_code >= 400:
            logger.error("chat API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

        body = resp.json()
        content = body["choices"][0]["message"]["content"] or ""
        b64_data = _extract_b64_from_content(content)

        image_path: str | None = None
        if b64_data:
            image_path = _save_b64(b64_data, self._out_dir)

        job_id = uuid.uuid4().hex[:12]
        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=image_path,
            metadata={
                "adapter": "gpt_image",
                "model": model,
                "path": "chat",
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
        )

    def _edit_via_chat(
        self, image_paths: list[str], prompt: str, model: str, params: dict
    ) -> ImageResult:
        size = params.get("size", "1024x1024")
        content_parts: list[dict] = []
        for p in image_paths:
            raw = Path(p).read_bytes()
            b64 = base64.b64encode(raw).decode()
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        content_parts.append({"type": "text", "text": prompt})

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content_parts}],
            "tools": [{"type": "image_generation", "size": size}],
            "tool_choice": "required",
        }
        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
            **self._client_kwargs,
        )
        if resp.status_code >= 400:
            logger.error("chat edit API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

        body = resp.json()
        content = body["choices"][0]["message"]["content"] or ""
        b64_data = _extract_b64_from_content(content)

        image_path: str | None = None
        if b64_data:
            image_path = _save_b64(b64_data, self._out_dir, suffix="_edit")

        job_id = uuid.uuid4().hex[:12]
        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_path=image_path,
            metadata={
                "adapter": "gpt_image",
                "mode": "edit",
                "model": model,
                "path": "chat",
                "image_count": len(image_paths),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
        )

    # ──────────────────────────────────────────────────────────────
    # 内部：images/generations 路径（标准 gpt-image-* 模型）
    # ──────────────────────────────────────────────────────────────

    def _generate_via_api(self, prompt: str, model: str, params: dict) -> ImageResult:
        base = dict(_DEFAULT_PARAMS)
        if _is_gpt_image_model(model):
            base.update(_GPT_IMAGE_EXTRA_PARAMS)
        merged = {**base, **params, "model": model, "prompt": prompt}

        resp = httpx.post(
            f"{self._base_url}/images/generations",
            headers=self._headers,
            json=merged,
            **self._client_kwargs,
        )
        if resp.status_code >= 400:
            logger.error("API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

        body = resp.json()
        job_id = uuid.uuid4().hex[:12]
        b64_data = body["data"][0].get("b64_json")
        image_url = body["data"][0].get("url")

        image_path: str | None = None
        if b64_data:
            image_path = _save_b64(b64_data, self._out_dir)
        elif image_url:
            image_path = _save_url(image_url, self._out_dir)

        usage = body.get("usage", {})
        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_url=image_url,
            image_path=image_path,
            metadata={
                "adapter": "gpt_image",
                "model": model,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
        )

    def _edit_via_api(
        self, image_paths: list[str], prompt: str, model: str, params: dict
    ) -> ImageResult:
        data = {
            "model": model,
            "prompt": prompt,
            **{k: str(v) for k, v in params.items()},
        }
        data.setdefault("quality", "high")
        data.setdefault("n", "1")
        data.setdefault("size", "1024x1024")

        headers = {"Authorization": f"Bearer {config.api_key}"}
        file_handles = []
        try:
            files = []
            for p in image_paths:
                path_obj = Path(p)
                if not path_obj.exists():
                    raise FileNotFoundError(f"E_ADAPTER_002: image not found: {p}")
                fh = path_obj.open("rb")
                file_handles.append(fh)
                files.append(("image", (path_obj.name, fh, "image/png")))

            resp = httpx.post(
                f"{self._base_url}/images/edits",
                headers=headers,
                data=data,
                files=files,
                **self._client_kwargs,
            )
        finally:
            for fh in file_handles:
                fh.close()

        if resp.status_code >= 400:
            logger.error("API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

        body = resp.json()
        job_id = uuid.uuid4().hex[:12]
        result_url = body["data"][0].get("url")
        result_b64 = body["data"][0].get("b64_json")

        out_path: str | None = None
        if result_b64:
            out_path = _save_b64(result_b64, self._out_dir, suffix="_edit")
        elif result_url:
            out_path = _save_url(result_url, self._out_dir, suffix="_edit")

        return ImageResult(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            image_url=result_url,
            image_path=out_path,
            metadata={
                "adapter": "gpt_image",
                "mode": "edit",
                "model": model,
                "image_count": len(image_paths),
            },
        )

    # ──────────────────────────────────────────────────────────────
    # 公共接口
    # ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, params: dict | None = None) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        model = (params or {}).get("model", config.image_model)
        clean_params = {k: v for k, v in (params or {}).items() if k != "model"}

        try:
            if _is_client_model(model):
                return self._generate_via_chat(prompt, model, clean_params)
            return self._generate_via_api(prompt, model, clean_params)
        except Exception as exc:
            logger.error(
                "GptImage primary failed (%s), falling back to %s",
                exc,
                config.fallback_model,
            )
            try:
                if _is_gemini_model(config.fallback_model):
                    from pipeline.adapters.gemini_image_adapter import GeminiImageAdapter

                    return GeminiImageAdapter().generate(
                        prompt,
                        params={**clean_params, "model": config.fallback_model},
                    )
                return self.generate(
                    prompt, params={**clean_params, "model": config.fallback_model}
                )
            except Exception as fb_exc:
                logger.error(
                    "GptImage fallback failed (%s), falling back to Gemini",
                    fb_exc,
                )
                from pipeline.adapters.gemini_image_adapter import GeminiImageAdapter

                return GeminiImageAdapter().generate(prompt, params=clean_params)

    def edit(
        self, image_paths: str | list[str], prompt: str, params: dict | None = None
    ) -> ImageResult:
        if not prompt:
            raise ValueError("E_ADAPTER_002: prompt must be non-empty")

        paths = [image_paths] if isinstance(image_paths, str) else list(image_paths)
        if not paths:
            raise ValueError("E_ADAPTER_002: at least one image_path required")

        model = (params or {}).get("model", config.edit_model)
        clean_params = {k: v for k, v in (params or {}).items() if k != "model"}

        try:
            if _is_client_model(model):
                return self._edit_via_chat(paths, prompt, model, clean_params)
            return self._edit_via_api(paths, prompt, model, clean_params)
        except Exception as exc:
            logger.error(
                "GptImage edit primary failed (%s), falling back to %s",
                exc,
                config.fallback_model,
            )
            try:
                if _is_gemini_model(config.fallback_model):
                    from pipeline.adapters.gemini_image_adapter import GeminiImageAdapter

                    return GeminiImageAdapter().edit(
                        paths,
                        prompt,
                        params={**clean_params, "model": config.fallback_model},
                    )
                return self.edit(
                    image_paths,
                    prompt,
                    params={**clean_params, "model": config.fallback_model},
                )
            except Exception as fb_exc:
                logger.error(
                    "GptImage edit fallback failed (%s), falling back to Gemini",
                    fb_exc,
                )
                from pipeline.adapters.gemini_image_adapter import GeminiImageAdapter

                return GeminiImageAdapter().edit(
                    image_paths, prompt, params=clean_params
                )

    def check_status(self, job_id: str) -> JobStatus:
        return JobStatus.COMPLETED

    def download_image(self, job_id: str, dest_path: str) -> str:
        raise NotImplementedError(
            "gpt-image returns images inline; use generate() result directly"
        )
