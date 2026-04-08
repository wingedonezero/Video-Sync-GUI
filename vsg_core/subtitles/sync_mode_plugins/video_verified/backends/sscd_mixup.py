# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/sscd_mixup.py
"""SSCD disc_mixup neural backend — Meta's 2022 copy-detection model.

Direct ISC successor. 25M params (vs ISC 52M), 320×320 input, 512-dim
L2-normalized descriptor. Faster than ISC per position with sharper peaks
in the empirical benchmarks. Loaded via ``torch.jit.load`` — no timm needed.

Downloaded via ``setup_gui.py::download_sscd_models`` from Meta's CDN:
    https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class SscdMixupBackend:
    name = "sscd_mixup"
    display_name = "SSCD disc_mixup"
    requires_weights = True
    needs_subprocess = True
    weights_filename = "sscd_disc_mixup.torchscript.pt"

    def __init__(self) -> None:
        self._model: Any = None
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("SscdMixupBackend.load is implemented in Phase 2")

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
        raise NotImplementedError("SscdMixupBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        self._model = None
