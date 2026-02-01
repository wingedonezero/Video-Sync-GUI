# vsg_core/subtitles/ocr/engine.py
"""
Tesseract OCR Engine Wrapper

Provides OCR functionality with:
    - Confidence score tracking per line
    - Multiple PSM (Page Segmentation Mode) support
    - Character whitelist/blacklist configuration
    - Line-by-line OCR for better accuracy

Uses pytesseract as the interface to Tesseract 5.x
"""

from dataclasses import dataclass, field

import numpy as np

try:
    import pytesseract
    from pytesseract import Output

    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False


@dataclass
class OCRConfig:
    """Configuration for OCR engine."""

    language: str = "eng"
    psm: int = 6  # Block mode - works better for DVD subtitles than line mode
    oem: int = 3  # Default - use LSTM if available
    char_whitelist: str = ""  # Characters to allow (empty = all)
    char_blacklist: str = "|"  # Exclude pipe which is often misread

    # Confidence thresholds
    min_confidence: float = 0.0  # Minimum confidence to accept (0-100)
    low_confidence_threshold: float = 60.0  # Flag if below this

    # Multi-pass settings
    enable_multi_pass: bool = True  # Retry with different settings if low confidence
    fallback_psm: int = 4  # PSM to use on retry (single column)


@dataclass
class OCRLineResult:
    """Result for a single OCR line."""

    text: str
    confidence: float  # 0-100 scale
    word_confidences: list[tuple[str, float]] = field(default_factory=list)
    psm_used: int = 7
    was_retry: bool = False


@dataclass
class OCRResult:
    """Complete OCR result for a subtitle image."""

    text: str  # Full recognized text
    lines: list[OCRLineResult] = field(default_factory=list)
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    low_confidence: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if OCR was successful."""
        return self.error is None and len(self.text.strip()) > 0


class OCREngine:
    """
    Tesseract OCR engine with confidence tracking.

    Provides line-by-line OCR with detailed confidence information.
    """

    def __init__(self, config: OCRConfig | None = None):
        if not PYTESSERACT_AVAILABLE:
            raise ImportError(
                "pytesseract is not installed. Install with: pip install pytesseract"
            )

        self.config = config or OCRConfig()
        self._verify_tesseract()

    def _verify_tesseract(self):
        """Verify Tesseract is installed and accessible."""
        try:
            version = pytesseract.get_tesseract_version()
            self.tesseract_version = str(version)
        except Exception as e:
            raise RuntimeError(
                f"Tesseract not found or not accessible: {e}\n"
                "Install Tesseract: apt install tesseract-ocr tesseract-ocr-eng"
            )

    def _build_config(self, psm: int | None = None) -> str:
        """
        Build Tesseract configuration string.

        Args:
            psm: Override PSM mode (uses config default if None)

        Returns:
            Tesseract config string
        """
        config_parts = []

        # Page segmentation mode
        mode = psm if psm is not None else self.config.psm
        config_parts.append(f"--psm {mode}")

        # OCR Engine mode
        config_parts.append(f"--oem {self.config.oem}")

        # Character restrictions
        if self.config.char_whitelist:
            config_parts.append(
                f"-c tessedit_char_whitelist={self.config.char_whitelist}"
            )
        if self.config.char_blacklist:
            config_parts.append(
                f"-c tessedit_char_blacklist={self.config.char_blacklist}"
            )

        # Additional Tesseract settings for subtitle OCR
        # These help with the outlined/anti-aliased fonts common in DVD subtitles
        config_parts.append("-c preserve_interword_spaces=1")

        return " ".join(config_parts)

    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """
        Perform OCR on a preprocessed image.

        Args:
            image: Grayscale/binary image (preprocessed for OCR)

        Returns:
            OCRResult with recognized text and confidence
        """
        result = OCRResult(text="")

        try:
            # Get detailed OCR data with confidence
            config = self._build_config()
            data = pytesseract.image_to_data(
                image, lang=self.config.language, config=config, output_type=Output.DICT
            )

            # Process results
            lines = self._process_ocr_data(data, self.config.psm)
            result.lines = lines

            # Build full text
            result.text = self._build_text_from_lines(lines)

            # Calculate confidence stats
            if lines:
                confidences = [
                    line.confidence for line in lines if line.confidence >= 0
                ]
                if confidences:
                    result.average_confidence = sum(confidences) / len(confidences)
                    result.min_confidence = min(confidences)
                    result.low_confidence = (
                        result.average_confidence < self.config.low_confidence_threshold
                    )

            # Multi-pass retry if configured and confidence is low
            if (
                self.config.enable_multi_pass
                and result.low_confidence
                and self.config.fallback_psm != self.config.psm
            ):
                retry_result = self._retry_with_fallback(image)
                if retry_result.average_confidence > result.average_confidence:
                    result = retry_result

        except Exception as e:
            result.error = str(e)

        return result

    def _process_ocr_data(self, data: dict, psm_used: int) -> list[OCRLineResult]:
        """
        Process Tesseract output data into structured results.

        Tesseract returns data at word level with block/line/word hierarchy.
        """
        lines: list[OCRLineResult] = []
        current_line: OCRLineResult | None = None
        current_line_num = -1

        n_boxes = len(data["text"])

        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])
            line_num = data["line_num"][i]

            # Skip empty entries
            if not text:
                continue

            # Start new line if line number changed
            if line_num != current_line_num:
                if current_line is not None:
                    lines.append(current_line)
                current_line = OCRLineResult(
                    text="", confidence=0.0, word_confidences=[], psm_used=psm_used
                )
                current_line_num = line_num

            # Add word to current line
            if current_line is not None:
                if current_line.text:
                    current_line.text += " "
                current_line.text += text
                if conf >= 0:  # -1 means no confidence available
                    current_line.word_confidences.append((text, conf))

        # Don't forget the last line
        if current_line is not None and current_line.text:
            lines.append(current_line)

        # Calculate line-level confidence from word confidences
        for line in lines:
            if line.word_confidences:
                valid_confs = [c for _, c in line.word_confidences if c >= 0]
                if valid_confs:
                    line.confidence = sum(valid_confs) / len(valid_confs)

        return lines

    def _build_text_from_lines(self, lines: list[OCRLineResult]) -> str:
        """Build full text from line results."""
        return "\n".join(line.text for line in lines if line.text.strip())

    def _retry_with_fallback(self, image: np.ndarray) -> OCRResult:
        """
        Retry OCR with fallback PSM mode.

        Used when initial OCR has low confidence.
        """
        result = OCRResult(text="")

        try:
            config = self._build_config(psm=self.config.fallback_psm)
            data = pytesseract.image_to_data(
                image, lang=self.config.language, config=config, output_type=Output.DICT
            )

            lines = self._process_ocr_data(data, self.config.fallback_psm)

            # Mark as retry
            for line in lines:
                line.was_retry = True

            result.lines = lines
            result.text = self._build_text_from_lines(lines)

            if lines:
                confidences = [
                    line.confidence for line in lines if line.confidence >= 0
                ]
                if confidences:
                    result.average_confidence = sum(confidences) / len(confidences)
                    result.min_confidence = min(confidences)
                    result.low_confidence = (
                        result.average_confidence < self.config.low_confidence_threshold
                    )

        except Exception as e:
            result.error = str(e)

        return result

    def ocr_lines_separately(
        self, image: np.ndarray, line_images: list[np.ndarray] | None = None
    ) -> OCRResult:
        """
        OCR each line separately for better accuracy.

        Uses PSM 7 (single line mode) for each line, which greatly improves
        accuracy especially for non-English text. This is the approach used
        by subtile-ocr/vobsubocr.

        If line_images are provided, OCR each one individually.
        Otherwise, attempt to split the image into lines and OCR each.

        Args:
            image: Full subtitle image
            line_images: Optional pre-split line images

        Returns:
            Combined OCRResult
        """
        if line_images is None:
            # Try to split image into lines
            line_images = self._split_into_lines(image)

        if not line_images:
            # Couldn't split, fall back to full image OCR
            return self.ocr_image(image)

        all_lines = []
        for i, line_img in enumerate(line_images):
            # Use PSM 7 (single line) for individual lines - much better accuracy
            line_result = self._ocr_single_line(line_img)
            all_lines.extend(line_result.lines)

        result = OCRResult(
            text=self._build_text_from_lines(all_lines),
            lines=all_lines,
        )

        if all_lines:
            confidences = [
                line.confidence for line in all_lines if line.confidence >= 0
            ]
            if confidences:
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = (
                    result.average_confidence < self.config.low_confidence_threshold
                )

        return result

    def _ocr_single_line(self, image: np.ndarray) -> OCRResult:
        """
        OCR a single line image using PSM 7 (single text line).

        PSM 7 is optimized for single lines and gives much better results
        than block modes for subtitle lines.
        """
        result = OCRResult(text="")

        try:
            # Use PSM 7 specifically for single lines
            config = self._build_config(psm=7)
            data = pytesseract.image_to_data(
                image, lang=self.config.language, config=config, output_type=Output.DICT
            )

            lines = self._process_ocr_data(data, 7)
            result.lines = lines
            result.text = self._build_text_from_lines(lines)

            if lines:
                confidences = [
                    line.confidence for line in lines if line.confidence >= 0
                ]
                if confidences:
                    result.average_confidence = sum(confidences) / len(confidences)
                    result.min_confidence = min(confidences)

        except Exception as e:
            result.error = str(e)

        return result

    def _split_into_lines(self, image: np.ndarray) -> list[np.ndarray]:
        """
        Split a multi-line subtitle image into separate line images.

        Uses horizontal projection to find line boundaries.

        Returns:
            List of line images, or empty list if splitting fails
        """
        import cv2

        # Ensure binary image for projection
        if len(image.shape) > 2:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        # Invert if needed (want text as white for projection)
        if np.mean(gray) > 128:
            gray = 255 - gray

        # Calculate horizontal projection (sum pixels per row)
        projection = np.sum(gray, axis=1)

        # Find line boundaries (rows with low projection values)
        # Use higher threshold (20%) to filter out noise
        threshold = np.max(projection) * 0.2
        in_text = False
        line_starts = []
        line_ends = []

        for i, val in enumerate(projection):
            if val > threshold and not in_text:
                line_starts.append(i)
                in_text = True
            elif val <= threshold and in_text:
                line_ends.append(i)
                in_text = False

        # Handle case where image ends in text
        if in_text:
            line_ends.append(len(projection) - 1)

        # Extract line images with minimum height filter
        lines = []
        padding = 5  # Add some padding around each line
        min_line_height = 10  # Minimum height for valid text line (filters noise)

        for start, end in zip(line_starts, line_ends):
            line_height = end - start
            if line_height >= min_line_height:
                y1 = max(0, start - padding)
                y2 = min(image.shape[0], end + padding)
                line_img = image[y1:y2, :]
                lines.append(line_img)

        return lines


def get_available_languages() -> list[str]:
    """
    Get list of available Tesseract languages.

    Returns:
        List of language codes (e.g., ['eng', 'jpn', 'osd'])
    """
    if not PYTESSERACT_AVAILABLE:
        return []

    try:
        langs = pytesseract.get_languages()
        return langs
    except Exception:
        return ["eng"]  # Assume at least English is available


def create_ocr_engine(settings_dict: dict) -> OCREngine:
    """
    Create OCR engine from settings dictionary.

    Args:
        settings_dict: Application settings

    Returns:
        Configured OCREngine
    """
    # Get configured language or auto-detect
    language = settings_dict.get("ocr_language", "eng")

    # If language is 'auto', try to use eng+jpn for anime subtitles
    if language == "auto":
        available = get_available_languages()
        if "jpn" in available and "eng" in available:
            language = "eng+jpn"
        elif "eng" in available:
            language = "eng"
        else:
            language = available[0] if available else "eng"

    config = OCRConfig(
        language=language,
        psm=settings_dict.get("ocr_psm", 7),
        char_whitelist=settings_dict.get("ocr_char_whitelist", ""),
        char_blacklist=settings_dict.get("ocr_char_blacklist", "|"),
        low_confidence_threshold=settings_dict.get(
            "ocr_low_confidence_threshold", 60.0
        ),
        enable_multi_pass=settings_dict.get("ocr_multi_pass", True),
    )

    return OCREngine(config)


# =============================================================================
# New Backend-based Engine Factory
# =============================================================================


def create_ocr_engine_v2(settings_dict: dict):
    """
    Create OCR engine using the new backend system.

    Supports multiple OCR backends: tesseract, easyocr, paddleocr

    Args:
        settings_dict: Application settings

    Returns:
        Configured OCRBackend instance
    """
    from .backends import create_backend, get_available_backends

    # Get backend preference
    backend_name = settings_dict.get("ocr_engine", "tesseract")
    language = settings_dict.get("ocr_language", "eng")

    # Check if requested backend is available
    available = get_available_backends()
    if backend_name not in available:
        # Fall back to first available
        if available:
            import logging

            logging.getLogger(__name__).warning(
                f"OCR backend '{backend_name}' not available. "
                f"Falling back to '{available[0]}'"
            )
            backend_name = available[0]
        else:
            raise RuntimeError(
                "No OCR backends available. Install pytesseract or easyocr."
            )

    # Create backend with language
    char_blacklist = settings_dict.get("ocr_char_blacklist", "|")

    if backend_name == "tesseract":
        return create_backend(
            backend_name, language=language, char_blacklist=char_blacklist
        )
    else:
        return create_backend(backend_name, language=language)
