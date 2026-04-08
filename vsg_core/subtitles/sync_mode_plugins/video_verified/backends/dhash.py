# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/dhash.py
"""GPU dHash backend — difference hash via adjacent-column comparison.

No model weights required. Resizes each frame to ``hash_size × (hash_size+1)``
grayscale and compares adjacent columns to build a binary descriptor of
length ``hash_size**2`` (1024-bit at the default ``hash_size=32``). Binary
bits are mapped to -1/+1 and scaled by ``1/sqrt(descriptor_dim)`` so the
resulting vector is L2-normalized and plugs into the cosine-slide harness
correctly.

Faster than pHash (no DCT, just a resize and a comparison) but with
slightly less sharp peaks. Still a valid primary or cross-check backend.

``hash_size`` is read from ``settings.video_verified_hash_size`` at
``load()`` time and shared with ``PHashBackend`` (one setting, used by
whichever hash backend is active).

Port source: ``Tests/Isc Tests/classical.py::DHashModule`` + ``load_dhash``.
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


class DHashBackend:
    name = "dhash"
    display_name = "dHash (GPU)"
    requires_weights = False
    # See PHashBackend for the rationale: subprocess isolation is needed
    # even for weight-less classical backends because torch's CUDA/ROCm
    # context (cuBLAS, MIOpen primitive caches, driver state) leaks
    # several GB of host RAM that only os.exit() reclaims.
    needs_subprocess = True
    weights_filename = None

    def __init__(self) -> None:
        self._device: Any = None
        self._luma: Any = None
        self._hash_size: int = 32

    def load(self, device: "torch.device", settings: Any) -> None:
        import torch

        hash_size = int(getattr(settings, "video_verified_hash_size", 32))
        if hash_size < 4:
            raise ValueError(f"video_verified_hash_size must be >= 4, got {hash_size}")

        self._device = device
        self._hash_size = hash_size
        self._luma = torch.tensor(
            [0.299, 0.587, 0.114], device=device
        ).view(1, 3, 1, 1)

        logger.info(
            "DHashBackend loaded: hash_size=%d (%d-bit), device=%s",
            hash_size,
            hash_size * hash_size,
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
        if self._luma is None:
            raise RuntimeError("DHashBackend.load() must be called before score()")

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
        """Produce the dHash binary descriptor for each frame.

        Returns shape ``[N, hash_size**2]`` with values in {-1/s, +1/s}
        where ``s = sqrt(hash_size**2)``, giving unit L2 norm for every row.
        """
        import torch
        import torch.nn.functional as F

        assert self._luma is not None

        hash_size = self._hash_size
        descriptor_dim = hash_size * hash_size
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
            # dHash needs (W = hash_size+1, H = hash_size) so there's an
            # extra column to compare against the previous one.
            resized = F.interpolate(
                tensor,
                size=(hash_size, hash_size + 1),
                mode="bilinear",
                align_corners=False,
            )
            batch_tensors.append(resized.squeeze(0))

        def flush_batch() -> None:
            if not batch_tensors:
                return
            batch = torch.stack(batch_tensors).to(device)  # [B, 3, H, W+1]
            gray = (batch * self._luma).sum(dim=1)  # [B, H, W+1]
            # Compare each column to the next: left > right → 1, else 0
            bits = (gray[:, :, :-1] > gray[:, :, 1:]).float()  # [B, H, W]
            flat = bits.reshape(bits.shape[0], -1)  # [B, H*W]
            desc = (flat * 2.0 - 1.0) * scale
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
        self._luma = None
        self._device = None
