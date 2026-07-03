# vsg_core/subtitles/sync_mode_plugins/video_verified/sliding_core.py
"""Shared helpers for the sliding-window video-verified matcher.

This module owns the code that is common to every backend:

- ``_open_clip`` — opens a video via VapourSynth + FFMS2 with PTS-aware
  metadata on frame 0 (for the PTS correction bugfix).
- ``frame_abs_time_s`` / ``probe_timeline_integrity`` — real per-frame
  container timestamps and gap detection (frame-index vs wall-clock
  divergence, e.g. sources with dropped frame slots).
- ``_get_project_root`` / ``get_backend_model_dir`` — filesystem layout for
  backend weights. Used by ``backends.isc``, ``backends.sscd_*`` to find
  their model files.
- ``cosine_slide`` — canonical feature-based sliding score loop, shared
  by all feature backends (ISC, SSCD, pHash, dHash).
- ``compute_gradient`` — per-frame score drop-off around the peak.

The orchestrator in ``sliding_matcher.py`` (Phase 3) uses these helpers
and is backend-agnostic. Backends in ``backends/*.py`` call
``cosine_slide`` after extracting their per-frame descriptors; the SSIM
backend uses a different path entirely because it's pairwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable


# ── Project layout ────────────────────────────────────────────────────────────


def _get_project_root() -> Path:
    """Walk up from this file to the directory containing ``pyproject.toml``.

    Used by backends to locate their weights under ``models/{backend_dir}/``.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("Could not find project root (pyproject.toml)")


def get_backend_model_dir(backend_subdir: str) -> Path:
    """Return ``{project_root}/models/{backend_subdir}/``, creating it if needed.

    Examples: ``get_backend_model_dir("isc")`` → ``.../models/isc/``.
    """
    model_dir = _get_project_root() / "models" / backend_subdir
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


# ── Clip I/O with PTS metadata ────────────────────────────────────────────────


def open_clip(video_path: str, vs: Any, temp_dir: Path | None = None):
    """Open a video and return ``(yuv_clip, rgb_clip, start_pts_s)``.

    ``start_pts_s`` is the wall-clock time of frame 0 from the container's
    PTS metadata (``_AbsoluteTime`` property on frame 0 via ffms2). For
    the common case this is 0.0. Some re-encodes and DVD rips preserve a
    non-zero PTS origin from their original source, which causes a
    constant frame-index vs wall-clock offset. The orchestrator subtracts
    the relative delta between source and target start_pts_s so sub
    timing (which is always wall-clock) is preserved.
    """
    from ...frame_utils.video_reader import _get_ffms2_cache_path

    core = vs.core

    cache_path = str(_get_ffms2_cache_path(video_path, temp_dir))

    try:
        clip = core.ffms2.Source(source=video_path, cachefile=cache_path)
    except Exception:
        stale = Path(cache_path)
        if stale.exists():
            stale.unlink(missing_ok=True)
        clip = core.ffms2.Source(source=video_path, cachefile=cache_path)

    rgb_clip = core.resize.Bicubic(clip, format=vs.RGB24, matrix_in_s="170m")

    # Read frame 0's absolute wall-clock time from container PTS metadata.
    # Safe fallback to 0.0 if the property is missing for any reason.
    try:
        start_pts_s = float(clip.get_frame(0).props.get("_AbsoluteTime", 0.0))
    except Exception:
        start_pts_s = 0.0

    return clip, rgb_clip, start_pts_s


def frame_abs_time_s(clip: Any, n: int) -> float | None:
    """Real container timestamp of frame ``n`` in seconds, or ``None``.

    Reads the ffms2 ``_AbsoluteTime`` frame prop. Returns ``None`` when the
    prop is missing or the frame can't be fetched — callers must fall back
    to frame-index math in that case, never guess.
    """
    try:
        t = clip.get_frame(n).props.get("_AbsoluteTime")
        return float(t) if t is not None else None
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class TimelineProbe:
    """Result of checking a clip's frame-index ↔ wall-clock mapping.

    ``ok=None`` means timestamps were unavailable and nothing could be
    verified (distinct from ``ok=True``, which is a positive confirmation).
    """

    ok: bool | None
    num_frames: int
    missing_slots: int  # >0: dropped frame slots (pts gaps); <0: extra frames
    first_divergence_index: int | None  # first frame where index != pts slot
    first_divergence_time_s: float | None  # its wall-clock time

    @property
    def has_gaps(self) -> bool:
        return self.ok is False


def probe_timeline_integrity(
    num_frames: int,
    fps: float,
    start_pts_s: float,
    pts_lookup: Callable[[int], float | None],
) -> TimelineProbe:
    """Check whether frame index ``n`` sits at wall-clock slot ``n``.

    A clean CFR file satisfies ``round((pts(n) - pts(0)) * fps) == n`` for
    every frame. A dropped frame slot (pts gap — e.g. a WEB encode missing
    one frame while keeping the remaining timestamps) breaks this from the
    gap onward, which silently corrupts any ``frame_index * frame_duration``
    arithmetic.

    Cost: 1 pts read for the last frame; plus O(log n) reads to locate the
    first divergence when one exists (divergence index is monotonic because
    later frames inherit the accumulated slot shift).
    """
    if num_frames < 2 or fps <= 0:
        return TimelineProbe(True, num_frames, 0, None, None)

    def slot_of(n: int) -> int | None:
        t = pts_lookup(n)
        if t is None:
            return None
        return round((t - start_pts_s) * fps)

    last_slot = slot_of(num_frames - 1)
    if last_slot is None:
        return TimelineProbe(None, num_frames, 0, None, None)

    missing = last_slot - (num_frames - 1)
    if missing == 0:
        return TimelineProbe(True, num_frames, 0, None, None)

    # Binary search the first frame whose slot diverges from its index.
    lo, hi = 0, num_frames - 1  # slot(lo) == lo (frame 0 by construction)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        mid_slot = slot_of(mid)
        if mid_slot is None:
            # Can't refine further; report what we know.
            break
        if mid_slot == mid:
            lo = mid
        else:
            hi = mid
    first_idx = hi
    first_time = pts_lookup(first_idx)
    return TimelineProbe(False, num_frames, missing, first_idx, first_time)


# ── Feature-based sliding (ISC, SSCD, pHash, dHash share this) ───────────────


def cosine_slide(
    src_feats: np.ndarray,
    tgt_feats: np.ndarray,
    match_threshold: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Slide ``src_feats`` across ``tgt_feats`` and return per-slide scores.

    Both arrays are shape ``[N, D]``. Each row is a per-frame descriptor.
    The function L2-normalizes both (idempotent if already normalized),
    then at every valid slide position computes mean cosine similarity
    across the paired rows.

    Returns
    -------
    scores : np.ndarray, shape ``[T-S+1]``
        Mean cosine similarity per slide position.
    match_counts : np.ndarray, shape ``[T-S+1]``
        Number of pair similarities above ``match_threshold``. Included
        for parity with the existing debug log format.

    For a source window of length ``S`` and target window of length
    ``T``, the number of slide positions is ``T - S + 1``. Returns
    empty arrays if the target is shorter than the source.
    """
    S = len(src_feats)
    T = len(tgt_feats)
    max_slides = T - S + 1
    if max_slides <= 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.int64)

    # L2 normalize (safe if already normalized — norm becomes 1.0)
    src_norm = src_feats / (np.linalg.norm(src_feats, axis=1, keepdims=True) + 1e-8)
    tgt_norm = tgt_feats / (np.linalg.norm(tgt_feats, axis=1, keepdims=True) + 1e-8)

    scores = np.zeros(max_slides, dtype=np.float64)
    match_counts = np.zeros(max_slides, dtype=np.int64)
    for p in range(max_slides):
        pair_sims = np.sum(src_norm * tgt_norm[p : p + S], axis=1)
        scores[p] = pair_sims.mean()
        match_counts[p] = int(np.sum(pair_sims > match_threshold))

    return scores, match_counts


# ── Peak sharpness metric ─────────────────────────────────────────────────────


def compute_gradient(scores: np.ndarray, best_pos: int) -> float:
    """Mean score drop-off per frame within ±5 frames of the peak.

    Higher = sharper peak = more confident alignment. Used by the
    orchestrator for confidence assessment and debug reporting.
    """
    if len(scores) < 3:
        return 0.0

    peak_score = scores[best_pos]
    gradients: list[float] = []

    for delta in range(1, 6):
        for sign in (-1, 1):
            pos = best_pos + sign * delta
            if 0 <= pos < len(scores):
                drop = peak_score - scores[pos]
                gradients.append(drop / delta)

    return float(np.mean(gradients)) if gradients else 0.0
