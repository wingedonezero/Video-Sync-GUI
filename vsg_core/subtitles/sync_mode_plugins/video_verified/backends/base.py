# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/base.py
"""Base protocol and result dataclass for video-verified sliding backends.

A SlidingBackend is a pluggable feature-extraction + scoring strategy for the
sliding-window matcher. Feature-based backends (ISC, SSCD, pHash, dHash)
extract per-frame descriptors and score via cosine similarity across slide
positions. Pairwise backends (SSIM) run pairwise scoring directly at every
slide position without producing descriptors. The orchestrator doesn't care
which paradigm a backend uses — it only asks for a ``BackendResult`` via the
``score()`` method.

All backends share the sliding-window harness in ``sliding_core.py``, which
owns frame I/O, PTS correction, consensus voting, and debug reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    import torch


@dataclass
class BackendResult:
    """What a backend returns from ``score()`` for a single sliding position.

    Attributes
    ----------
    scores
        Shape ``[max_slides]``. Mean similarity across the paired frames
        at each slide position. Higher = better match. For feature-based
        backends this is mean pairwise cosine; for SSIM it's mean SSIM.
    match_counts
        Shape ``[max_slides]``. Count of pair similarities above 0.5 at each
        slide position. Provided for parity with the existing debug log
        format (used as a confidence signal alongside the raw scores).
    descriptor_dim
        Diagnostic only — the feature dimensionality the backend produced
        (256 for ISC, 512 for SSCD, ``hash_size**2`` for pHash/dHash, or
        ``input_size**2`` for SSIM). Stored in the final debug report.
    extract_time_s
        Wall-clock seconds spent on feature extraction (or frame I/O for
        pairwise backends). Diagnostic only.
    score_time_s
        Wall-clock seconds spent on the sliding score loop. Diagnostic only.
    extra
        Optional free-form dict for backend-specific diagnostics that the
        debug report should preserve (e.g. per-frame DCT coefficients,
        intermediate tensors, etc.). Must be JSON-serializable.
    """

    scores: np.ndarray
    match_counts: np.ndarray
    descriptor_dim: int
    extract_time_s: float
    score_time_s: float
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SlidingBackend(Protocol):
    """Protocol every video-verified backend implements.

    The matcher instantiates a backend via ``get_backend(name)`` from the
    registry in ``backends/__init__.py``, calls ``load(device, settings)``
    exactly once, then calls ``score()`` once per sliding-window position,
    and finally calls ``cleanup()`` to release any GPU resources.

    Attributes
    ----------
    name
        Registry key that matches ``VideoVerifiedBackendStr`` (e.g. ``"isc"``,
        ``"sscd_mixup"``, ``"phash"``).
    display_name
        Human-readable label for logs and the final audit report
        (e.g. ``"ISC ft_v107"``, ``"pHash (1024-bit)"``).
    requires_weights
        ``True`` if the backend needs a model file on disk. Used by the
        setup GUI and error messaging when weights are missing.
    needs_subprocess
        ``True`` if the backend should run inside the subprocess isolation
        wrapper (applies to any backend that loads a large model into VRAM
        — ISC, SSCD). Hash backends bypass subprocess isolation entirely
        because their startup cost dwarfs their runtime.
    weights_filename
        Filename of the weights file inside ``models/{backend_dir}/``.
        ``None`` for backends that require no weights (pHash, dHash, SSIM).
    """

    name: str
    display_name: str
    requires_weights: bool
    needs_subprocess: bool
    weights_filename: str | None

    def load(self, device: "torch.device", settings: Any) -> None:
        """Load model weights (if any) onto ``device``.

        Called exactly once per backend instance before any ``score()`` call.
        For weight-less backends (pHash, dHash, SSIM) this typically just
        initializes small tensors (DCT basis, SSIM kernels) on the GPU.
        """
        ...

    def score(
        self,
        src_rgb_clip: Any,          # VapourSynth RGB24 clip
        src_frame_nums: list[int],
        tgt_rgb_clip: Any,          # VapourSynth RGB24 clip
        tgt_frame_nums: list[int],
        device: "torch.device",
        batch_size: int,
        settings: Any,
    ) -> BackendResult:
        """Score a sliding window between source and target frame ranges.

        The orchestrator has already applied PTS correction — ``src_frame_nums``
        and ``tgt_frame_nums`` are wall-clock-aligned frame indices in their
        respective clips. The backend reads frames via ``clip.get_frame(n)`` or
        the ``clip.frames()`` iterator, extracts features (or runs pairwise
        scoring), and returns a ``BackendResult`` covering every valid slide
        position.

        The number of slide positions is ``len(tgt_frame_nums) - len(src_frame_nums) + 1``.
        """
        ...

    def cleanup(self) -> None:
        """Release any GPU resources. Called once when the matcher is done.

        Hash backends can no-op. Neural backends should delete their model
        reference and call ``torch.cuda.empty_cache()`` if relevant.
        """
        ...
