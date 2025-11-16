# vsg_core/subtitles/preprocessing/image.py
# -*- coding: utf-8 -*-
"""
Image preprocessing pipeline for optimal Tesseract OCR.
Implements SubtitleEdit-style preprocessing for maximum accuracy.
"""

from __future__ import annotations
from typing import List
from PIL import Image, ImageFilter, ImageOps
import numpy as np


class ImagePreprocessor:
    """Preprocesses subtitle images for optimal OCR accuracy."""

    def __init__(self, config: dict, debug_dir: str = None):
        """
        Initialize preprocessor with configuration.

        Args:
            config: Configuration dictionary with preprocessing settings
            debug_dir: Optional directory to save debug images
        """
        self.target_dpi = config.get('ocr_target_dpi', 300)
        self.scale_enabled = config.get('ocr_preprocessing_scale', True)
        self.denoise_enabled = config.get('ocr_preprocessing_denoise', False)
        self.debug_dir = debug_dir
        self.debug_counter = 0

    def preprocess(self, image: Image.Image) -> List[Image.Image]:
        """
        Preprocess subtitle image for OCR.

        Args:
            image: Input PIL Image (RGBA)

        Returns:
            List of preprocessed PIL Images (one per line if multi-line)
        """
        # Step 1: Convert to grayscale with white background
        grayscale = self._invert_colors(image)

        # Step 2: Scale to target DPI
        if self.scale_enabled:
            scaled = self._scale_image(grayscale)
        else:
            scaled = grayscale

        # DISABLE binarization - let Tesseract handle it
        # DISABLE line segmentation - PSM 7 expects single line anyway

        # Return as single image
        return [scaled]

    def _invert_colors(self, image: Image.Image) -> Image.Image:
        """
        Convert subtitle image to grayscale.

        SIMPLE APPROACH: Just use PIL's built-in RGB to grayscale conversion
        with alpha compositing. Let Tesseract handle the rest.
        """
        # Convert to RGBA if needed
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # Create a white background image
        background = Image.new('RGB', image.size, (255, 255, 255))

        # Composite the subtitle onto white background using its alpha channel
        # This handles transparency properly
        background.paste(image, mask=image.split()[3])  # Use alpha as mask

        # Convert to grayscale
        grayscale = background.convert('L')

        # Save debug image if enabled
        if self.debug_dir:
            import os
            os.makedirs(self.debug_dir, exist_ok=True)
            debug_path = os.path.join(self.debug_dir, f'step1_grayscale_{self.debug_counter}.png')
            grayscale.save(debug_path)
            self.debug_counter += 1

        # Convert back to RGB for consistency
        return grayscale.convert('RGB')

    def _get_content_bbox(self, mask: np.ndarray) -> tuple:
        """Get bounding box of content (where mask is True)."""
        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)

        if not rows.any() or not cols.any():
            return None

        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]

        # Add small padding
        padding = 3
        rmin = max(0, rmin - padding)
        rmax = min(mask.shape[0] - 1, rmax + padding)
        cmin = max(0, cmin - padding)
        cmax = min(mask.shape[1] - 1, cmax + padding)

        return (cmin, rmin, cmax + 1, rmax + 1)

    def _scale_image(self, image: Image.Image) -> Image.Image:
        """
        Scale image to target DPI for optimal Tesseract accuracy.
        Tesseract works best at 300+ DPI.
        """
        # Estimate current DPI based on height
        # DVD subtitles are typically 20-30 pixels tall
        # Target: scale so text is equivalent to ~12pt at 300 DPI
        # 12pt at 300 DPI = 50 pixels tall

        current_height = image.height
        target_height = 50  # Approximate good height for OCR

        # Calculate scale factor
        if current_height < target_height:
            scale_factor = target_height / current_height
            # Limit maximum scale to avoid artifacts
            scale_factor = min(scale_factor, 4.0)
        else:
            scale_factor = 1.0

        if scale_factor > 1.1:  # Only scale if significant improvement
            new_width = int(image.width * scale_factor)
            new_height = int(image.height * scale_factor)

            # Use high-quality resampling
            scaled = image.resize((new_width, new_height), Image.LANCZOS)
            return scaled

        return image

    def _denoise(self, image: Image.Image) -> Image.Image:
        """Apply light denoising to reduce compression artifacts."""
        # Use a light Gaussian blur to smooth out MPEG compression artifacts
        # while preserving text edges
        denoised = image.filter(ImageFilter.GaussianBlur(radius=0.5))
        return denoised

    def _binarize(self, image: Image.Image) -> Image.Image:
        """
        Convert to pure black and white using Otsu's method.
        Tesseract has internal binarization, but pre-binarizing can help.
        """
        # Convert to grayscale first
        if image.mode != 'L':
            gray = image.convert('L')
        else:
            gray = image

        # Use PIL's built-in auto-contrast and then threshold
        # This is similar to Otsu's method
        gray = ImageOps.autocontrast(gray)

        # Simple threshold at midpoint
        # Tesseract will do additional processing
        binary = gray.point(lambda x: 0 if x < 128 else 255, mode='1')

        return binary.convert('RGB')  # Convert back to RGB for Tesseract

    def _segment_lines(self, image: Image.Image) -> List[Image.Image]:
        """
        Segment multi-line subtitles into individual lines.
        Processing each line separately with PSM 7 dramatically improves accuracy.
        """
        # Convert to grayscale for analysis
        if image.mode != 'L':
            gray = np.array(image.convert('L'))
        else:
            gray = np.array(image)

        # Find rows with text (dark pixels)
        row_has_text = np.mean(gray, axis=1) < 250  # Row has text if average is dark

        if not row_has_text.any():
            return [image]

        # Find contiguous regions of text (lines)
        lines = []
        in_line = False
        line_start = 0

        for i, has_text in enumerate(row_has_text):
            if has_text and not in_line:
                # Start of new line
                line_start = i
                in_line = True
            elif not has_text and in_line:
                # End of line
                line_end = i
                in_line = False

                # Extract line with padding
                padding = 2
                y1 = max(0, line_start - padding)
                y2 = min(image.height, line_end + padding)

                if y2 - y1 > 5:  # Minimum height threshold
                    line_img = image.crop((0, y1, image.width, y2))
                    lines.append(line_img)

        # Handle case where last line extends to bottom
        if in_line:
            padding = 2
            y1 = max(0, line_start - padding)
            y2 = image.height

            if y2 - y1 > 5:
                line_img = image.crop((0, y1, image.width, y2))
                lines.append(line_img)

        # If we found lines, return them; otherwise return original
        return lines if lines else [image]
