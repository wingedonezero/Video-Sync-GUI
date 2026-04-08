# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/dhash.py
"""GPU dHash backend — difference hash via adjacent-column comparison.

No model weights required. Resizes each frame to ``(hash_size+1, hash_size)``
grayscale and compares adjacent columns to build a binary descriptor of
length ``hash_size * (hash_size)`` (1024-bit at the default ``hash_size=32``).
Binary bits mapped to -1/+1 so the existing cosine-sliding harness works
unchanged.

Faster than pHash (no DCT) with slightly less sharp peaks, but still a
valid primary or cross-check backend.

Port source: ``/home/chaoz/Desktop/Makemkv/Tests/Isc Tests/classical.py`` —
``DHashModule`` class and ``load_dhash`` factory.

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class DHashBackend:
    name = "dhash"
    display_name = "dHash (GPU)"
    requires_weights = False
    needs_subprocess = False
    weights_filename = None

    def __init__(self) -> None:
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("DHashBackend.load is implemented in Phase 2")

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
        raise NotImplementedError("DHashBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        pass
