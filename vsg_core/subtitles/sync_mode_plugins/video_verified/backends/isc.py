# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/isc.py
"""ISC ft_v107 neural backend — the original Image Similarity Challenge model.

52M params, 512×512 input, 256-dim L2-normalized descriptor. Runs on GPU.
Same architecture and behavior as the legacy ``isc_model.py`` +
``neural_matcher._extract_features_batch``/``_frame_to_tensor`` pipeline,
now exposed through the unified ``SlidingBackend`` protocol.

Weights file: ``models/isc/isc_ft_v107_weights.pt`` (downloaded by the
ISC button in ``setup_gui.py``).

Normalization: (0.5, 0.5, 0.5) mean and std — NOT ImageNet defaults.
Input: 512×512 RGB tensor.
Output: 256-dim L2-normalized descriptor.
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
    import torch.nn as nn

logger = logging.getLogger(__name__)

# Model constants
_WEIGHTS_FILENAME = "isc_ft_v107_weights.pt"
_INPUT_SIZE = 512
_DESCRIPTOR_DIM = 256
_NORMALIZE_MEAN = (0.5, 0.5, 0.5)
_NORMALIZE_STD = (0.5, 0.5, 0.5)


def _gem(x: "torch.Tensor", p: float = 3.0, eps: float = 1e-6) -> "torch.Tensor":
    """Generalized Mean (GeM) pooling — ISC's global aggregation."""
    import torch.nn.functional as F

    return F.avg_pool2d(x.clamp(min=eps).pow(p), (x.size(-2), x.size(-1))).pow(
        1.0 / p
    )


def _build_isc_net(ckpt: dict) -> "nn.Module":
    """Reconstruct the ISCNet architecture from a stripped checkpoint.

    Expects a dict with keys ``state_dict`` and ``arch`` where ``arch`` is
    the timm model name (e.g. ``"timm/tf_efficientnetv2_m.in21k_ft_in1k"``).
    """
    import timm
    import torch.nn as nn
    import torch.nn.functional as F

    class ISCNet(nn.Module):
        def __init__(self, backbone: nn.Module, fc_dim: int = _DESCRIPTOR_DIM):
            super().__init__()
            self.backbone = backbone
            self.fc = nn.Linear(
                self.backbone.feature_info.info[-1]["num_chs"], fc_dim, bias=False
            )
            self.bn = nn.BatchNorm1d(fc_dim)
            self.p = 1.0
            self.eval_p = 1.0
            self.l2_normalize = True

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            batch_size = x.shape[0]
            x = self.backbone(x)[-1]
            p = self.p if self.training else self.eval_p
            x = _gem(x, p).view(batch_size, -1)
            x = self.fc(x)
            x = self.bn(x)
            if self.l2_normalize:
                x = F.normalize(x)
            return x

    backbone = timm.create_model(ckpt["arch"], features_only=True)
    model = ISCNet(backbone=backbone, fc_dim=_DESCRIPTOR_DIM)
    model.load_state_dict(ckpt["state_dict"])
    return model


class IscBackend:
    name = "isc"
    display_name = "ISC ft_v107"
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

        weights_path = get_backend_model_dir("isc") / _WEIGHTS_FILENAME
        if not weights_path.is_file():
            raise FileNotFoundError(
                f"ISC weights not found at: {weights_path}\n"
                "Run setup_gui.py and use the Models tab to download ISC weights."
            )

        ckpt = torch.load(str(weights_path), map_location="cpu", weights_only=False)
        model = _build_isc_net(ckpt)
        model.to(device).eval()

        self._model = model
        self._device = device
        # Pre-build mean/std tensors on the target device (avoids per-frame alloc)
        self._mean = torch.tensor(_NORMALIZE_MEAN, device=device).view(1, 3, 1, 1)
        self._std = torch.tensor(_NORMALIZE_STD, device=device).view(1, 3, 1, 1)

        n_params = sum(p.numel() for p in model.parameters())
        logger.info("ISC model loaded (%.1fM params) on %s", n_params / 1e6, device)

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
            raise RuntimeError("IscBackend.load() must be called before score()")

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
        """Extract 256-dim ISC descriptors for the given frame indices.

        Fast path via ``clip.frames()`` for contiguous ranges; slow path
        via ``clip.get_frame(n)`` for non-contiguous. GPU batching respects
        ``batch_size`` from settings.
        """
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
        # Best-effort VRAM release; safe to call when torch isn't imported
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
