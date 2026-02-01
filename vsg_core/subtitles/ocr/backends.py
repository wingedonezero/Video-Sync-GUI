# vsg_core/subtitles/ocr/backends.py
"""
OCR Engine Backends

Provides abstract interface and implementations for different OCR engines:
    - Tesseract (traditional, fast, good for clean text)
    - EasyOCR (deep learning, better for varied fonts)
    - PaddleOCR (state-of-art, best accuracy) [future]

This abstraction allows easy switching between engines for comparison.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OCRLineResult:
    """Result for a single OCR line."""

    text: str
    confidence: float  # 0-100 scale
    word_confidences: list[tuple[str, float]] = field(default_factory=list)
    backend: str = "unknown"


@dataclass
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
# Tesseract Backend
# =============================================================================


class TesseractBackend(OCRBackend):
    """Tesseract OCR backend using pytesseract."""

    name = "tesseract"

    def __init__(self, language: str = "eng", char_blacklist: str = "|"):
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
        parts = [f"--psm {psm}", "--oem 3"]
        if self.char_blacklist:
            parts.append(f"-c tessedit_char_blacklist={self.char_blacklist}")
        parts.append("-c preserve_interword_spaces=1")
        return " ".join(parts)

    def ocr_image(self, image: np.ndarray) -> OCRResult:
        """OCR using block mode (PSM 6)."""
        return self._do_ocr(image, psm=6)

    def ocr_line(self, image: np.ndarray) -> OCRResult:
        """OCR using single line mode (PSM 7)."""
        return self._do_ocr(image, psm=7)

    def _do_ocr(self, image: np.ndarray, psm: int) -> OCRResult:
        """Perform OCR with specified PSM."""
        result = OCRResult(text="", backend=self.name)

        try:
            config = self._build_config(psm)
            data = self.pytesseract.image_to_data(
                image, lang=self.language, config=config, output_type=self.Output.DICT
            )

            # Process into lines
            lines = self._process_data(data)
            result.lines = lines
            result.text = "\n".join(line.text for line in lines if line.text.strip())

            if lines:
                confidences = [l.confidence for l in lines if l.confidence >= 0]
                if confidences:
                    result.average_confidence = sum(confidences) / len(confidences)
                    result.min_confidence = min(confidences)
                    result.low_confidence = result.average_confidence < 60.0

        except Exception as e:
            result.error = str(e)

        return result

    def _process_data(self, data: dict) -> list[OCRLineResult]:
        """Process Tesseract output into line results."""
        lines = []
        current_line = None
        current_line_num = -1

        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])
            line_num = data["line_num"][i]

            if not text:
                continue

            if line_num != current_line_num:
                if current_line is not None:
                    lines.append(current_line)
                current_line = OCRLineResult(text="", confidence=0.0, backend=self.name)
                current_line_num = line_num

            if current_line is not None:
                if current_line.text:
                    current_line.text += " "
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

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[
                        (d["text"], d["conf"] * 100.0) for d in detection_data
                    ],
                    backend=self.name,
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

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[(d["text"], d["conf"] * 100.0) for d in group],
                    backend=self.name,
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
# PaddleOCR Backend (Full Implementation)
# =============================================================================


class PaddleOCRBackend(OCRBackend):
    """
    PaddleOCR backend for OCR processing.

    PaddleOCR is a state-of-the-art OCR system from Baidu using PP-OCR models.
    Note: PaddleOCR only supports CUDA (NVIDIA) for GPU, not ROCm (AMD).
    """

    name = "paddleocr"

    def __init__(
        self,
        language: str = "en",
        model_storage_directory: str | None = None,
        drop_score: float = 0.5,
        force_cpu: bool = False,
    ):
        import os
        from pathlib import Path

        self.language = language
        self.drop_score = drop_score  # Min confidence threshold (0.0-1.0)
        self.force_cpu = force_cpu
        self._ocr = None
        # Use custom model directory if specified, otherwise use app's .config/ocr/paddleocr_models
        if model_storage_directory:
            self.model_dir = model_storage_directory
        else:
            app_dir = Path(
                __file__
            ).parent.parent.parent.parent  # vsg_core -> project root
            self.model_dir = str(app_dir / ".config" / "ocr" / "paddleocr_models")

        # PaddleOCR 3.0 uses PaddleX - set env vars BEFORE any paddleocr imports
        # These MUST be set at init time, not later when lazily loading
        Path(self.model_dir).mkdir(parents=True, exist_ok=True)
        os.environ["PADDLEX_HOME"] = self.model_dir
        os.environ["PADDLEOCR_HOME"] = self.model_dir

        logger.info(f"PaddleOCRBackend created with language: {self.language}")
        logger.info(f"PaddleOCR model directory: {self.model_dir}")

    @property
    def ocr(self):
        """Lazy initialization of PaddleOCR."""
        if self._ocr is None:
            try:
                # Environment variables already set in __init__
                from paddleocr import PaddleOCR

                # Detect GPU (PaddleOCR only supports CUDA, not ROCm)
                # PaddleOCR 3.0+ uses 'device' parameter instead of 'use_gpu'
                device = "cpu"
                gpu_info = "CPU"
                if self.force_cpu:
                    gpu_info = "CPU (forced)"
                else:
                    try:
                        import paddle

                        if paddle.device.is_compiled_with_cuda():
                            # Check if CUDA device is available
                            gpu_count = paddle.device.cuda.device_count()
                            if gpu_count > 0:
                                device = "gpu"
                                gpu_info = f"CUDA (PaddlePaddle, {gpu_count} device(s))"
                    except Exception:
                        pass

                logger.info(f"Initializing PaddleOCR with language: {self.language}")
                logger.info(f"Model storage: {self.model_dir}")
                logger.info(f"Device: {gpu_info}")
                logger.info("This may take a moment if models need to be downloaded...")

                self._ocr = PaddleOCR(
                    use_doc_orientation_classify=False,  # Don't try to fix document rotation
                    use_doc_unwarping=False,  # Don't try to unwarp document
                    use_textline_orientation=False,  # Don't rotate text (replaces use_angle_cls)
                    lang=self.language,
                    device=device,  # PaddleOCR 3.0+ API
                )
                logger.info("PaddleOCR initialized successfully")

            except ImportError:
                raise ImportError(
                    "paddleocr is not installed. Install with: pip install paddleocr paddlepaddle"
                )
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {e}")
                raise
        return self._ocr

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
        Override base class to skip manual line splitting for PaddleOCR.

        PaddleOCR has its own DB text detection that handles multi-line text
        better than manual horizontal projection splitting.
        """
        logger.debug(f"[{self.name}] Using native text detection (skipping line split)")
        return self.ocr_image(image)

    def _do_ocr(self, image: np.ndarray, single_line: bool = False) -> OCRResult:
        """
        Perform OCR using PaddleOCR.

        Uses the ocr.ocr() method which returns results in format:
        [[[box_coords], (text, confidence)], ...]

        For multi-line subtitles:
        1. Get all detections with bounding boxes
        2. Sort by Y position (top to bottom)
        3. Group detections on the same line
        4. Join with newlines
        """
        result = OCRResult(text="", backend=self.name)

        try:
            import cv2

            # PaddleOCR expects RGB images (3 channels)
            # Convert grayscale to RGB if needed
            if len(image.shape) == 2:
                # Grayscale image - convert to RGB
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            elif len(image.shape) == 3 and image.shape[2] == 1:
                # Single channel image - convert to RGB
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            elif len(image.shape) == 3 and image.shape[2] == 4:
                # RGBA - convert to RGB
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

            logger.debug(f"[{self.name}] Running OCR on image shape: {image.shape}")

            # PaddleOCR 3.x ocr.ocr() can return various formats depending on version
            ocr_result = self.ocr.ocr(image)

            if ocr_result is None:
                logger.debug(f"[{self.name}] ocr() returned None")
                return result

            # Log what we got for debugging
            logger.info(f"[{self.name}] ocr_result type: {type(ocr_result)}")

            # Collect all texts, scores, and polygons
            rec_texts = []
            rec_scores = []
            dt_polys = []

            try:
                # Convert to list if generator
                if hasattr(ocr_result, "__next__"):
                    ocr_result = list(ocr_result)

                logger.info(
                    f"[{self.name}] ocr_result length: {len(ocr_result) if ocr_result else 0}"
                )

                # Handle different result formats
                for idx, res_obj in enumerate(ocr_result):
                    if res_obj is None:
                        continue

                    logger.info(f"[{self.name}] Result {idx} type: {type(res_obj)}")

                    # Try to get data as dict
                    data = None

                    if hasattr(res_obj, "json"):
                        # PaddleOCR 3.x result object with .json property
                        data = res_obj.json
                        logger.info(f"[{self.name}] Got .json, type: {type(data)}")
                    elif isinstance(res_obj, dict):
                        data = res_obj
                    elif isinstance(res_obj, (list, tuple)):
                        # Could be old format: [[box, (text, conf)], ...]
                        # Or new format where each item is [box, (text, conf)]
                        if len(res_obj) > 0:
                            first = res_obj[0]
                            if isinstance(first, (list, tuple)) and len(first) >= 2:
                                # Check if it looks like [box, (text, conf)]
                                if (
                                    isinstance(first[1], (list, tuple))
                                    and len(first[1]) >= 2
                                ):
                                    # Old format items
                                    for item in res_obj:
                                        if item and len(item) >= 2:
                                            box, text_conf = item[0], item[1]
                                            if (
                                                isinstance(text_conf, (list, tuple))
                                                and len(text_conf) >= 2
                                            ):
                                                dt_polys.append(box)
                                                rec_texts.append(str(text_conf[0]))
                                                rec_scores.append(float(text_conf[1]))
                                    continue

                    if data is None:
                        logger.info(
                            f"[{self.name}] Could not extract data from result {idx}"
                        )
                        continue

                    # Navigate nested structure if present
                    if isinstance(data, dict):
                        if "res" in data and isinstance(data["res"], dict):
                            actual = data["res"]
                        else:
                            actual = data

                        logger.info(
                            f"[{self.name}] Data keys: {list(actual.keys()) if isinstance(actual, dict) else 'not a dict'}"
                        )

                        # Extract texts, scores, polygons - try various key names
                        texts = actual.get("rec_texts") or actual.get("rec_text") or []
                        scores = (
                            actual.get("rec_scores") or actual.get("rec_score") or []
                        )
                        polys = actual.get("dt_polys") or actual.get("rec_polys") or []

                        # Handle single values vs lists
                        if isinstance(texts, str):
                            texts = [texts]
                        if isinstance(scores, (int, float)):
                            scores = [scores]
                        if texts:
                            logger.info(
                                f"[{self.name}] Found {len(texts)} texts: {texts[:3]}..."
                            )

                        rec_texts.extend(texts if isinstance(texts, list) else [texts])
                        rec_scores.extend(
                            scores if isinstance(scores, list) else [scores]
                        )
                        dt_polys.extend(polys if isinstance(polys, list) else [polys])

            except Exception as e:
                logger.error(f"[{self.name}] Error iterating OCR results: {e}")
                import traceback

                logger.error(f"[{self.name}] Traceback: {traceback.format_exc()}")
                return result

            logger.info(
                f"[{self.name}] Total extracted: {len(rec_texts)} texts, {len(dt_polys)} polys"
            )

            if not rec_texts:
                logger.debug(f"[{self.name}] No text extracted")
                return result

            # Build detection data from extracted results
            detection_data = []
            for i, text in enumerate(rec_texts):
                if not text:
                    continue

                conf = rec_scores[i] if i < len(rec_scores) else 0.5

                # Get position from polygon
                x_center = 0
                y_center = i * 50
                height = 30

                if i < len(dt_polys) and dt_polys[i]:
                    try:
                        poly = dt_polys[i]
                        # Polygon format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                        if isinstance(poly[0], (list, tuple)):
                            xs = [p[0] for p in poly]
                            ys = [p[1] for p in poly]
                        else:
                            # Flat format
                            xs = [poly[j] for j in range(0, len(poly), 2)]
                            ys = [poly[j] for j in range(1, len(poly), 2)]
                        x_center = sum(xs) / len(xs)
                        y_center = sum(ys) / len(ys)
                        height = max(ys) - min(ys) if ys else 30
                    except (TypeError, IndexError, ValueError):
                        pass

                detection_data.append(
                    {
                        "text": text,
                        "conf": conf,
                        "y_center": y_center,
                        "x_center": x_center,
                        "height": height,
                    }
                )

            logger.debug(f"[{self.name}] Parsed {len(detection_data)} text regions")

            if not detection_data:
                return result

            # Single-line mode: treat all detections as one line
            if single_line:
                # Sort by X position only (left to right)
                detection_data.sort(key=lambda d: d["x_center"])

                # Join all text as one line
                line_text = " ".join(d["text"] for d in detection_data)
                line_conf = (
                    sum(d["conf"] for d in detection_data) / len(detection_data) * 100.0
                )

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[
                        (d["text"], d["conf"] * 100.0) for d in detection_data
                    ],
                    backend=self.name,
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

                line = OCRLineResult(
                    text=line_text,
                    confidence=line_conf,
                    word_confidences=[(d["text"], d["conf"] * 100.0) for d in group],
                    backend=self.name,
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
            import traceback

            result.error = str(e)
            logger.error(f"PaddleOCR error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

        return result

    def cleanup(self):
        """Release PaddleOCR engine and associated GPU memory."""
        if self._ocr is not None:
            logger.info("Releasing PaddleOCR engine and GPU memory")
            try:
                # Clear Paddle GPU memory if using GPU
                import paddle

                if paddle.device.is_compiled_with_cuda():
                    paddle.device.cuda.empty_cache()
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Error clearing Paddle CUDA cache: {e}")
            self._ocr = None


# =============================================================================
# Factory Functions
# =============================================================================

# Map of available backends
BACKENDS = {
    "tesseract": TesseractBackend,
    "easyocr": EasyOCRBackend,
    "paddleocr": PaddleOCRBackend,
}

# Language code mapping for different backends
LANGUAGE_MAP = {
    "tesseract": {
        "eng": "eng",
        "jpn": "jpn",
        "spa": "spa",
        "fra": "fra",
        "deu": "deu",
        "chi_sim": "chi_sim",
        "chi_tra": "chi_tra",
        "kor": "kor",
    },
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
    "paddleocr": {
        "eng": "en",
        "jpn": "japan",
        "spa": "es",
        "fra": "fr",
        "deu": "de",
        "chi_sim": "ch",
        "chi_tra": "ch",
        "kor": "korean",
    },
}


def get_available_backends() -> list[str]:
    """Get list of available OCR backends."""
    available = []

    # Check Tesseract
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        available.append("tesseract")
    except:
        pass

    # Check EasyOCR
    try:
        import easyocr

        available.append("easyocr")
    except ImportError:
        pass

    # Check PaddleOCR
    try:
        from paddleocr import PaddleOCR

        available.append("paddleocr")
    except ImportError:
        pass

    return available


def create_backend(backend_name: str, language: str = "eng", **kwargs) -> OCRBackend:
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
        raise ValueError(
            f"Unknown backend: {backend_name}. Available: {list(BACKENDS.keys())}"
        )

    backend_class = BACKENDS[backend_name]

    # Map language code to backend-specific format
    lang_map = LANGUAGE_MAP.get(backend_name, {})
    mapped_lang = lang_map.get(language, language)

    if backend_name == "tesseract":
        return backend_class(language=mapped_lang, **kwargs)
    elif backend_name == "easyocr":
        langs = mapped_lang if isinstance(mapped_lang, list) else [mapped_lang]
        return backend_class(languages=langs)
    elif backend_name == "paddleocr":
        # Pass through drop_score and force_cpu if provided
        return backend_class(
            language=mapped_lang,
            drop_score=kwargs.get("drop_score", 0.5),
            force_cpu=kwargs.get("force_cpu", False),
        )

    return backend_class()
