"""Adapter registry — register and retrieve image generation adapters."""

from __future__ import annotations

from typing import Type

from pipeline.adapters.base import BaseImageAdapter
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.adapter.registry")

__all__ = ["register_adapter", "get_adapter"]

_REGISTRY: dict[str, Type[BaseImageAdapter]] = {}


def register_adapter(name: str, adapter_cls: Type[BaseImageAdapter]) -> None:
    _REGISTRY[name] = adapter_cls
    logger.info("Registered adapter '%s' -> %s", name, adapter_cls.__name__)


def get_adapter(name: str) -> BaseImageAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"E_ADAPTER_001: adapter '{name}' not configured")
    return _REGISTRY[name]()


def _bootstrap() -> None:
    from pipeline.adapters.mock_adapter import MockImageAdapter

    register_adapter("mock", MockImageAdapter)


_bootstrap()
