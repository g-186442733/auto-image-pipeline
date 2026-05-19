"""图像安全边距检测工具。

用于白底产品图的保守裁切/贴边检测。只在四角近白时启用，避免误杀
lifestyle、场景图、macro detail 等天然非白底或局部裁切图。
"""

from __future__ import annotations

from typing import Any

SAFE_FRAME_MIN_MARGIN_RATIO = 0.05
WHITE_BACKGROUND_THRESHOLD = 245
CORNER_SAMPLE_SIZE = 16
EDGE_BAND_RATIO = 0.01


def measure_white_bg_foreground_margins(image_path: str) -> dict[str, Any]:
    """测量白底产品图主体到画布四边的安全边距。"""
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            rgba = img.convert("RGBA")
            width, height = rgba.size
            pixels = rgba.load()

            sample = min(CORNER_SAMPLE_SIZE, width, height)
            corner_boxes = (
                (0, 0, sample, sample),
                (width - sample, 0, width, sample),
                (0, height - sample, sample, height),
                (width - sample, height - sample, width, height),
            )
            for left, top, right, bottom in corner_boxes:
                total = 0.0
                count = 0
                for y in range(top, bottom):
                    for x in range(left, right):
                        r, g, b, a = pixels[x, y]
                        if a < 16:
                            continue
                        total += ((255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2) ** 0.5
                        count += 1
                if count == 0 or total / count > 30:
                    return {
                        "applicable": False,
                        "reason": "non_white_background",
                        "width": width,
                        "height": height,
                    }

            def is_foreground(x: int, y: int) -> bool:
                r, g, b, a = pixels[x, y]
                if a < 16:
                    return False
                return not (
                    r > WHITE_BACKGROUND_THRESHOLD
                    and g > WHITE_BACKGROUND_THRESHOLD
                    and b > WHITE_BACKGROUND_THRESHOLD
                )

            min_x = width
            min_y = height
            max_x = -1
            max_y = -1
            edge_band = max(1, round(min(width, height) * EDGE_BAND_RATIO))
            edge_counts = {"top": 0, "right": 0, "bottom": 0, "left": 0}
            foreground_count = 0

            for y in range(height):
                for x in range(width):
                    if not is_foreground(x, y):
                        continue
                    foreground_count += 1
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)
                    if y < edge_band:
                        edge_counts["top"] += 1
                    if x >= width - edge_band:
                        edge_counts["right"] += 1
                    if y >= height - edge_band:
                        edge_counts["bottom"] += 1
                    if x < edge_band:
                        edge_counts["left"] += 1

            if foreground_count == 0:
                return {
                    "applicable": False,
                    "reason": "no_foreground_detected",
                    "width": width,
                    "height": height,
                }

            margins_px = {
                "left": min_x,
                "top": min_y,
                "right": width - 1 - max_x,
                "bottom": height - 1 - max_y,
            }
            margins_ratio = {
                side: value / (width if side in ("left", "right") else height)
                for side, value in margins_px.items()
            }
            return {
                "applicable": True,
                "width": width,
                "height": height,
                "foreground_box": {
                    "min_x": min_x,
                    "min_y": min_y,
                    "max_x": max_x,
                    "max_y": max_y,
                    "foreground_count": foreground_count,
                },
                "margins_px": margins_px,
                "margins_ratio": margins_ratio,
                "min_margin_ratio": min(margins_ratio.values()),
                "edge_band_px": edge_band,
                "edge_touch": {side: count > 0 for side, count in edge_counts.items()},
            }
    except Exception as exc:
        return {"applicable": False, "reason": f"read_failed:{exc}"}


def safe_frame_failed(
    metrics: dict[str, Any], min_margin_ratio: float = SAFE_FRAME_MIN_MARGIN_RATIO
) -> bool:
    """判断白底前景检测结果是否触发安全边距失败。"""
    if not metrics.get("applicable"):
        return False
    measured_min_margin = float(metrics.get("min_margin_ratio") or 0.0)
    edge_touch = metrics.get("edge_touch") or {}
    return measured_min_margin < min_margin_ratio or any(edge_touch.values())
