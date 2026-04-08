# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/sscd_mixup.py
"""SSCD disc_mixup neural backend — Meta's 2022 copy-detection model.

Direct ISC successor. 25M params, 320×320 input, 512-dim L2-normalized
descriptor. Loaded via ``torch.jit.load`` — the downloaded file is a
self-contained TorchScript module with the architecture baked in.

Downloaded by ``setup_gui.py::download_sscd_models`` from Meta's CDN:
    https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt

Weights file: ``models/sscd/sscd_disc_mixup.torchscript.pt``.
Normalization: ImageNet (0.485, 0.456, 0.406) / (0.229, 0.224, 0.225).
Input: 320×320 RGB tensor.
Output: 512-dim L2-normalized descriptor (SSCD models include an L2
normalization in the final layer, but we re-normalize defensively
inside ``cosine_slide``).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from ..sliding_core import cosine_slide, get_backend_model_dir
from .base import BackendResult

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

_WEIGHTS_FILENAME = "sscd_disc_mixup.torchscript.pt"
_INPUT_SIZE = 320
_DESCRIPTOR_DIM = 512
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


class SscdMixupBackend:
    name = "sscd_mixup"
    display_name = "SSCD disc_mixup"
    requires_weights = True
    needs_subprocess = True
    weights_filename = _WEIGHTS_FILENAME

    def __init__(self) -> None:
        self._model: Any = None
        self._device: Any = None
        self._mean: Any = None
        self._std: Any = None

    def load(self, device: "torch.device", settings: Any) -> None:  # noqa: ARG002
        import torch

        weights_path = get_backend_model_dir("sscd") / _WEIGHTS_FILENAME
        if not weights_path.is_file():
            raise FileNotFoundError(
                f"SSCD disc_mixup weights not found at: {weights_path}\n"
                "Run setup_gui.py and use the Models tab to download SSCD weights."
            )

        try:
            model = torch.jit.load(str(weights_path), map_location="cpu")
        except Exception as e:
            raise RuntimeError(
                f"Failed to load SSCD disc_mixup TorchScript from {weights_path}: {e}"
            ) from e

        model.to(device).eval()
        self._model = model
        self._device = device
        self._mean = torch.tensor(_IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
        self._std = torch.tensor(_IMAGENET_STD, device=device).view(1, 3, 1, 1)

        logger.info("SSCD disc_mixup loaded on %s (320x320, 512-dim)", device)

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
        if self._model is None:
            raise RuntimeError("SscdMixupBackend.load() must be called before score()")

        t_extract_start = time.perf_counter()
        src_feats = self._extract_features(src_rgb_clip, src_frame_nums, device, batch_size)
        tgt_feats = self._extract_features(tgt_rgb_clip, tgt_frame_nums, device, batch_size)
        extract_time_s = time.perf_counter() - t_extract_start

        t_score_start = time.perf_counter()
        scores, match_counts = cosine_slide(src_feats, tgt_feats)
        score_time_s = time.perf_counter() - t_score_start

        return BackendResult(
            scores=scores,
            match_counts=match_counts,
            descriptor_dim=_DESCRIPTOR_DIM,
            extract_time_s=extract_time_s,
            score_time_s=score_time_s,
        )

    def _extract_features(
        self,
        rgb_clip: Any,
        frame_nums: list[int],
        device: "torch.device",
        batch_size: int,
    ) -> np.ndarray:
        import torch
        import torch.nn.functional as F

        assert self._model is not None
        assert self._mean is not None and self._std is not None

        all_feats: list[torch.Tensor] = []
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
                tensor, size=(_INPUT_SIZE, _INPUT_SIZE), mode="bilinear", align_corners=False
            )
            normalized = (resized - self._mean) / self._std
            batch_tensors.append(normalized.squeeze(0))

        def flush_batch() -> None:
            if not batch_tensors:
                return
            batch = torch.stack(batch_tensors).to(device)
            feats = self._model(batch)
            all_feats.append(feats.cpu())
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

        return torch.cat(all_feats, dim=0).numpy()

    def cleanup(self) -> None:
        self._model = None
        self._mean = None
        self._std = None
        self._device = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
