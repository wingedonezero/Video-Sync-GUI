# vsg_core/subtitles/ocr/backends.py
# -*- coding: utf-8 -*-
"""
OCR Engine Backends

Provides abstract interface and implementations for different OCR engines:
    - Tesseract (traditional, fast, good for clean text)
    - EasyOCR (deep learning, better for varied fonts)
    - PaddleOCR (state-of-art, best accuracy) [future]

This abstraction allows easy switching between engines for comparison.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class OCRLineResult:
    """Result for a single OCR line."""
    text: str
    confidence: float  # 0-100 scale
    word_confidences: List[Tuple[str, float]] = field(default_factory=list)
    backend: str = "unknown"


@dataclass
class OCRResult:
    """Complete OCR result for a subtitle image."""
    text: str  # Full recognized text
    lines: List[OCRLineResult] = field(default_factory=list)
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    low_confidence: bool = False
    error: Optional[str] = None
    backend: str = "unknown"

    @property
    def success(self) -> bool:
        """Check if OCR was successful."""
        return self.error is None and len(self.text.strip()) > 0


class OCRBackend(ABC):
    """Abstract base class for OCR backends."""

    name: str = "base"

    @abstractmethod
    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """
        Perform OCR on a preprocessed image.

        Args:
            image: Grayscale/binary image (preprocessed for OCR)

        Returns:
            OCRResult with recognized text and confidence
        """
        pass

    @abstractmethod
    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """
        OCR a single line image.

        Args:
            image: Single line image

        Returns:
            OCRResult for the line
        """
        pass

    def ocr_lines_separately(
        self,
        image: np.ndarray,
        line_images: Optional[List[np.ndarray]] = None
    ) -> OCRResult:
        """
        OCR each line separately for better accuracy.

        Args:
            image: Full subtitle image
            line_images: Optional pre-split line images

        Returns:
            Combined OCRResult
        """
        if line_images is None:
            line_images = self._split_into_lines(image)

        if not line_images:
            return self.ocr_image(image)

        all_lines = []
        for line_img in line_images:
            line_result = self.ocr_line(line_img)
            all_lines.extend(line_result.lines)

        # Build combined result
        text = '\n'.join(line.text for line in all_lines if line.text.strip())

        result = OCRResult(
            text=text,
            lines=all_lines,
            backend=self.name
        )

        if all_lines:
            confidences = [line.confidence for line in all_lines if line.confidence >= 0]
            if confidences:
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = result.average_confidence < 60.0

        return result

    def _split_into_lines(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Split a multi-line subtitle image into separate line images.
        Uses horizontal projection to find line boundaries.
        """
        import cv2

        # Ensure grayscale
        if len(image.shape) > 2:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        # Invert if needed (want text as white for projection)
        if np.mean(gray) > 128:
            gray = 255 - gray

        # Calculate horizontal projection
        projection = np.sum(gray, axis=1)

        # Find line boundaries
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

        if in_text:
            line_ends.append(len(projection) - 1)

        # Extract line images
        lines = []
        padding = 5
        min_line_height = 10

        for start, end in zip(line_starts, line_ends):
            if end - start >= min_line_height:
                y1 = max(0, start - padding)
                y2 = min(image.shape[0], end + padding)
                lines.append(image[y1:y2, :])

        return lines


# =============================================================================
# Tesseract Backend
# =============================================================================

class TesseractBackend(OCRBackend):
    """Tesseract OCR backend using pytesseract."""

    name = "tesseract"

    def __init__(self, language: str = 'eng', char_blacklist: str = '|'):
        try:
            import pytesseract
            self.pytesseract = pytesseract
            self.Output = pytesseract.Output
        except ImportError:
            raise ImportError(
                "pytesseract is not installed. Install with: pip install pytesseract"
            )

        self.language = language
        self.char_blacklist = char_blacklist
        self._verify_tesseract()

    def _verify_tesseract(self):
        """Verify Tesseract is installed."""
        try:
            self.pytesseract.get_tesseract_version()
        except Exception as e:
            raise RuntimeError(f"Tesseract not found: {e}")

    def _build_config(self, psm: int = 6) -> str:
        """Build Tesseract config string."""
        parts = [f'--psm {psm}', '--oem 3']
        if self.char_blacklist:
            parts.append(f'-c tessedit_char_blacklist={self.char_blacklist}')
        parts.append('-c preserve_interword_spaces=1')
        return ' '.join(parts)

    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """OCR using block mode (PSM 6)."""
        return self._do_ocr(image, psm=6)

    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """OCR using single line mode (PSM 7)."""
        return self._do_ocr(image, psm=7)

    def _do_ocr(self, image: np.ndarray, psm: int) -> OCRResult:
        """Perform OCR with specified PSM."""
        result = OCRResult(text='', backend=self.name)

        try:
            config = self._build_config(psm)
            data = self.pytesseract.image_to_data(
                image,
                lang=self.language,
                config=config,
                output_type=self.Output.DICT
            )

            # Process into lines
            lines = self._process_data(data)
            result.lines = lines
            result.text = '\n'.join(line.text for line in lines if line.text.strip())

            if lines:
                confidences = [l.confidence for l in lines if l.confidence >= 0]
                if confidences:
                    result.average_confidence = sum(confidences) / len(confidences)
                    result.min_confidence = min(confidences)
                    result.low_confidence = result.average_confidence < 60.0

        except Exception as e:
            result.error = str(e)

        return result

    def _process_data(self, data: dict) -> List[OCRLineResult]:
        """Process Tesseract output into line results."""
        lines = []
        current_line = None
        current_line_num = -1

        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            conf = float(data['conf'][i])
            line_num = data['line_num'][i]

            if not text:
                continue

            if line_num != current_line_num:
                if current_line is not None:
                    lines.append(current_line)
                current_line = OCRLineResult(text='', confidence=0.0, backend=self.name)
                current_line_num = line_num

            if current_line is not None:
                if current_line.text:
                    current_line.text += ' '
                current_line.text += text
                if conf >= 0:
                    current_line.word_confidences.append((text, conf))

        if current_line is not None and current_line.text:
            lines.append(current_line)

        # Calculate line confidences
        for line in lines:
            if line.word_confidences:
                valid = [c for _, c in line.word_confidences if c >= 0]
                if valid:
                    line.confidence = sum(valid) / len(valid)

        return lines


# =============================================================================
# EasyOCR Backend
# =============================================================================

class EasyOCRBackend(OCRBackend):
    """EasyOCR backend using deep learning."""

    name = "easyocr"

    def __init__(self, languages: List[str] = None, model_storage_directory: str = None):
        self.languages = languages or ['en']
        self._reader = None
        # Use custom model directory if specified, otherwise use app's .config/ocr/easyocr_models
        if model_storage_directory:
            self.model_dir = model_storage_directory
        else:
            # Try to use the app's config directory
            from pathlib import Path
            app_dir = Path(__file__).parent.parent.parent.parent  # vsg_core -> project root
            self.model_dir = str(app_dir / '.config' / 'ocr' / 'easyocr_models')
        logger.info(f"EasyOCRBackend created with languages: {self.languages}")
        logger.info(f"EasyOCR model directory: {self.model_dir}")

    @property
    def reader(self):
        """Lazy initialization of EasyOCR reader."""
        if self._reader is None:
            try:
                import easyocr
                from pathlib import Path
                # Ensure model directory exists
                Path(self.model_dir).mkdir(parents=True, exist_ok=True)
                logger.info(f"Initializing EasyOCR Reader with languages: {self.languages}")
                logger.info(f"Model storage: {self.model_dir}")
                logger.info("This may take a moment if models need to be downloaded...")
                self._reader = easyocr.Reader(
                    self.languages,
                    gpu=False,
                    model_storage_directory=self.model_dir,
                    verbose=True
                )
                logger.info("EasyOCR Reader initialized successfully")
            except ImportError:
                raise ImportError(
                    "easyocr is not installed. Install with: pip install easyocr"
                )
            except Exception as e:
                logger.error(f"Failed to initialize EasyOCR: {e}")
                raise
        return self._reader

    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """OCR full image."""
        return self._do_ocr(image, paragraph=True)

    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """OCR single line."""
        return self._do_ocr(image, paragraph=False)

    def _do_ocr(self, image: np.ndarray, paragraph: bool = True) -> OCRResult:
        """Perform OCR using EasyOCR."""
        result = OCRResult(text='', backend=self.name)

        try:
            # EasyOCR returns list of (bbox, text, confidence)
            detections = self.reader.readtext(image, paragraph=paragraph)

            if not detections:
                return result

            lines = []
            for detection in detections:
                if len(detection) >= 3:
                    bbox, text, conf = detection[0], detection[1], detection[2]
                elif len(detection) == 2:
                    text, conf = detection[0], detection[1]
                else:
                    continue

                # EasyOCR confidence is 0-1, convert to 0-100
                confidence = conf * 100.0

                line = OCRLineResult(
                    text=text,
                    confidence=confidence,
                    word_confidences=[(text, confidence)],
                    backend=self.name
                )
                lines.append(line)

            result.lines = lines
            result.text = '\n'.join(line.text for line in lines if line.text.strip())

            if lines:
                confidences = [l.confidence for l in lines]
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = result.average_confidence < 60.0

        except Exception as e:
            result.error = str(e)
            logger.error(f"EasyOCR error: {e}")

        return result


# =============================================================================
# PaddleOCR Backend (placeholder for future)
# =============================================================================

class PaddleOCRBackend(OCRBackend):
    """PaddleOCR backend - placeholder for future implementation."""

    name = "paddleocr"

    def __init__(self, language: str = 'en'):
        self.language = language
        self._ocr = None

    @property
    def ocr(self):
        """Lazy initialization of PaddleOCR."""
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                logger.info(f"Initializing PaddleOCR with language: {self.language}")
                self._ocr = PaddleOCR(use_angle_cls=False, lang=self.language, show_log=False)
            except ImportError:
                raise ImportError(
                    "paddleocr is not installed. Install with: pip install paddleocr"
                )
        return self._ocr

    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """OCR full image."""
        return self._do_ocr(image)

    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """OCR single line."""
        return self._do_ocr(image)

    def _do_ocr(self, image: np.ndarray) -> OCRResult:
        """Perform OCR using PaddleOCR."""
        result = OCRResult(text='', backend=self.name)

        try:
            detections = self.ocr.ocr(image, cls=False)

            if not detections or not detections[0]:
                return result

            lines = []
            for detection in detections[0]:
                # PaddleOCR returns [bbox, (text, confidence)]
                if detection and len(detection) >= 2:
                    text_conf = detection[1]
                    text = text_conf[0]
                    conf = text_conf[1] * 100.0  # Convert to 0-100

                    line = OCRLineResult(
                        text=text,
                        confidence=conf,
                        word_confidences=[(text, conf)],
                        backend=self.name
                    )
                    lines.append(line)

            result.lines = lines
            result.text = '\n'.join(line.text for line in lines if line.text.strip())

            if lines:
                confidences = [l.confidence for l in lines]
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = result.average_confidence < 60.0

        except Exception as e:
            result.error = str(e)
            logger.error(f"PaddleOCR error: {e}")

        return result


# =============================================================================
# Factory Functions
# =============================================================================

# Map of available backends
BACKENDS = {
    'tesseract': TesseractBackend,
    'easyocr': EasyOCRBackend,
    'paddleocr': PaddleOCRBackend,
}

# Language code mapping for different backends
LANGUAGE_MAP = {
    'tesseract': {
        'eng': 'eng', 'jpn': 'jpn', 'spa': 'spa', 'fra': 'fra',
        'deu': 'deu', 'chi_sim': 'chi_sim', 'chi_tra': 'chi_tra', 'kor': 'kor'
    },
    'easyocr': {
        'eng': ['en'], 'jpn': ['ja'], 'spa': ['es'], 'fra': ['fr'],
        'deu': ['de'], 'chi_sim': ['ch_sim'], 'chi_tra': ['ch_tra'], 'kor': ['ko']
    },
    'paddleocr': {
        'eng': 'en', 'jpn': 'japan', 'spa': 'es', 'fra': 'fr',
        'deu': 'de', 'chi_sim': 'ch', 'chi_tra': 'ch', 'kor': 'korean'
    }
}


def get_available_backends() -> List[str]:
    """Get list of available OCR backends."""
    available = []

    # Check Tesseract
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        available.append('tesseract')
    except:
        pass

    # Check EasyOCR
    try:
        import easyocr
        available.append('easyocr')
    except ImportError:
        pass

    # Check PaddleOCR
    try:
        from paddleocr import PaddleOCR
        available.append('paddleocr')
    except ImportError:
        pass

    return available


def create_backend(
    backend_name: str,
    language: str = 'eng',
    **kwargs
) -> OCRBackend:
    """
    Create an OCR backend instance.

    Args:
        backend_name: Name of backend ('tesseract', 'easyocr', 'paddleocr')
        language: Tesseract-style language code (e.g., 'eng', 'jpn')
        **kwargs: Additional backend-specific arguments

    Returns:
        Configured OCRBackend instance
    """
    if backend_name not in BACKENDS:
        raise ValueError(f"Unknown backend: {backend_name}. Available: {list(BACKENDS.keys())}")

    backend_class = BACKENDS[backend_name]

    # Map language code to backend-specific format
    lang_map = LANGUAGE_MAP.get(backend_name, {})
    mapped_lang = lang_map.get(language, language)

    if backend_name == 'tesseract':
        return backend_class(language=mapped_lang, **kwargs)
    elif backend_name == 'easyocr':
        langs = mapped_lang if isinstance(mapped_lang, list) else [mapped_lang]
        return backend_class(languages=langs)
    elif backend_name == 'paddleocr':
        return backend_class(language=mapped_lang)

    return backend_class()
