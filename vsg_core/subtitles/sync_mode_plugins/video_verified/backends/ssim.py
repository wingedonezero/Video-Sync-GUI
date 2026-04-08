# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/ssim.py
"""GPU SSIM backend — Structural Similarity Index, pairwise scoring.

No model weights required. Unlike the other backends, SSIM is *pairwise*
— it cannot produce per-frame descriptors that the cosine-slide harness
can consume. Instead, ``score()`` extracts grayscale tensors for both
windows and then runs a slide loop that recomputes SSIM at every
candidate slide position directly.

Frames are resized to ``ssim_input_size × ssim_input_size`` (default
256) before scoring. Uses a fast box-filter SSIM kernel (``avg_pool2d``
with a uniform 11×11 window) rather than a Gaussian window — nearly
identical results, noticeably faster on GPU.

``ssim_input_size`` is read from ``settings.video_verified_ssim_input_size``
at ``load()`` time. Larger = sharper peaks but more VRAM and slower
per position.

Port source: ``Tests/Isc Tests/classical.py::_ssim_pair`` +
``_extract_gray_tensor_batch`` + ``run_sliding_ssim``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import BackendResult

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)


def _ssim_pair(
    x: "torch.Tensor",
    y: "torch.Tensor",
    window: int = 11,
    c1: float = 0.01**2,
    c2: float = 0.03**2,
) -> "torch.Tensor":
    """Pairwise SSIM between two batches of grayscale images.

    Inputs are ``[B, 1, H, W]`` in ``[0, 1]``. Returns a tensor of shape
    ``[B]`` with the mean SSIM per image pair. Uses an ``window × window``
    uniform box filter.
    """
    import torch.nn.functional as F

    pad = window // 2
    mu_x = F.avg_pool2d(x, window, stride=1, padding=pad)
    mu_y = F.avg_pool2d(y, window, stride=1, padding=pad)
    mu_x2 = mu_x * mu_x
    mu_y2 = mu_y * mu_y
    mu_xy = mu_x * mu_y
    sigma_x2 = F.avg_pool2d(x * x, window, stride=1, padding=pad) - mu_x2
    sigma_y2 = F.avg_pool2d(y * y, window, stride=1, padding=pad) - mu_y2
    sigma_xy = F.avg_pool2d(x * y, window, stride=1, padding=pad) - mu_xy
    num = (2 * mu_xy + c1) * (2 * sigma_xy + c2)
    den = (mu_x2 + mu_y2 + c1) * (sigma_x2 + sigma_y2 + c2)
    ssim_map = num / den
    return ssim_map.mean(dim=(1, 2, 3))


class SsimBackend:
    name = "ssim"
    display_name = "SSIM (GPU)"
    requires_weights = False
    # See PHashBackend for the rationale: subprocess isolation is needed
    # even for weight-less classical backends because torch's CUDA/ROCm
    # context (cuBLAS, MIOpen primitive caches, driver state) leaks
    # several GB of host RAM that only os.exit() reclaims. SSIM also
    # keeps every src/tgt frame on-device for the slide loop, so its
    # peak VRAM is even more important to clean up between sources.
    needs_subprocess = True
    weights_filename = None

    def __init__(self) -> None:
        self._device: Any = None
        self._luma: Any = None
        self._input_size: int = 256

    def load(self, device: "torch.device", settings: Any) -> None:
        import torch

        input_size = int(getattr(settings, "video_verified_ssim_input_size", 256))
        if input_size < 32:
            raise ValueError(
                f"video_verified_ssim_input_size must be >= 32, got {input_size}"
            )

        self._device = device
        self._input_size = input_size
        self._luma = torch.tensor(
            [0.299, 0.587, 0.114], device=device
        ).view(1, 3, 1, 1)

        logger.info(
            "SsimBackend loaded: input_size=%d, device=%s", input_size, device
        )

    def score(
        self,
        src_rgb_clip: Any,
        src_frame_nums: list[int],
        tgt_rgb_clip: Any,
        tgt_frame_nums: list[int],
        device: "torch.device",
        batch_size: int,  # noqa: ARG002 — unused; SSIM reads all frames at once
        settings: Any,  # noqa: ARG002
    ) -> BackendResult:
        if self._luma is None:
            raise RuntimeError("SsimBackend.load() must be called before score()")

        import torch

        size = self._input_size

        # ─── Extract grayscale tensors for both windows ──────────────
        t_extract_start = time.perf_counter()
        src_gray = self._extract_gray_batch(src_rgb_clip, src_frame_nums, device)
        tgt_gray = self._extract_gray_batch(tgt_rgb_clip, tgt_frame_nums, device)
        extract_time_s = time.perf_counter() - t_extract_start

        # ─── Pairwise SSIM at every slide position ───────────────────
        t_score_start = time.perf_counter()
        S = src_gray.shape[0]
        T = tgt_gray.shape[0]
        max_slides = T - S + 1

        if max_slides <= 0:
            score_time_s = time.perf_counter() - t_score_start
            return BackendResult(
                scores=np.array([], dtype=np.float64),
                match_counts=np.array([], dtype=np.int64),
                descriptor_dim=size * size,
                extract_time_s=extract_time_s,
                score_time_s=score_time_s,
            )

        all_pairs = torch.empty((max_slides, S), device=device)
        with torch.no_grad():
            for p in range(max_slides):
                tgt_window = tgt_gray[p : p + S]
                ssim_vals = _ssim_pair(src_gray, tgt_window)
                all_pairs[p] = ssim_vals

        scores_t = all_pairs.mean(dim=1)
        scores = scores_t.cpu().numpy().astype(np.float64)
        match_counts = (all_pairs > 0.5).sum(dim=1).cpu().numpy().astype(np.int64)
        score_time_s = time.perf_counter() - t_score_start

        # Release GPU memory before returning
        del src_gray, tgt_gray, all_pairs
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return BackendResult(
            scores=scores,
            match_counts=match_counts,
            descriptor_dim=size * size,
            extract_time_s=extract_time_s,
            score_time_s=score_time_s,
        )

    def _extract_gray_batch(
        self,
        rgb_clip: Any,
        frame_nums: list[int],
        device: "torch.device",
    ) -> "torch.Tensor":
        """Return a ``[N, 1, size, size]`` grayscale tensor in ``[0, 1]``.

        Unlike the feature backends, SSIM needs every frame kept on-device
        at once (so the slide loop can index into tgt_gray without re-I/O).
        The memory cost is ``N × size**2 × 4`` bytes per clip, e.g.
        ~63 MB for 240 frames at 256×256, ~250 MB at 512×512.
        """
        import torch
        import torch.nn.functional as F

        assert self._luma is not None

        size = self._input_size
        N = len(frame_nums)
        out = torch.empty((N, 1, size, size), device=device)

        first_frame = frame_nums[0]
        last_frame = frame_nums[-1]
        is_contiguous = frame_nums == list(range(first_frame, last_frame + 1))

        def load_frame_to_gray(frame: Any, idx: int) -> None:
            r = np.asarray(frame[0])
            g = np.asarray(frame[1])
            b = np.asarray(frame[2])
            rgb_np = np.stack([r, g, b], axis=0).astype(np.float32) / 255.0
            tensor = torch.from_numpy(rgb_np).unsqueeze(0).to(device)
            resized = F.interpolate(
                tensor, size=(size, size), mode="bilinear", align_corners=False
            )
            gray = (resized * self._luma).sum(dim=1, keepdim=True)
            out[idx : idx + 1] = gray

        with torch.no_grad():
            if is_contiguous:
                trimmed = rgb_clip[first_frame : last_frame + 1]
                for i, frame in enumerate(trimmed.frames()):
                    load_frame_to_gray(frame, i)
            else:
                for idx, fn in enumerate(frame_nums):
                    fn_clamped = max(0, min(fn, rgb_clip.num_frames - 1))
                    frame = rgb_clip.get_frame(fn_clamped)
                    load_frame_to_gray(frame, idx)

        return out

    def cleanup(self) -> None:
        self._luma = None
        self._device = None
