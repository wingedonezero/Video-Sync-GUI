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

        MINIMAL APPROACH matching VobSub-ML-OCR:
        - NO inversion (images are already correct from parser)
        - NO segmentation (let Tesseract handle multi-line)
        - ONLY scaling (Tesseract needs larger text)

        VobSub-ML-OCR does ZERO preprocessing and gets better results.

        Args:
            image: Input PIL Image (RGB or RGBA)

        Returns:
            List with single PIL Image
        """
        # Save debug image FIRST (the raw extracted image)
        if self.debug_dir:
            import os
            os.makedirs(self.debug_dir, exist_ok=True)
            debug_path = os.path.join(self.debug_dir, f'raw_extracted_{self.debug_counter}.png')
            image.save(debug_path)

        # Step 1: Convert to RGB if needed
        if image.mode == 'RGBA':
            # Composite onto white background
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            rgb_image = background
        elif image.mode != 'RGB':
            rgb_image = image.convert('RGB')
        else:
            rgb_image = image

        # Step 2: Scale ONLY (Tesseract likes larger text)
        if self.scale_enabled:
            scaled = self._scale_image(rgb_image)
        else:
            scaled = rgb_image

        # Save debug image
        if self.debug_dir:
            debug_path = os.path.join(self.debug_dir, f'preprocessed_{self.debug_counter}.png')
            scaled.save(debug_path)
            self.debug_counter += 1

        # Return as single image - NO segmentation, NO inversion, NO border
        return [scaled]

    def _normalize_background(self, image: Image.Image) -> Image.Image:
        """
        Normalize background for Tesseract (black text on white background).

        VobSub subtitles typically have white/colored text on dark background.
        Tesseract 4.0+ expects black text on white background.

        Args:
            image: RGB image

        Returns:
            Normalized RGB image with inverted colors if needed
        """
        # Convert to grayscale for analysis
        gray = image.convert('L')
        gray_array = np.array(gray)

        # Find non-white pixels (potential text)
        # White background is typically 240-255, so anything < 230 is content
        content_mask = gray_array < 230

        if not content_mask.any():
            # No content found, return as-is
            return image

        # Calculate average brightness of content pixels only
        content_brightness = np.mean(gray_array[content_mask])

        # If content is bright (white/light text), invert the image
        # Threshold: if average content brightness > 127, it's light text on dark background
        if content_brightness > 127:
            # Invert the image (white text -> black text, dark bg -> white bg)
            inverted = ImageOps.invert(image.convert('RGB'))
            return inverted
        else:
            # Already black text on white background
            return image

    def _add_border(self, image: Image.Image, padding: int = 10) -> Image.Image:
        """
        Add white border padding around image.

        Helps Tesseract with edge detection and prevents text being cut off.

        Args:
            image: Input image
            padding: Border size in pixels

        Returns:
            Image with white border
        """
        # Create new image with padding
        new_width = image.width + (padding * 2)
        new_height = image.height + (padding * 2)

        # Create white background
        padded = Image.new('RGB', (new_width, new_height), (255, 255, 255))

        # Paste original image in center
        padded.paste(image, (padding, padding))

        return padded

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
