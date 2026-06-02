# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
ImageProcessPlugin — 图像处理 (Pillow-backed)

从 web/adaptive_agent.py 的 image_proc 工具迁移而来,
适配 UnifiedAgent 插件体系。
"""

import os
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from app.core.agent.path_utils import resolve_existing_path


class ImageProcessPlugin(AgentPlugin):
    """Provides image manipulation capabilities via Pillow."""

    @property
    def name(self) -> str:
        return "ImageProcess"

    @property
    def description(self) -> str:
        return "Resize, convert, and inspect images using Pillow."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "image_info",
                "func": self.image_info,
                "description": "Get metadata about an image file (format, size, mode).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Path to the image file.",
                        }
                    },
                    "required": ["filepath"],
                },
            },
            {
                "name": "image_resize",
                "func": self.image_resize,
                "description": "Resize an image to the specified width and height. "
                "Saves the result to output_path (or adds '_resized' suffix).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Path to the source image.",
                        },
                        "width": {
                            "type": "INTEGER",
                            "description": "Target width in pixels.",
                        },
                        "height": {
                            "type": "INTEGER",
                            "description": "Target height in pixels.",
                        },
                        "output_path": {
                            "type": "STRING",
                            "description": "Optional output path. If omitted, '_resized' is appended to the filename.",
                        },
                    },
                    "required": ["filepath", "width", "height"],
                },
            },
            {
                "name": "image_convert",
                "func": self.image_convert,
                "description": "Convert an image to a different format (e.g. PNG, JPEG, BMP, WEBP).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Path to the source image.",
                        },
                        "target_format": {
                            "type": "STRING",
                            "description": "Target format, e.g. 'PNG', 'JPEG', 'WEBP', 'BMP'.",
                        },
                        "output_path": {
                            "type": "STRING",
                            "description": "Optional output path.",
                        },
                    },
                    "required": ["filepath", "target_format"],
                },
            },
        ]

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_image_path(filepath: str) -> tuple[str | None, str | None, bool]:
        resolved, err = resolve_existing_path(filepath)
        if resolved:
            return resolved, None, True
        # Compatibility fallback: allow downstream image loader to attempt raw path
        # (useful for unit tests with mocked PIL open).
        return filepath, err, False

    @classmethod
    def image_info(cls, filepath: str) -> str:
        """Return metadata about an image."""
        try:
            from PIL import Image

            resolved, err, from_resolver = cls._resolve_image_path(filepath)
            if not resolved:
                return f"Error reading image info: {err or 'empty path'}"

            try:
                img = Image.open(resolved)
            except Exception as exc:
                if not from_resolver and err:
                    return f"Error reading image info: {err}"
                return f"Error reading image info: {exc}"
            return (
                f"File: {resolved}\n"
                f"Format: {img.format}\n"
                f"Size: {img.size[0]}x{img.size[1]} px\n"
                f"Mode: {img.mode}"
            )
        except Exception as exc:
            return f"Error reading image info: {exc}"

    @classmethod
    def image_resize(
        cls, filepath: str, width: int, height: int, output_path: str = ""
    ) -> str:
        """Resize an image."""
        try:
            from PIL import Image

            resolved, err, from_resolver = cls._resolve_image_path(filepath)
            if not resolved:
                return f"Error resizing image: {err or 'empty path'}"

            try:
                img = Image.open(resolved)
            except Exception as exc:
                if not from_resolver and err:
                    return f"Error resizing image: {err}"
                return f"Error resizing image: {exc}"
            resized = img.resize((int(width), int(height)))
            if not output_path:
                base, ext = os.path.splitext(resolved)
                output_path = f"{base}_resized{ext}"
            elif not os.path.isabs(output_path):
                output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            resized.save(output_path)
            return f"Image resized to {width}x{height} and saved to {output_path}"
        except Exception as exc:
            return f"Error resizing image: {exc}"

    @classmethod
    def image_convert(
        cls, filepath: str, target_format: str, output_path: str = ""
    ) -> str:
        """Convert an image to another format."""
        try:
            from PIL import Image

            resolved, err, from_resolver = cls._resolve_image_path(filepath)
            if not resolved:
                return f"Error converting image: {err or 'empty path'}"

            try:
                img = Image.open(resolved)
            except Exception as exc:
                if not from_resolver and err:
                    return f"Error converting image: {err}"
                return f"Error converting image: {exc}"
            fmt = target_format.upper()
            if not output_path:
                base, _ = os.path.splitext(resolved)
                ext_map = {
                    "JPEG": ".jpg",
                    "PNG": ".png",
                    "WEBP": ".webp",
                    "BMP": ".bmp",
                    "GIF": ".gif",
                }
                ext = ext_map.get(fmt, f".{fmt.lower()}")
                output_path = f"{base}_converted{ext}"
            elif not os.path.isabs(output_path):
                output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            # Handle RGBA → RGB for JPEG
            if fmt == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(output_path, format=fmt)
            return f"Image converted to {fmt} and saved to {output_path}"
        except Exception as exc:
            return f"Error converting image: {exc}"
