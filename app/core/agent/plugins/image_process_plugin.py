"""
ImageProcessPlugin — 图像处理 (Pillow-backed)

从 web/adaptive_agent.py 的 image_proc 工具迁移而来,
适配 UnifiedAgent 插件体系。
"""

import os
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


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
    def image_info(filepath: str) -> str:
        """Return metadata about an image."""
        try:
            from PIL import Image

            img = Image.open(filepath)
            return (
                f"Format: {img.format}\n"
                f"Size: {img.size[0]}x{img.size[1]} px\n"
                f"Mode: {img.mode}"
            )
        except Exception as exc:
            return f"Error reading image info: {exc}"

    @staticmethod
    def image_resize(
        filepath: str, width: int, height: int, output_path: str = ""
    ) -> str:
        """Resize an image."""
        try:
            from PIL import Image

            img = Image.open(filepath)
            resized = img.resize((int(width), int(height)))
            if not output_path:
                base, ext = os.path.splitext(filepath)
                output_path = f"{base}_resized{ext}"
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            resized.save(output_path)
            return f"Image resized to {width}x{height} and saved to {output_path}"
        except Exception as exc:
            return f"Error resizing image: {exc}"

    @staticmethod
    def image_convert(filepath: str, target_format: str, output_path: str = "") -> str:
        """Convert an image to another format."""
        try:
            from PIL import Image

            img = Image.open(filepath)
            fmt = target_format.upper()
            if not output_path:
                base, _ = os.path.splitext(filepath)
                ext_map = {
                    "JPEG": ".jpg",
                    "PNG": ".png",
                    "WEBP": ".webp",
                    "BMP": ".bmp",
                    "GIF": ".gif",
                }
                ext = ext_map.get(fmt, f".{fmt.lower()}")
                output_path = f"{base}_converted{ext}"
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            # Handle RGBA → RGB for JPEG
            if fmt == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(output_path, format=fmt)
            return f"Image converted to {fmt} and saved to {output_path}"
        except Exception as exc:
            return f"Error converting image: {exc}"
