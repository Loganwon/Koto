# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MAX_IMG_DIMENSION = 1200
MAX_IMG_BYTES = 300 * 1024
MAX_BLOB_BYTES = 15 * 1024 * 1024


def compress_image_bytes(
    img_bytes: bytes,
    content_type: str = "image/png",
) -> tuple[bytes, str]:
    if len(img_bytes) <= MAX_IMG_BYTES:
        return img_bytes, content_type
    try:
        from PIL import Image as PILImage

        pil_img = PILImage.open(io.BytesIO(img_bytes))
        width, height = pil_img.size
        if width > MAX_IMG_DIMENSION or height > MAX_IMG_DIMENSION:
            ratio = min(MAX_IMG_DIMENSION / width, MAX_IMG_DIMENSION / height)
            pil_img = pil_img.resize(
                (int(width * ratio), int(height * ratio)),
                PILImage.LANCZOS,
            )

        if pil_img.mode in ("RGBA", "P", "LA"):
            bg = PILImage.new("RGB", pil_img.size, (255, 255, 255))
            if pil_img.mode == "P":
                pil_img = pil_img.convert("RGBA")
            bg.paste(pil_img, mask=pil_img.split()[-1])
            pil_img = bg

        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=82, optimize=True)
        compressed = buf.getvalue()
        logger.info(
            "[compress_image_bytes] %dx%d -> %dx%d, %.0f KB -> %.0f KB",
            width,
            height,
            pil_img.size[0],
            pil_img.size[1],
            len(img_bytes) / 1024,
            len(compressed) / 1024,
        )
        return compressed, "image/jpeg"
    except ImportError:
        return img_bytes, content_type
    except Exception as exc:
        logger.debug("[compress_image_bytes] failed (using original): %s", exc)
        return img_bytes, content_type
