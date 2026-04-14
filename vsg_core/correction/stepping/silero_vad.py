# vsg_core/correction/stepping/silero_vad.py
"""
Silero VAD v6.2 model management and inference.

Downloads the TorchScript model on first use and provides speech region
detection.  No pip dependency — uses ``torch.jit.load()`` directly.

The model file is stored under ``{project_root}/models/silero_vad/``,
following the same layout as the video-verified backends.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np  # noqa: TC002 — used at runtime in detect_speech_regions

if TYPE_CHECKING:
    from collections.abc import Callable

# Pinned to v6.2.1 for stability
_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/"
    "v6.2.1/src/silero_vad/data/silero_vad.jit"
)
_MODEL_FILENAME = "silero_vad.jit"
_MODEL_SUBDIR = "silero_vad"
_EXPECTED_SIZE_MIN = 2_000_000  # ~2.2 MB, reject obviously corrupt files


# ---------------------------------------------------------------------------
# Model directory
# ---------------------------------------------------------------------------


def _get_model_dir() -> Path:
    """Return ``{project_root}/models/silero_vad/``, creating if needed."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            model_dir = parent / "models" / _MODEL_SUBDIR
            model_dir.mkdir(parents=True, exist_ok=True)
            return model_dir
    raise FileNotFoundError("Could not find project root (pyproject.toml)")


def get_silero_model_path() -> Path:
    """Return the expected path to ``silero_vad.jit``."""
    return _get_model_dir() / _MODEL_FILENAME


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def ensure_silero_model(
    log: Callable[[str], None] | None = None,
) -> Path:
    """Download the Silero VAD model if it is not already present.

    Returns the path to the ``.jit`` file.  Raises on download failure.
    """
    model_path = get_silero_model_path()

    if model_path.is_file() and model_path.stat().st_size >= _EXPECTED_SIZE_MIN:
        return model_path

    if log:
        log(f"[Silero VAD] Downloading model to {model_path} ...")

    request = Request(_MODEL_URL, headers={"User-Agent": "Video-Sync-GUI/1.0"})

    try:
        with urlopen(request, timeout=60) as response:
            fd, tmp_path = tempfile.mkstemp(suffix=".jit.tmp", dir=model_path.parent)
            try:
                downloaded = 0
                with os.fdopen(fd, "wb") as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                if downloaded < _EXPECTED_SIZE_MIN:
                    raise RuntimeError(
                        f"Download too small ({downloaded} bytes), "
                        f"expected >= {_EXPECTED_SIZE_MIN}"
                    )

                shutil.move(tmp_path, model_path)
            except Exception:
                # Clean up partial download
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
    except (HTTPError, URLError, OSError) as exc:
        raise RuntimeError(
            f"Failed to download Silero VAD model from {_MODEL_URL}: {exc}"
        ) from exc

    if log:
        log(f"[Silero VAD] Model downloaded ({model_path.stat().st_size} bytes)")

    return model_path


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def detect_speech_regions(
    pcm_mono: np.ndarray,
    sample_rate: int,
    model_path: Path | str,
    threshold: float = 0.5,
    min_speech_ms: float = 50.0,
    min_silence_ms: float = 50.0,
) -> list[tuple[float, float]]:
    """Detect speech regions in mono audio using the Silero VAD model.

    Parameters
    ----------
    pcm_mono:
        Mono float32 audio (any sample rate — resampled to 16 kHz internally
        if needed).
    sample_rate:
        Sample rate of *pcm_mono*.
    model_path:
        Path to ``silero_vad.jit``.
    threshold:
        Speech probability threshold (default 0.5).
    min_speech_ms:
        Minimum speech region duration to emit.
    min_silence_ms:
        Minimum silence gap to split speech regions.

    Returns
    -------
    list[tuple[float, float]]
        ``(start_s, end_s)`` pairs of detected speech regions.
    """
    import torch

    model = torch.jit.load(str(model_path))
    model.eval()

    # Silero VAD expects 16 kHz mono
    target_sr = 16000
    if sample_rate != target_sr:
        step = max(1, sample_rate // target_sr)
        pcm_16k = pcm_mono[::step]
    else:
        pcm_16k = pcm_mono

    audio = torch.from_numpy(pcm_16k.copy()).float()

    # Process in 512-sample chunks (32ms at 16kHz)
    chunk_size = 512
    chunk_duration_s = chunk_size / target_sr

    model.reset_states()

    speech_frames: list[tuple[float, bool]] = []

    with torch.no_grad():
        for i in range(0, len(audio) - chunk_size, chunk_size):
            chunk = audio[i : i + chunk_size]
            prob = model(chunk, target_sr).item()
            t = i / target_sr
            speech_frames.append((t, prob >= threshold))

    # Group consecutive speech frames into regions
    regions: list[tuple[float, float]] = []
    in_speech = False
    speech_start = 0.0

    for t, is_speech in speech_frames:
        if is_speech and not in_speech:
            speech_start = t
            in_speech = True
        elif not is_speech and in_speech:
            speech_end = t + chunk_duration_s
            dur_ms = (speech_end - speech_start) * 1000
            if dur_ms >= min_speech_ms:
                regions.append((speech_start, speech_end))
            in_speech = False

    # Close trailing speech
    if in_speech:
        speech_end = len(audio) / target_sr
        dur_ms = (speech_end - speech_start) * 1000
        if dur_ms >= min_speech_ms:
            regions.append((speech_start, speech_end))

    # Merge regions with small gaps
    merged: list[tuple[float, float]] = []
    for start, end in regions:
        if merged and (start - merged[-1][1]) * 1000 < min_silence_ms:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    return merged


def is_speech_at(
    time_s: float,
    speech_regions: list[tuple[float, float]],
) -> bool:
    """Check whether *time_s* falls inside a speech region."""
    return any(start <= time_s <= end for start, end in speech_regions)
