# vsg_core/subtitles/sync_mode_plugins/video_verified/backends/sscd_large.py
"""SSCD disc_large neural backend — larger variant of Meta's SSCD.

44M params, 320×320 input, 512-dim L2-normalized descriptor. Identical
to ``SscdMixupBackend`` except for the weights filename and display
name — the architecture, normalization, and extraction pipeline are
the same. Implementation subclasses ``SscdMixupBackend`` and overrides
the class attributes to avoid ~200 lines of duplication.

Downloaded by ``setup_gui.py::download_sscd_models`` from Meta's CDN:
    https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_large.torchscript.pt

Weights file: ``models/sscd/sscd_disc_large.torchscript.pt``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..sliding_core import get_backend_model_dir
from .sscd_mixup import SscdMixupBackend

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

_WEIGHTS_FILENAME = "sscd_disc_large.torchscript.pt"


class SscdLargeBackend(SscdMixupBackend):
    """Large SSCD variant. Only difference from mixup is the weights file."""

    name = "sscd_large"
    display_name = "SSCD disc_large"
    weights_filename = _WEIGHTS_FILENAME

    def load(self, device: "torch.device", settings: Any) -> None:  # noqa: ARG002
        import torch

        weights_path = get_backend_model_dir("sscd") / _WEIGHTS_FILENAME
        if not weights_path.is_file():
            raise FileNotFoundError(
                f"SSCD disc_large weights not found at: {weights_path}\n"
                "Run setup_gui.py and use the Models tab to download SSCD weights."
            )

        try:
            model = torch.jit.load(str(weights_path), map_location="cpu")
        except Exception as e:
            raise RuntimeError(
                f"Failed to load SSCD disc_large TorchScript from {weights_path}: {e}"
            ) from e

        model.to(device).eval()
        self._model = model
        self._device = device
        # Same ImageNet normalization as the mixup variant
        from .sscd_mixup import _IMAGENET_MEAN, _IMAGENET_STD

        self._mean = torch.tensor(_IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
        self._std = torch.tensor(_IMAGENET_STD, device=device).view(1, 3, 1, 1)

        logger.info("SSCD disc_large loaded on %s (320x320, 512-dim)", device)
