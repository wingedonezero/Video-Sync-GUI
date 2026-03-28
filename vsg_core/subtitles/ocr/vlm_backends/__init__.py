# vsg_core/subtitles/ocr/vlm_backends/__init__.py
"""
VLM-based OCR backends for subtitle text recognition.

Each backend implements load/ocr/unload for explicit GPU lifecycle.
Two approaches are supported:
- Annotated: Full frame image with numbered region boxes (Qwen family)
- Crop: Individual region crops sent to model (LFM2, LightOnOCR, Florence)

Usage:
    from vsg_core.subtitles.ocr.vlm_backends import get_vlm_backend, is_model_available

    if is_model_available("lfm2vl-450m"):
        backend = get_vlm_backend("lfm2vl-450m")
        backend.load()
        results = backend.ocr(image, regions)
        backend.unload()
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..region_detector import Region

logger = logging.getLogger(__name__)

# Project root for model storage
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
_MODELS_DIR = _PROJECT_DIR / "models" / "ocr"


@dataclass
class VLMRegionResult:
    """OCR result for a single region."""

    region_id: int
    text: str
    raw_output: str = ""
    vl_bbox: tuple[int, int, int, int] | None = None  # VL-detected bbox (x1,y1,x2,y2)


@dataclass
class VLMResult:
    """OCR result for one subtitle image."""

    index: int
    regions: list[VLMRegionResult] = field(default_factory=list)
    ocr_ms: float = 0.0
    model_name: str = ""
    raw_model_output: str = ""

    @property
    def full_text(self) -> str:
        """All region texts joined by newline."""
        return "\n".join(r.text for r in self.regions if r.text)


class VLMBackend(ABC):
    """
    Base class for VLM OCR backends.

    Unlike traditional OCR backends (EasyOCR/PaddleOCR) that work on
    preprocessed grayscale line images, VLM backends work on raw RGBA
    images with detected regions.
    """

    name: str = "base"

    # Whether this backend uses annotated images (numbered boxes) or crops
    uses_annotated: bool = True

    @abstractmethod
    def load(self) -> None:
        """
        Load model to GPU.

        Must use CPU-first loading to avoid VRAM spikes:
            model = Model.from_pretrained(..., device_map="cpu")
            model = model.to("cuda")
        """

    @abstractmethod
    def ocr(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        """
        Run OCR on an image with known regions.

        For annotated backends (uses_annotated=True):
            image = annotated RGB image with numbered boxes
            regions = detected regions for mapping results

        For crop backends (uses_annotated=False):
            image = annotated image (unused)
            regions = regions to crop from raw_image
            raw_image = original RGB image for cropping
        """

    @abstractmethod
    def unload(self) -> None:
        """Free GPU memory."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"


# ── Backend Registry ──────────────────────────────────────────────────────

_BACKENDS: dict[str, type[VLMBackend]] = {}


def register_vlm_backend(name: str):
    """Decorator to register a VLM backend class."""

    def decorator(cls: type[VLMBackend]) -> type[VLMBackend]:
        _BACKENDS[name] = cls
        cls.name = name
        return cls

    return decorator


def get_vlm_backend(name: str, **kwargs) -> VLMBackend:
    """Get a VLM backend instance by name."""
    if name not in _BACKENDS:
        available = ", ".join(_BACKENDS.keys())
        raise ValueError(f"Unknown VLM backend '{name}'. Available: {available}")
    return _BACKENDS[name](**kwargs)


def list_vlm_backends() -> list[str]:
    """List all registered VLM backend names."""
    return list(_BACKENDS.keys())


# ── Model Management ──────────────────────────────────────────────────────

# Maps backend name -> HuggingFace repo ID and local directory name
_MODEL_REGISTRY: dict[str, dict] = {
    "lfm2vl-450m": {
        "repo_id": "LiquidAI/LFM2-VL-450M",
        "dir_name": "LFM2-VL-450M",
    },
    "qwen35-4b": {
        "repo_id": "Qwen/Qwen3.5-4B",
        "dir_name": "Qwen3.5-4B",
    },
    "paddleocr-vl": {
        "repo_id": "PaddlePaddle/PaddleOCR-VL-1.5-GGUF",
        "dir_name": "PaddleOCR-VL-1.5-GGUF",
        "check_file": "PaddleOCR-VL-1.5.gguf",
    },
}


def get_model_dir(name: str) -> Path:
    """Get the local model directory for a backend."""
    if name in _MODEL_REGISTRY:
        return _MODELS_DIR / _MODEL_REGISTRY[name]["dir_name"]
    return _MODELS_DIR / name


def is_model_available(name: str) -> bool:
    """Check if a model is downloaded and ready to use."""
    model_dir = get_model_dir(name)
    if not model_dir.exists():
        return False
    # GGUF models use a specific file instead of config.json
    if name in _MODEL_REGISTRY and "check_file" in _MODEL_REGISTRY[name]:
        return (model_dir / _MODEL_REGISTRY[name]["check_file"]).exists()
    return (model_dir / "config.json").exists()


def get_model_repo_id(name: str) -> str | None:
    """Get the HuggingFace repo ID for downloading a model."""
    if name in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[name]["repo_id"]
    return None


# ── Import backends to trigger registration ───────────────────────────────
# These imports must be at the bottom to avoid circular imports.

try:
    from . import lfm2vl  # noqa: F401
except ImportError as e:
    logger.debug(f"LFM2-VL backend not available: {e}")

try:
    from . import qwen35  # noqa: F401
except ImportError as e:
    logger.debug(f"Qwen3.5 backend not available: {e}")

try:
    from . import paddleocr_vl  # noqa: F401
except ImportError as e:
    logger.debug(f"PaddleOCR-VL backend not available: {e}")
