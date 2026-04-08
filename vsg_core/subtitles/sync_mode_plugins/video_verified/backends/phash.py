# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/phash.py
"""GPU pHash backend — perceptual hash via 2D DCT on GPU.

No model weights required. Computes a DCT-based perceptual hash per frame,
producing a binary descriptor of length ``hash_size**2`` (1024-bit at the
default ``hash_size=32``). Binary bits are mapped to -1/+1 so the existing
cosine-sliding harness works unchanged.

Empirical sharpness (from ``Tests/Isc Tests/``) exceeds ISC in every case
tested — at 1024-bit this is the sharpest backend available. Runs ~3× faster
than ISC per position on GPU.

Port source: ``/home/chaoz/Desktop/Makemkv/Tests/Isc Tests/classical.py`` —
``PHashModule`` class and ``load_phash`` factory.

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class PHashBackend:
    name = "phash"
    display_name = "pHash (GPU)"
    requires_weights = False
    needs_subprocess = False
    weights_filename = None

    def __init__(self) -> None:
        self._dct_basis: Any = None
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("PHashBackend.load is implemented in Phase 2")

    def score(
        self,
        src_rgb_clip: Any,
        src_frame_nums: list[int],
        tgt_rgb_clip: Any,
        tgt_frame_nums: list[int],
        device: "torch.device",
        batch_size: int,
        settings: Any,
    ) -> BackendResult:
        raise NotImplementedError("PHashBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        self._dct_basis = None
