# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/isc.py
"""ISC ft_v107 neural backend — the original Image Similarity Challenge model.

52M params, 512×512 input, 256-dim L2-normalized descriptor. Runs on GPU.
This is the existing backend from ``neural_matcher.py``, now exposed through
the unified SlidingBackend protocol. Phase 2 of the refactor fills in the
``score()`` method by lifting code from the current ``isc_model.py`` +
``neural_matcher.py::_extract_features_batch`` / ``_frame_to_tensor`` /
``_slide_and_score`` helpers.

Stub — Phase 1 scaffolding only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BackendResult

if TYPE_CHECKING:
    import torch


class IscBackend:
    name = "isc"
    display_name = "ISC ft_v107"
    requires_weights = True
    needs_subprocess = True
    weights_filename = "isc_ft_v107_weights.pt"

    def __init__(self) -> None:
        self._model: Any = None
        self._device: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:
        raise NotImplementedError("IscBackend.load is implemented in Phase 2")

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
        raise NotImplementedError("IscBackend.score is implemented in Phase 2")

    def cleanup(self) -> None:
        self._model = None
