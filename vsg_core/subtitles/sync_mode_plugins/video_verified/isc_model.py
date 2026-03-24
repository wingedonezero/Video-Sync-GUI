# vsg_core/subtitles/sync_mode_plugins/video_verified/isc_model.py
"""
ISC (Image Similarity Challenge) model for neural video matching.

Self-contained implementation — no external ``isc-feature-extractor`` package
required. Model weights are downloaded via setup_gui.py and stored in
``models/isc/`` at the project root.

Architecture:
    EfficientNetV2-M backbone (via timm) → GeM pooling → 256-dim FC → BN → L2 norm

Model: ISC ft_v107 — 256-dim descriptors, Meta ISC21 competition winner.
Source: https://github.com/lyakaap/ISC21-Descriptor-Track-1st
License: MIT
"""

from __future__ import annotations

import logging
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# Weights filename (stripped checkpoint: state_dict + arch + input_size only)
_WEIGHTS_FILENAME = "isc_ft_v107_weights.pt"

# Original checkpoint URL (full 401MB with optimizer state)
ISC_DOWNLOAD_URL = (
    "https://github.com/lyakaap/ISC21-Descriptor-Track-1st/"
    "releases/download/v1.0.1/isc_ft_v107.pth.tar"
)


# ── Model definition ─────────────────────────────────────────────────────────


def _gem(x: torch.Tensor, p: float = 3.0, eps: float = 1e-6) -> torch.Tensor:
    """Generalized Mean (GeM) pooling."""
    return F.avg_pool2d(x.clamp(min=eps).pow(p), (x.size(-2), x.size(-1))).pow(
        1.0 / p
    )


class ISCNet(nn.Module):
    """Feature extractor for image copy-detection.

    Args:
        backbone: timm feature-extraction model (``features_only=True``).
        fc_dim: output descriptor dimension (default 256).
        p: GeM power for training.
        eval_p: GeM power for evaluation.
        l2_normalize: whether to L2-normalize the output.
    """

    def __init__(
        self,
        backbone: nn.Module,
        fc_dim: int = 256,
        p: float = 1.0,
        eval_p: float = 1.0,
        l2_normalize: bool = True,
    ):
        super().__init__()
        self.backbone = backbone
        self.fc = nn.Linear(
            self.backbone.feature_info.info[-1]["num_chs"], fc_dim, bias=False
        )
        self.bn = nn.BatchNorm1d(fc_dim)
        self.p = p
        self.eval_p = eval_p
        self.l2_normalize = l2_normalize

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size = x.shape[0]
        x = self.backbone(x)[-1]
        p = self.p if self.training else self.eval_p
        x = _gem(x, p).view(batch_size, -1)
        x = self.fc(x)
        x = self.bn(x)
        if self.l2_normalize:
            x = F.normalize(x)
        return x


# ── Weight loading ────────────────────────────────────────────────────────────


def _get_project_root() -> Path:
    """Find the project root by walking up from this file to pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("Could not find project root (pyproject.toml)")


def get_model_dir() -> Path:
    """Return the ISC model directory (models/isc/ at project root)."""
    model_dir = _get_project_root() / "models" / "isc"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def is_model_downloaded() -> bool:
    """Check if stripped ISC weights exist in models/isc/."""
    return (get_model_dir() / _WEIGHTS_FILENAME).is_file()


def create_isc_model(
    device: str = "cuda",
    model_dir: str | None = None,
    log=None,
) -> tuple[ISCNet, None]:
    """Create and return the ISC model.

    Loads weights from ``models/isc/`` in the project. Weights must be
    downloaded first via setup_gui.py (Models tab).

    Args:
        device: torch device string ("cuda" or "cpu").
        model_dir: Unused, kept for API compatibility.
        log: Optional log callback ``(str) -> None``.

    Returns:
        Tuple of ``(model, None)``.  The second element was formerly a
        torchvision preprocessor but preprocessing is handled directly
        in ``neural_matcher._frame_to_tensor`` so it is always ``None``.
    """
    if log:
        log("[NeuralVerified] Loading ISC model...")

    try:
        import timm
    except ImportError:
        if log:
            log("[NeuralVerified] ERROR: timm not installed")
            log("[NeuralVerified] Install with: pip install timm")
        raise

    # Locate weights
    weights_path = get_model_dir() / _WEIGHTS_FILENAME
    if not weights_path.is_file():
        msg = (
            f"ISC weights not found at: {weights_path}\n"
            "Run setup_gui.py and use the Models tab to download ISC weights."
        )
        if log:
            log(f"[NeuralVerified] ERROR: {msg}")
        raise FileNotFoundError(msg)

    if log:
        log(f"[NeuralVerified] Weights: {weights_path}")

    # Load checkpoint
    ckpt = torch.load(str(weights_path), map_location="cpu", weights_only=False)
    arch = ckpt["arch"]

    # Create backbone
    backbone = timm.create_model(arch, features_only=True)

    # Build model
    model = ISCNet(
        backbone=backbone,
        fc_dim=256,
        p=1.0,
        eval_p=1.0,
        l2_normalize=True,
    )

    # Load weights
    model.load_state_dict(ckpt["state_dict"])
    model.to(device).eval()

    if log:
        n_params = sum(p.numel() for p in model.parameters())
        log(f"[NeuralVerified] ISC model loaded ({n_params/1e6:.1f}M params, {device})")

    return model, None
