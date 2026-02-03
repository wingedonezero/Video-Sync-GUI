# vsg_core/subtitles/ocr/preprocessing.py
"""
Adaptive Image Preprocessing for OCR

Prepares subtitle images for optimal Tesseract OCR accuracy.

Key preprocessing steps:
    1. Convert to grayscale
    2. Ensure black text on white background
    3. Upscale small images to ~300 DPI equivalent
    4. Add white border for better recognition
    5. Optional: Adaptive thresholding/binarization

The pipeline is adaptive - it analyzes image characteristics to determine
which preprocessing steps are beneficial for each specific image.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .parsers.base import SubtitleImage


@dataclass
class PreprocessingConfig:
    """Configuration for preprocessing pipeline."""

    # Auto-detect vs forced settings
    auto_detect: bool = True

    # Upscaling
    upscale_threshold_height: int = 40  # Upscale if height < this
    target_height: int = 80  # Target height after upscaling

    # Border
    border_size: int = 10  # White border in pixels
    border_color: tuple[int, int, int] = (255, 255, 255)  # White

    # Binarization - ALWAYS binarize for subtitle OCR
    # Pure black on white is optimal for Tesseract
    force_binarization: bool = True
    binarization_method: str = "otsu"  # 'otsu', 'adaptive', 'none'
    adaptive_block_size: int = 11
    adaptive_c: int = 2

    # Denoising
    denoise: bool = False
    denoise_strength: int = 3

    # Debug
    save_debug_images: bool = False
    debug_dir: Path | None = None


@dataclass
class PreprocessedImage:
    """Result of preprocessing a subtitle image."""

    image: np.ndarray  # Preprocessed image (grayscale or binary)
    original: np.ndarray  # Original image for reference
    subtitle_index: int
    was_inverted: bool = False
    was_upscaled: bool = False
    was_binarized: bool = False
    scale_factor: float = 1.0
    debug_path: Path | None = None


class ImagePreprocessor:
    """
    Adaptive preprocessing pipeline for subtitle images.

    Analyzes each image to determine optimal preprocessing steps.
    """

    def __init__(self, config: PreprocessingConfig | None = None):
        self.config = config or PreprocessingConfig()

    def preprocess(
        self, subtitle: SubtitleImage, work_dir: Path | None = None
    ) -> PreprocessedImage:
        """
        Preprocess a subtitle image for OCR.

        Args:
            subtitle: SubtitleImage with RGBA bitmap
            work_dir: Optional directory for debug images

        Returns:
            PreprocessedImage ready for OCR
        """
        result = PreprocessedImage(
            image=subtitle.image.copy(),
            original=subtitle.image.copy(),
            subtitle_index=subtitle.index,
        )

        # Step 1: Convert RGBA to grayscale, handling transparency
        gray = self._convert_to_grayscale(subtitle.image)

        # Step 2: Analyze image to determine if we need to invert
        should_invert = self._should_invert(gray)
        if should_invert:
            gray = 255 - gray
            result.was_inverted = True

        # Step 3: Upscale if image is too small
        if gray.shape[0] < self.config.upscale_threshold_height:
            gray, scale = self._upscale(gray)
            result.was_upscaled = True
            result.scale_factor = scale

        # Step 4: Apply binarization if configured or auto-detected as beneficial
        if self.config.force_binarization or self._should_binarize(gray):
            gray = self._binarize(gray)
            result.was_binarized = True

        # Step 5: Add white border
        gray = self._add_border(gray)

        # Step 6: Optional denoising
        if self.config.denoise:
            gray = self._denoise(gray)

        result.image = gray

        # Save debug image if configured
        if self.config.save_debug_images and work_dir:
            debug_path = self._save_debug(result, work_dir)
            result.debug_path = debug_path

        return result

    def preprocess_batch(
        self, subtitles: list[SubtitleImage], work_dir: Path | None = None
    ) -> list[PreprocessedImage]:
        """
        Preprocess multiple subtitle images.

        Args:
            subtitles: List of subtitle images
            work_dir: Optional directory for debug images

        Returns:
            List of preprocessed images
        """
        return [self.preprocess(sub, work_dir) for sub in subtitles]

    def _convert_to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """
        Convert RGBA image to grayscale, handling transparency.

        For VobSub subtitles with colored text (fill + outline), we:
        1. Composite the image onto a white background
        2. Convert to grayscale
        3. The colored text becomes dark on white background

        This approach works better than alpha-only because it preserves
        the full text shape including outlines.
        """
        if len(image.shape) == 2:
            # Already grayscale
            return image

        if image.shape[2] == 4:
            # RGBA - composite onto white background
            alpha = image[:, :, 3:4].astype(np.float32) / 255.0
            rgb = image[:, :, :3].astype(np.float32)

            # Composite: result = fg * alpha + bg * (1 - alpha)
            # White background = 255
            white_bg = np.ones_like(rgb) * 255.0
            composited = (rgb * alpha + white_bg * (1.0 - alpha)).astype(np.uint8)

            # Convert to grayscale
            gray = cv2.cvtColor(composited, cv2.COLOR_RGB2GRAY)

        elif image.shape[2] == 3:
            # RGB
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            # Unknown format, just take first channel
            gray = image[:, :, 0]

        return gray

    def _should_invert(self, gray: np.ndarray) -> bool:
        """
        Determine if image should be inverted (white text on black background).

        Tesseract works best with black text on white background.
        After compositing colored VobSub onto white, text should be dark.
        But some DVDs use inverted color schemes.
        """
        if not self.config.auto_detect:
            return False

        # Calculate average brightness of the image
        mean_brightness = np.mean(gray)

        # If image is mostly dark, text might be light (inverted scheme)
        # Normal case: white background (~200+) with dark text
        # Inverted case: dark background with light text
        return mean_brightness < 128

    def _should_binarize(self, gray: np.ndarray) -> bool:
        """
        Determine if binarization would help this image.

        Generally beneficial for:
            - Low contrast images
            - Images with anti-aliased edges
            - Noisy backgrounds
        """
        if not self.config.auto_detect:
            return False

        # Calculate image statistics
        std_dev = np.std(gray)

        # High standard deviation suggests good contrast, may not need binarization
        # Low standard deviation suggests flat image, binarization might help
        # Very low suggests almost uniform (likely already binary or problematic)
        if std_dev < 10:
            return False  # Already nearly uniform
        if std_dev > 80:
            return False  # Good contrast, Tesseract should handle it

        # Medium contrast - binarization might help
        return True

    def _upscale(self, gray: np.ndarray) -> tuple[np.ndarray, float]:
        """
        Upscale image to target height.

        Uses Lanczos interpolation for best quality.
        """
        current_height = gray.shape[0]
        if current_height >= self.config.target_height:
            return gray, 1.0

        scale = self.config.target_height / current_height
        new_width = int(gray.shape[1] * scale)
        new_height = self.config.target_height

        upscaled = cv2.resize(
            gray, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4
        )

        return upscaled, scale

    def _binarize(self, gray: np.ndarray) -> np.ndarray:
        """
        Apply binarization (thresholding) to image.

        Converts to pure black and white, which can help with
        anti-aliased edges and noise.
        """
        method = self.config.binarization_method

        if method == "otsu":
            # Otsu's automatic thresholding
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif method == "adaptive":
            # Adaptive thresholding (handles uneven lighting)
            binary = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                self.config.adaptive_block_size,
                self.config.adaptive_c,
            )
        else:
            # No binarization
            binary = gray

        return binary

    def _add_border(self, gray: np.ndarray) -> np.ndarray:
        """
        Add white border around image.

        Tesseract performs better when text isn't at the edge.
        """
        size = self.config.border_size
        if size <= 0:
            return gray

        bordered = cv2.copyMakeBorder(
            gray,
            top=size,
            bottom=size,
            left=size,
            right=size,
            borderType=cv2.BORDER_CONSTANT,
            value=255,  # White border
        )

        return bordered

    def _denoise(self, gray: np.ndarray) -> np.ndarray:
        """
        Apply denoising to reduce image noise.

        Uses median blur which preserves edges well.
        """
        strength = self.config.denoise_strength
        if strength <= 0:
            return gray

        # Median blur kernel must be odd
        kernel_size = strength * 2 + 1
        denoised = cv2.medianBlur(gray, kernel_size)

        return denoised

    def _save_debug(self, result: PreprocessedImage, work_dir: Path) -> Path:
        """
        Save debug images for inspection.

        Creates side-by-side comparison of original and preprocessed.
        """
        debug_dir = self.config.debug_dir or work_dir / "preprocessed"
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Save preprocessed image
        filename = f"sub_{result.subtitle_index:04d}_preprocessed.png"
        output_path = debug_dir / filename

        Image.fromarray(result.image).save(output_path)

        return output_path


def create_preprocessor(
    settings_dict: dict, work_dir: Path | None = None
) -> ImagePreprocessor:
    """
    Create preprocessor from settings dictionary.

    Args:
        settings_dict: Application settings
        work_dir: Working directory for debug output

    Returns:
        Configured ImagePreprocessor
    """
    # Check which OCR engine is being used
    ocr_engine = settings_dict.get("ocr_engine", "tesseract")

    # Deep learning OCR engines (EasyOCR, PaddleOCR) work better WITHOUT binarization
    # They're trained on natural images with anti-aliasing and grayscale gradients
    # Tesseract (traditional) works best WITH binarization (clean black on white)
    if ocr_engine in ("easyocr", "paddleocr"):
        # Skip binarization for deep learning engines
        force_binarization = False
        # Also use smaller border - deep learning handles edge text better
        border_size = settings_dict.get("ocr_border_size", 5)
    else:
        # Tesseract: use binarization
        force_binarization = settings_dict.get("ocr_force_binarization", True)
        border_size = settings_dict.get("ocr_border_size", 10)

    config = PreprocessingConfig(
        auto_detect=settings_dict.get("ocr_preprocess_auto", True),
        upscale_threshold_height=settings_dict.get("ocr_upscale_threshold", 40),
        target_height=settings_dict.get("ocr_target_height", 80),
        border_size=border_size,
        force_binarization=force_binarization,
        binarization_method=settings_dict.get("ocr_binarization_method", "otsu"),
        denoise=settings_dict.get("ocr_denoise", False),
        save_debug_images=settings_dict.get("ocr_save_debug_images", False),
        debug_dir=work_dir / "preprocessed" if work_dir else None,
    )

    return ImagePreprocessor(config)
