#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Image Generator for Koto
Cloud image generation is disabled until an active image provider is configured.
"""

import logging

logger = logging.getLogger(__name__)


class ImageGenerator:
    """
    Provides deterministic local placeholders while cloud image generation is disabled.
    """

    def __init__(self, api_key: str = None):
        self.client = None
        self.image_model = None

    def generate_image(
        self, prompt: str, output_path: str, aspect_ratio: str = "16:9"
    ) -> bool:
        """
        Generates an image from prompt and saves to output_path.

        Args:
            prompt: Description of image
            output_path: Local path to save the generated image (PNG/JPEG)
            aspect_ratio: "1:1", "3:4", "4:3", "9:16", "16:9"

        Returns:
            True if successful, False otherwise.
        """
        logger.info("[ImageGenerator] Cloud image generation is not configured")
        return False

    def generate_placeholder(self, prompt: str, output_path: str):
        """Generates a local placeholder image (solid color with text) if AI fails."""
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
            d = ImageDraw.Draw(img)
            # Draw text
            # Need a font, default to basic
            d.text((100, 360), f"Image Placeholder\n{prompt}", fill=(255, 255, 255))
            img.save(output_path)
        except ImportError:
            # Fallback if Pillow not installed (unlikely based on requirements)
            with open(output_path, "wb") as f:
                f.write(b"")  # Empty file
