from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ALLOWED_ROOTS = (
    _PROJECT_ROOT / "data",
    _PROJECT_ROOT / "output",
    _PROJECT_ROOT / "browser-outputs",
    _PROJECT_ROOT / "uploads",
)
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _allowed_roots() -> list[Path]:
    roots = list(_DEFAULT_ALLOWED_ROOTS)
    extra = os.getenv("AIP_ALLOWED_IMAGE_ROOTS", "")
    for raw in extra.split(os.pathsep):
        value = raw.strip()
        if value:
            roots.append(Path(value).expanduser())
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(root.resolve())
        except OSError:
            continue
    return resolved


def _is_under_allowed_root(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def validate_external_image_path(path: str | None) -> str | None:
    """Return a safe image path allowed for external model upload, otherwise None."""
    if not path:
        return None
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file():
        return None
    if resolved.suffix.lower() not in _ALLOWED_EXTENSIONS:
        return None
    if not _is_under_allowed_root(resolved, _allowed_roots()):
        return None
    try:
        from PIL import Image

        with Image.open(resolved) as img:
            img.verify()
    except Exception:
        return None
    return str(resolved)


def filter_external_image_paths(paths: list[str] | tuple[str, ...] | None) -> list[str]:
    """Keep only safe, real images that may be sent to external model APIs."""
    safe: list[str] = []
    seen: set[str] = set()
    for path in paths or []:
        validated = validate_external_image_path(path)
        if validated and validated not in seen:
            safe.append(validated)
            seen.add(validated)
    return safe
