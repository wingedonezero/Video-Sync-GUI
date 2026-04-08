# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/sscd_large.py
"""SSCD disc_large neural backend — larger variant of Meta's SSCD.

44M params, 320×320 input, 512-dim L2-normalized descriptor. Slightly slower
than ``sscd_mixup`` but with different accuracy characteristics on edge cases.
Same TorchScript loading pattern as the mixup variant.

Downloaded via ``setup_gui.py::download_sscd_models`` from Meta's CDN:
    https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_large.torchscript.pt

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class SscdLargeBackend:
    name = "sscd_large"
    display_name = "SSCD disc_large"
    requires_weights = True
    needs_subprocess = True
    weights_filename = "sscd_disc_large.torchscript.pt"

    def __init__(self) -> None:
        self._model: Any = None
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("SscdLargeBackend.load is implemented in Phase 2")

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
        raise NotImplementedError("SscdLargeBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        self._model = None
