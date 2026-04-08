# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/ssim.py
"""GPU SSIM backend — Structural Similarity Index, pairwise scoring.

No model weights required. Unlike the other backends, SSIM is *pairwise* —
it cannot produce per-frame descriptors. Its ``score()`` implementation
therefore runs a slide loop internally that recomputes SSIM at every
candidate slide position directly, rather than extracting features once
and sliding via cosine.

Frames are resized to ``ssim_input_size`` (default 256×256) before scoring.
Uses a fast box-filter SSIM kernel.

Port source: ``/home/chaoz/Desktop/Makemkv/Tests/Isc Tests/classical.py`` —
``_ssim_pair`` function and ``run_sliding_ssim`` loop.

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class SsimBackend:
    name = "ssim"
    display_name = "SSIM (GPU)"
    requires_weights = False
    needs_subprocess = False
    weights_filename = None

    def __init__(self) -> None:
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("SsimBackend.load is implemented in Phase 2")

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
        raise NotImplementedError("SsimBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        pass
