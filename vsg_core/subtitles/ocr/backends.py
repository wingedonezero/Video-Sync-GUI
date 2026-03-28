# vsg_core/subtitles/ocr/backends.py
"""
OCR Engine Backends

Provides abstract interface and implementations for different OCR engines:
    - EasyOCR (deep learning, good for varied fonts)

This abstraction allows easy switching between engines for comparison.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OCRLineResult:
    """Result for a single OCR line."""

    text: str
    confidence: float  # 0-100 scale
    word_confidences: list[tuple[str, float]] = field(default_factory=list)
    backend: str = "unknown"
    y_center: float = 0.0  # Y center of this line within the source image (pixels)


@dataclass(slots=True)
class OCRResult:
    """Complete OCR result for a subtitle image."""

    text: str  # Full recognized text
    lines: list[OCRLineResult] = field(default_factory=list)
    average_confidence: float = 0.0
    min_confidence: float = 0.0
    low_confidence: bool = False
    error: str | None = None
    backend: str = "unknown"

    @property
    def success(self) -> bool:
        """Check if OCR was successful."""
        return self.error is None and len(self.text.strip()) > 0


class OCRBackend(ABC):
    """Abstract base class for OCR backends."""

    name: str = "base"

    def cleanup(self):
        """
        Release resources held by the backend.

        Override in subclasses that hold expensive resources (models, GPU memory).
        Called when the backend is no longer needed.
        """
        pass

    def __del__(self):
        """Destructor - ensure cleanup is called."""
        try:
            self.cleanup()
        except Exception:
            pass  # Don't raise in destructor

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
        self, image: np.ndarray, line_images: list[np.ndarray] | None = None
    ) -> OCRResult:
        """
        OCR each line separately for better accuracy.

        Note: Subclasses (like EasyOCR) may override this to use their own
        text detection instead of manual line splitting.

        Args:
            image: Full subtitle image
            line_images: Optional pre-split line images

        Returns:
            Combined OCRResult
        """
        if line_images is None:
            line_images = self._split_into_lines(image)

        if not line_images:
            logger.debug(f"[{self.name}] No line split, using full image OCR")
            return self.ocr_image(image)

        logger.debug(f"[{self.name}] Split image into {len(line_images)} lines")

        all_lines = []
        for i, line_img in enumerate(line_images):
            line_result = self.ocr_line(line_img)
            logger.debug(
                f"[{self.name}] Line {i + 1}: text='{line_result.text[:50] if line_result.text else ''}...', "
                f"conf={line_result.average_confidence:.1f}%, lines={len(line_result.lines)}"
            )
            all_lines.extend(line_result.lines)

        # Build combined result
        text = "\n".join(line.text for line in all_lines if line.text.strip())

        result = OCRResult(text=text, lines=all_lines, backend=self.name)

        if all_lines:
            confidences = [
                line.confidence for line in all_lines if line.confidence >= 0
            ]
            if confidences:
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = result.average_confidence < 60.0
                logger.debug(
                    f"[{self.name}] Combined: {len(all_lines)} lines, "
                    f"avg_conf={result.average_confidence:.1f}%, min={result.min_confidence:.1f}%"
                )

        return result

    def _split_into_lines(self, image: np.ndarray) -> list[np.ndarray]:
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
# EasyOCR Backend
# =============================================================================


class EasyOCRBackend(OCRBackend):
    """EasyOCR backend using deep learning."""

    name = "easyocr"

    def __init__(
        self,
        languages: list[str] | None = None,
        model_storage_directory: str | None = None,
    ):
        self.languages = languages or ["en"]
        self._reader = None
        # Use custom model directory if specified, otherwise use app's .config/ocr/easyocr_models
        if model_storage_directory:
            self.model_dir = model_storage_directory
        else:
            # Try to use the app's config directory
            from pathlib import Path

            app_dir = Path(
                __file__
            ).parent.parent.parent.parent  # vsg_core -> project root
            self.model_dir = str(app_dir / ".config" / "ocr" / "easyocr_models")
        logger.info(f"EasyOCRBackend created with languages: {self.languages}")
        logger.info(f"EasyOCR model directory: {self.model_dir}")

    @property
    def reader(self):
        """Lazy initialization of EasyOCR reader."""
        if self._reader is None:
            try:
                from pathlib import Path

                import easyocr

                # Auto-detect GPU (CUDA or ROCm)
                use_gpu = False
                gpu_info = "CPU"
                try:
                    import torch

                    if torch.cuda.is_available():
                        use_gpu = True
                        # Check if it's ROCm (AMD) or CUDA (NVIDIA)
                        if hasattr(torch.version, "hip") and torch.version.hip:
                            gpu_info = f"ROCm/HIP {torch.version.hip}"
                        else:
                            gpu_info = f"CUDA {torch.version.cuda}"
                except ImportError:
                    pass

                # Ensure model directory exists
                Path(self.model_dir).mkdir(parents=True, exist_ok=True)
                logger.info(
                    f"Initializing EasyOCR Reader with languages: {self.languages}"
                )
                logger.info(f"Model storage: {self.model_dir}")
                logger.info(f"GPU: {gpu_info} (enabled: {use_gpu})")
                logger.info("This may take a moment if models need to be downloaded...")
                self._reader = easyocr.Reader(
                    self.languages,
                    gpu=use_gpu,
                    model_storage_directory=self.model_dir,
                    verbose=True,
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
        """OCR full image with proper multi-line handling."""
        return self._do_ocr(image, single_line=False)

    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """OCR single line."""
        return self._do_ocr(image, single_line=True)

    def ocr_lines_separately(
        self, image: np.ndarray, line_images: list[np.ndarray] | None = None
    ) -> OCRResult:
        """
        Override base class to skip manual line splitting for EasyOCR.

        EasyOCR has its own CRAFT text detection that handles multi-line text
        better than manual horizontal projection splitting. Manual splitting
        can cut too close to text edges and cause first/last character loss.

        This approach matches VobSub-ML-OCR which passes full images to EasyOCR.
        """
        logger.debug(f"[{self.name}] Using native text detection (skipping line split)")
        # Use ocr_image which handles multi-line via bounding box grouping
        return self.ocr_image(image)

    def _do_ocr(self, image: np.ndarray, single_line: bool = False) -> OCRResult:
        """
        Perform OCR using EasyOCR.

        For multi-line subtitles, we need to:
        1. Get detections with bounding boxes (paragraph=False)
        2. Sort by Y position to get proper line order
        3. Group detections on the same line
        4. Join with newlines

        For single-line mode (when image is pre-split):
        - Just sort by X position and join all text as one line
        """
        result = OCRResult(text="", backend=self.name)

        try:
            # Always use paragraph=False to get bounding boxes for proper ordering
            # paragraph=True loses position info needed for multi-line subtitles
            detections = self.reader.readtext(image, paragraph=False)

            if not detections:
                return result

            # Each detection is (bbox, text, confidence)
            # bbox is 4 points: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]

            # Extract detections with position info
            detection_data = []
            for detection in detections:
                if len(detection) >= 3:
                    bbox, text, conf = detection[0], detection[1], detection[2]
                    # Calculate centers from bounding box
                    y_coords = [point[1] for point in bbox]
                    y_center = sum(y_coords) / len(y_coords)
                    x_coords = [point[0] for point in bbox]
                    x_center = sum(x_coords) / len(x_coords)
                    height = max(y_coords) - min(y_coords)

                    detection_data.append(
                        {
                            "text": text,
                            "conf": conf,
                            "y_center": y_center,
                            "x_center": x_center,
                            "height": height,
                        }
                    )

            if not detection_data:
                return result

            # Single-line mode: Image is pre-split, treat all detections as one line
            if single_line:
                # Sort by X position only (left to right)
                detection_data.sort(key=lambda d: d["x_center"])

                # Join all text as one line
                line_text = " ".join(d["text"] for d in detection_data)
                line_conf = (
                    sum(d["conf"] for d in detection_data) / len(detection_data) * 100.0
                )
                avg_y = sum(d["y_center"] for d in detection_data) / len(detection_data)

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[
                        (d["text"], d["conf"] * 100.0) for d in detection_data
                    ],
                    backend=self.name,
                    y_center=avg_y,
                )

                result.lines = [line]
                result.text = line_text
                result.average_confidence = line_conf
                result.min_confidence = min(d["conf"] * 100.0 for d in detection_data)
                result.low_confidence = result.average_confidence < 60.0

                return result

            # Multi-line mode: Group by Y position
            # Sort by Y position first (top to bottom)
            detection_data.sort(key=lambda d: d["y_center"])

            # Group detections into lines based on Y proximity
            line_groups = []
            current_group = [detection_data[0]]

            for det in detection_data[1:]:
                # Use the average height as threshold for same-line detection
                avg_height = sum(d["height"] for d in current_group) / len(
                    current_group
                )
                y_threshold = max(
                    avg_height * 0.5, 10
                )  # At least 10 pixels or half line height

                if abs(det["y_center"] - current_group[0]["y_center"]) < y_threshold:
                    # Same line - add to current group
                    current_group.append(det)
                else:
                    # New line - save current group and start new one
                    line_groups.append(current_group)
                    current_group = [det]

            # Don't forget the last group
            line_groups.append(current_group)

            # For each line group, sort by X position (left to right) and join
            lines = []
            for group in line_groups:
                # Sort by X position within the line
                group.sort(key=lambda d: d["x_center"])

                # Join text with spaces
                line_text = " ".join(d["text"] for d in group)

                # Calculate average confidence for the line
                line_conf = sum(d["conf"] for d in group) / len(group) * 100.0

                # Average Y center for all detections in this line group
                group_y = sum(d["y_center"] for d in group) / len(group)

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[(d["text"], d["conf"] * 100.0) for d in group],
                    backend=self.name,
                    y_center=group_y,
                )
                lines.append(line)

            result.lines = lines
            result.text = "\n".join(line.text for line in lines if line.text.strip())

            if lines:
                confidences = [l.confidence for l in lines]
                result.average_confidence = sum(confidences) / len(confidences)
                result.min_confidence = min(confidences)
                result.low_confidence = result.average_confidence < 60.0

        except Exception as e:
            result.error = str(e)
            logger.error(f"EasyOCR error: {e}")

        return result

    def cleanup(self):
        """Release EasyOCR reader and associated GPU memory."""
        if self._reader is not None:
            logger.info("Releasing EasyOCR reader and GPU memory")
            try:
                # Clear CUDA cache if using GPU
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Error clearing CUDA cache: {e}")
            self._reader = None



# =============================================================================
# Factory Functions
# =============================================================================

# Map of available backends
BACKENDS = {
    "easyocr": EasyOCRBackend,
}

# Language code mapping for different backends
LANGUAGE_MAP = {
    "easyocr": {
        "eng": ["en"],
        "jpn": ["ja"],
        "spa": ["es"],
        "fra": ["fr"],
        "deu": ["de"],
        "chi_sim": ["ch_sim"],
        "chi_tra": ["ch_tra"],
        "kor": ["ko"],
    },
}


def get_available_backends() -> list[str]:
    """Get list of available OCR backends."""
    available = []

    # Check EasyOCR
    try:
        import easyocr

        available.append("easyocr")
    except ImportError:
        pass

    return available


def create_backend(backend_name: str, language: str = "eng", **kwargs) -> OCRBackend:
    """
    Create an OCR backend instance.

    Args:
        backend_name: Name of backend ('easyocr')
        language: Language code (e.g., 'eng', 'jpn')
        **kwargs: Additional backend-specific arguments

    Returns:
        Configured OCRBackend instance
    """
    if backend_name not in BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend_name}. Available: {list(BACKENDS.keys())}"
        )

    backend_class = BACKENDS[backend_name]

    # Map language code to backend-specific format
    lang_map = LANGUAGE_MAP.get(backend_name, {})
    mapped_lang = lang_map.get(language, language)

    if backend_name == "easyocr":
        langs = mapped_lang if isinstance(mapped_lang, list) else [mapped_lang]
        return backend_class(languages=langs)

    return backend_class()


def create_ocr_engine_v2(settings_dict: dict) -> OCRBackend:
    """
    Create OCR engine using the backend system.

    Args:
        settings_dict: Application settings

    Returns:
        Configured OCRBackend instance
    """
    backend_name = settings_dict.get("ocr_engine", "easyocr")
    language = settings_dict.get("ocr_language", "eng")

    available = get_available_backends()
    if backend_name not in available:
        if available:
            logger.warning(
                f"OCR backend '{backend_name}' not available. "
                f"Falling back to '{available[0]}'"
            )
            backend_name = available[0]
        else:
            raise RuntimeError(
                "No OCR backends available. Install easyocr or paddleocr."
            )

    return create_backend(backend_name, language=language)
