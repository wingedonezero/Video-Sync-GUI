# vsg_core/subtitles/pgs/preprocessor.py
# -*- coding: utf-8 -*-
"""
Image preprocessing for OCR optimization.
Based on SubtitleEdit's preprocessing techniques.
"""
from __future__ import annotations
from dataclasses import dataclass
from PIL import Image, ImageOps, ImageEnhance
from typing import Tuple


@dataclass
class PreprocessSettings:
    """Settings for image preprocessing"""
    crop_transparent: bool = True
    crop_max: int = 20
    add_margin: int = 10
    invert_colors: bool = False
    yellow_to_white: bool = True
    binarize: bool = True
    binarize_threshold: int = 200
    scale_percent: int = 100
    enhance_contrast: float = 1.5  # Contrast enhancement factor


def replace_yellow_with_white(img: Image.Image) -> Image.Image:
    """
    Replace yellow text with white for better OCR.
    Yellow subtitles are common and OCR works better with white text.

    Args:
        img: PIL Image (RGBA)

    Returns:
        Modified image with yellow replaced by white
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    pixels = img.load()
    width, height = img.size

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]

            # Detect yellow: high R, high G, low B, high alpha
            if r > 200 and g > 200 and b < 100 and a > 200:
                pixels[x, y] = (255, 255, 255, a)  # Replace with white

    return img


def replace_color_with_white(img: Image.Image, target_color: Tuple[int, int, int], tolerance: int = 30) -> Image.Image:
    """
    Replace a specific color with white.

    Args:
        img: PIL Image (RGBA)
        target_color: RGB tuple to replace
        tolerance: Color matching tolerance (0-255)

    Returns:
        Modified image
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    pixels = img.load()
    width, height = img.size
    target_r, target_g, target_b = target_color

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]

            # Check if color matches within tolerance
            if (abs(r - target_r) <= tolerance and
                abs(g - target_g) <= tolerance and
                abs(b - target_b) <= tolerance and
                a > 10):
                pixels[x, y] = (255, 255, 255, a)

    return img


def binarize_image(img: Image.Image, threshold: int = 200) -> Image.Image:
    """
    Convert image to black and white (binarization) for optimal OCR.
    Tesseract works best with high-contrast black and white images.

    Args:
        img: PIL Image (RGBA)
        threshold: Brightness threshold (0-255)

    Returns:
        Binarized image
    """
    # Convert to grayscale
    if img.mode == 'RGBA':
        # Create white background
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])  # Alpha channel as mask
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    grayscale = img.convert('L')

    # Apply threshold
    binarized = grayscale.point(lambda x: 255 if x > threshold else 0, mode='1')

    return binarized.convert('RGB')


def add_margin(img: Image.Image, margin: int, color: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """
    Add margin around image to improve OCR.
    OCR engines work better when text has some spacing from edges.

    Args:
        img: PIL Image
        margin: Margin size in pixels
        color: Margin color (default white)

    Returns:
        Image with margin added
    """
    if margin <= 0:
        return img

    # For RGBA images, use transparent or white background
    if img.mode == 'RGBA':
        new_img = Image.new('RGBA', (img.width + 2 * margin, img.height + 2 * margin), (*color, 0))
    else:
        new_img = Image.new(img.mode, (img.width + 2 * margin, img.height + 2 * margin), color)

    new_img.paste(img, (margin, margin))
    return new_img


def invert_colors(img: Image.Image) -> Image.Image:
    """
    Invert image colors (useful if OCR prefers white text on black background).

    Args:
        img: PIL Image

    Returns:
        Inverted image
    """
    if img.mode == 'RGBA':
        r, g, b, a = img.split()
        rgb = Image.merge('RGB', (r, g, b))
        inverted_rgb = ImageOps.invert(rgb)
        r2, g2, b2 = inverted_rgb.split()
        return Image.merge('RGBA', (r2, g2, b2, a))
    else:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return ImageOps.invert(img)


def scale_image(img: Image.Image, scale_percent: int) -> Image.Image:
    """
    Scale image by percentage.

    Args:
        img: PIL Image
        scale_percent: Scale percentage (100 = no change, 200 = double size)

    Returns:
        Scaled image
    """
    if scale_percent == 100:
        return img

    new_width = int(img.width * scale_percent / 100)
    new_height = int(img.height * scale_percent / 100)

    # Use LANCZOS for high-quality downscaling, BICUBIC for upscaling
    if scale_percent < 100:
        resample = Image.LANCZOS
    else:
        resample = Image.BICUBIC

    return img.resize((new_width, new_height), resample)


def enhance_contrast(img: Image.Image, factor: float = 1.5) -> Image.Image:
    """
    Enhance image contrast for better OCR.

    Args:
        img: PIL Image
        factor: Contrast factor (1.0 = no change, > 1.0 = more contrast)

    Returns:
        Contrast-enhanced image
    """
    if factor == 1.0:
        return img

    # Convert RGBA to RGB for enhancement
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(factor)


def preprocess_for_ocr(img: Image.Image, settings: PreprocessSettings) -> Image.Image:
    """
    Apply complete preprocessing pipeline for OCR optimization.

    Processing order (important!):
    0. Convert transparent background to white (Tesseract doesn't handle transparency)
    1. Color replacements (yellow -> white)
    2. Contrast enhancement
    3. Add margin
    4. Invert colors (if needed)
    5. Binarization
    6. Scaling

    Args:
        img: PIL Image (RGBA)
        settings: Preprocessing settings

    Returns:
        Preprocessed image ready for OCR
    """
    # Step 0: Convert transparent background to black
    # Tesseract doesn't handle RGBA well, needs solid background
    # Use BLACK background so white text with black outline is visible
    # (white on white would be invisible!)
    if img.mode == 'RGBA':
        # Create black background
        background = Image.new('RGB', img.size, (0, 0, 0))
        # Paste image on black background using alpha channel as mask
        background.paste(img, mask=img.split()[3])
        img = background

    # Step 1: Color replacements
    if settings.yellow_to_white:
        img = replace_yellow_with_white(img)

    # Step 2: Enhance contrast (before binarization)
    if settings.enhance_contrast > 1.0:
        img = enhance_contrast(img, settings.enhance_contrast)

    # Step 3: Add margin
    if settings.add_margin > 0:
        img = add_margin(img, settings.add_margin)

    # Step 4: Invert colors (if needed)
    if settings.invert_colors:
        img = invert_colors(img)

    # Step 5: Binarization (convert to black and white)
    if settings.binarize:
        img = binarize_image(img, settings.binarize_threshold)

    # Step 6: Scaling
    if settings.scale_percent != 100:
        img = scale_image(img, settings.scale_percent)

    return img
