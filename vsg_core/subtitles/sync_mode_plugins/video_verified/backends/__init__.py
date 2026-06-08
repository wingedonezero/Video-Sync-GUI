# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/__init__.py
"""Registry of sliding-window backends for video-verified sync.

Exposes ``get_backend(name)`` which returns a fresh backend instance for the
given ``VideoVerifiedBackendStr`` value. The orchestrator uses this to route
the sliding-window matcher to the correct feature extractor.

Available backends:
    isc          — ISC ft_v107 neural features (existing, 52M params, 512² input)
    sscd_mixup   — Meta SSCD disc_mixup TorchScript (25M params, 320² input)
    sscd_large   — Meta SSCD disc_large TorchScript (44M params, 320² input)
    phash        — GPU pHash via torch DCT (no weights; hash_size-driven)
    dhash        — GPU dHash via torch difference (no weights)
    ssim         — GPU SSIM pairwise scoring (no weights; input_size-driven)

See ``base.py`` for the ``SlidingBackend`` protocol and ``BackendResult`` shape.
"""

from __future__ import annotations

import os

from .base import BackendResult, SlidingBackend
from .dhash import DHashBackend
from .isc import IscBackend
from .phash import PHashBackend
from .sscd_large import SscdLargeBackend
from .sscd_mixup import SscdMixupBackend
from .ssim import SsimBackend

# Pin video-verified GPU backends to the discrete GPU (device 0). The backends
# import torch lazily at load()/runtime, so this import-time setdefault lands
# before any HIP init. On dual-GPU ROCm systems the iGPU otherwise SIGSEGVs on
# first kernel launch; setdefault so main.py's global pin / an explicit override
# still wins. Matches the OCR pin in ocr/vlm_backends/__init__.py.
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")

BACKEND_REGISTRY: dict[str, type[SlidingBackend]] = {
    "isc": IscBackend,
    "sscd_mixup": SscdMixupBackend,
    "sscd_large": SscdLargeBackend,
    "phash": PHashBackend,
    "dhash": DHashBackend,
    "ssim": SsimBackend,
}

BACKEND_NAMES: tuple[str, ...] = tuple(BACKEND_REGISTRY.keys())


def get_backend(name: str) -> SlidingBackend:
    """Return a fresh instance of the backend registered under ``name``.

    Raises ``ValueError`` with the list of valid names if ``name`` is unknown.
    """
    cls = BACKEND_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown video-verified backend: {name!r}. "
            f"Valid options: {sorted(BACKEND_REGISTRY)}"
        )
    return cls()


__all__ = [
    "BACKEND_NAMES",
    "BACKEND_REGISTRY",
    "BackendResult",
    "DHashBackend",
    "IscBackend",
    "PHashBackend",
    "SlidingBackend",
    "SscdLargeBackend",
    "SscdMixupBackend",
    "SsimBackend",
    "get_backend",
]
