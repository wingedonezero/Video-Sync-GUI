# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/phash.py
"""GPU pHash backend — perceptual hash via 2D DCT on GPU.

No model weights required. Computes a 2D DCT-II of each frame's
grayscale signal, keeps the top-left ``hash_size × hash_size`` low-
frequency block, thresholds against the median, and maps the binary
result to -1/+1 so the existing cosine-slide harness scores it
correctly. The resulting descriptor is length ``hash_size**2`` (1024-bit
at the default ``hash_size=32``) and is L2-normalized by construction
(``/ hash_size`` yields unit length when all ±1 values are present).

Empirical sharpness (from ``Tests/Isc Tests/``) exceeds ISC in every
test case — at 1024-bit this is the sharpest backend available. Runs
roughly 3× faster than ISC per position on GPU because there's no
model forward pass, just resize + DCT.

``hash_size`` is read from ``settings.video_verified_hash_size`` at
``load()`` time. DCT size is always 4× hash_size (minimum 32) because
the DCT needs enough input resolution to produce meaningful
low-frequency coefficients — this mirrors ``imagehash.phash`` defaults.

Port source: ``Tests/Isc Tests/classical.py::PHashModule`` + ``load_phash``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from ..sliding_core import cosine_slide
from .base import BackendResult

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)


def _dct_ii_matrix(N: int, device: "torch.device") -> "torch.Tensor":
    """Type-II orthonormal DCT basis matrix of shape [N, N]."""
    import torch

    n = torch.arange(N, device=device).float()
    k = torch.arange(N, device=device).float().unsqueeze(1)
    M = torch.cos((torch.pi / N) * (n + 0.5) * k)
    M[0] *= 1.0 / (N**0.5)
    M[1:] *= (2.0 / N) ** 0.5
    return M


class PHashBackend:
    name = "phash"
    display_name = "pHash (GPU)"
    requires_weights = False
    needs_subprocess = False
    weights_filename = None

    def __init__(self) -> None:
        self._device: Any = None
        self._dct_matrix: Any = None  # [dct_size, dct_size]
        self._luma: Any = None  # [1, 3, 1, 1]
        self._hash_size: int = 32
        self._dct_size: int = 32

    def load(self, device: "torch.device", settings: Any) -> None:
        import torch

        hash_size = int(getattr(settings, "video_verified_hash_size", 32))
        if hash_size < 4:
            raise ValueError(f"video_verified_hash_size must be >= 4, got {hash_size}")

        # DCT input size should be at least 4× the hash size (and at least 32)
        # so the low-frequency coefficients we keep are well-defined. This
        # matches imagehash.phash's default of 32x32 DCT for hash_size=8.
        dct_size = max(32, hash_size * 4)

        self._device = device
        self._hash_size = hash_size
        self._dct_size = dct_size
        self._dct_matrix = _dct_ii_matrix(dct_size, device)
        self._luma = torch.tensor(
            [0.299, 0.587, 0.114], device=device
        ).view(1, 3, 1, 1)

        logger.info(
            "PHashBackend loaded: hash_size=%d (%d-bit), dct_size=%d, device=%s",
            hash_size,
            hash_size * hash_size,
            dct_size,
            device,
        )

    def score(
        self,
        src_rgb_clip: Any,
        src_frame_nums: list[int],
        tgt_rgb_clip: Any,
        tgt_frame_nums: list[int],
        device: "torch.device",
        batch_size: int,
        settings: Any,  # noqa: ARG002
    ) -> BackendResult:
        if self._dct_matrix is None:
            raise RuntimeError("PHashBackend.load() must be called before score()")

        descriptor_dim = self._hash_size * self._hash_size

        t_extract_start = time.perf_counter()
        src_feats = self._extract_descriptors(
            src_rgb_clip, src_frame_nums, device, batch_size
        )
        tgt_feats = self._extract_descriptors(
            tgt_rgb_clip, tgt_frame_nums, device, batch_size
        )
        extract_time_s = time.perf_counter() - t_extract_start

        t_score_start = time.perf_counter()
        scores, match_counts = cosine_slide(src_feats, tgt_feats)
        score_time_s = time.perf_counter() - t_score_start

        return BackendResult(
            scores=scores,
            match_counts=match_counts,
            descriptor_dim=descriptor_dim,
            extract_time_s=extract_time_s,
            score_time_s=score_time_s,
        )

    def _extract_descriptors(
        self,
        rgb_clip: Any,
        frame_nums: list[int],
        device: "torch.device",
        batch_size: int,
    ) -> np.ndarray:
        """Produce the binary pHash descriptor for each frame.

        Returns a numpy array of shape ``[N, hash_size**2]`` with values
        mapped to -1/+1 and scaled by ``1/hash_size`` so the L2 norm of
        every row is 1.0 (the cosine-slide harness expects unit-norm
        descriptors).
        """
        import torch
        import torch.nn.functional as F

        assert self._dct_matrix is not None and self._luma is not None

        hash_size = self._hash_size
        dct_size = self._dct_size
        descriptor_dim = hash_size * hash_size
        # Scale factor so ±1/s yields L2 norm == 1 when length == descriptor_dim
        scale = 1.0 / (descriptor_dim**0.5)

        all_desc: list[torch.Tensor] = []
        batch_tensors: list[torch.Tensor] = []

        first_frame = frame_nums[0]
        last_frame = frame_nums[-1]
        is_contiguous = frame_nums == list(range(first_frame, last_frame + 1))

        def push_tensor_from_frame(frame: Any) -> None:
            r = np.asarray(frame[0])
            g = np.asarray(frame[1])
            b = np.asarray(frame[2])
            rgb_np = np.stack([r, g, b], axis=0).astype(np.float32) / 255.0
            tensor = torch.from_numpy(rgb_np).unsqueeze(0).to(device)
            resized = F.interpolate(
                tensor, size=(dct_size, dct_size), mode="bilinear", align_corners=False
            )
            # Resized is [1, 3, dct_size, dct_size] in [0, 1]
            batch_tensors.append(resized.squeeze(0))

        def flush_batch() -> None:
            if not batch_tensors:
                return
            batch = torch.stack(batch_tensors).to(device)  # [B, 3, dct_size, dct_size]
            # RGB → grayscale via Rec. 601 luma
            gray = (batch * self._luma).sum(dim=1)  # [B, dct_size, dct_size]
            # 2D DCT-II via M @ X @ M.T (orthonormal)
            dct = self._dct_matrix @ gray @ self._dct_matrix.T
            # Keep top-left hash_size x hash_size block (low frequencies)
            low = dct[:, :hash_size, :hash_size]  # [B, hash_size, hash_size]
            flat = low.reshape(low.shape[0], -1)  # [B, hash_size**2]
            # Threshold against median of non-DC terms (imagehash convention)
            med = flat[:, 1:].median(dim=1, keepdim=True).values
            bits = (flat > med).float()  # 0/1 binary descriptor
            # Map 0/1 → -1/+1 and scale so L2 norm is 1
            desc = (bits * 2.0 - 1.0) * scale
            all_desc.append(desc.cpu())
            batch_tensors.clear()

        with torch.no_grad():
            if is_contiguous:
                trimmed = rgb_clip[first_frame : last_frame + 1]
                for i, frame in enumerate(trimmed.frames()):
                    push_tensor_from_frame(frame)
                    if len(batch_tensors) == batch_size or i == len(frame_nums) - 1:
                        flush_batch()
            else:
                for idx, fn in enumerate(frame_nums):
                    fn_clamped = max(0, min(fn, rgb_clip.num_frames - 1))
                    frame = rgb_clip.get_frame(fn_clamped)
                    push_tensor_from_frame(frame)
                    if len(batch_tensors) == batch_size or idx == len(frame_nums) - 1:
                        flush_batch()

        return torch.cat(all_desc, dim=0).numpy()

    def cleanup(self) -> None:
        self._dct_matrix = None
        self._luma = None
        self._device = None
