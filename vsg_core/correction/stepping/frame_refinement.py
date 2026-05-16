"""
Frame-precision EDL refinement for stepping correction.

After silence/scene boundary refinement produces splice points, this
module:

1. Confirms the BEFORE/AFTER per-segment delay offsets at each
   transition via window-averaged pHash matching (same approach as the
   video-verified sliding matcher, but localized to each transition
   zone with the audio-implied offset as the search center).
2. Walks the dead zone between anchors with strict BEFORE/AFTER
   classification to find the exact src2 "first-AFTER" frame — the
   frame where post-seam content begins matching at the AFTER offset.
3. Validates that the video-derived time is inside the audio silence
   zone the boundary refiner chose. If yes, replaces the splice point's
   ``src2_time_s`` with the video-derived value (frame-precise). If no,
   keeps the audio-derived value and tags the result as a fallback.

Stepping is fundamentally a VIDEO phenomenon — one source has extra
frames inserted relative to the other. The seam location is therefore
something the VIDEO knows exactly. Audio silence detection is used as
a safety check ("can we splice 42 ms of silence here without cutting
into dialogue?"), not as the source of truth for WHERE to splice. This
module makes that division explicit.

Gates (any failure → skip refinement, keep audio's splice point):
* ``settings.stepping_frame_refinement_enabled`` is True
* Both source 1 and source 2 ``content_type == "progressive"``
* Neither codec is mpeg1/mpeg2
* Source FPS within 0.1% of each other
* VapourSynth + the pHash backend are importable at runtime

When gated out, the audio-derived splice points pass through unchanged
and stepping correction behaves identically to before this module
existed. This is the design goal — refinement is purely additive.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from .types import FrameRefinementResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy as np

    from ...models.settings import AppSettings
    from .types import SplicePoint


# Anchor / search params — empirically validated on 91 Days + Akudama.
# Not exposed as settings yet; defaults proven to work and tunables would
# add config-surface complexity without obvious benefit.
ANCHOR_WIDTH_S = 5.0  # length of each BEFORE/AFTER anchor window
ANCHOR_GAP_S = 3.0  # gap between anchor and silence-edit point
SLIDE_RANGE_FRAMES = 60  # ±60-frame search around audio-implied offset
MATCH_THRESHOLD = 0.85  # cosine sim required for "strong match"
REJECT_THRESHOLD = 0.55  # cosine sim below which the offset is rejected
MIN_ANCHOR_SCORE = 0.85  # anchor score required to trust the offset
FPS_TOLERANCE_PCT = 0.1  # source FPS must match within this percentage
HASH_SIZE = 32  # pHash descriptor: 32x32 = 1024-bit


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _is_progressive_pair(
    src1_props: dict[str, Any] | None,
    src2_props: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Return ``(ok, reason)`` describing whether the source pair is
    eligible for frame refinement.
    """
    if not src1_props or not src2_props:
        return False, "video properties not available"

    s1_codec = (src1_props.get("codec_name") or "").lower()
    s2_codec = (src2_props.get("codec_name") or "").lower()
    if s1_codec in ("mpeg2video", "mpeg1video") or s2_codec in (
        "mpeg2video",
        "mpeg1video",
    ):
        return False, f"MPEG-2 source (s1={s1_codec}, s2={s2_codec})"

    s1_ct = (src1_props.get("content_type") or "").lower()
    s2_ct = (src2_props.get("content_type") or "").lower()
    if s1_ct != "progressive" or s2_ct != "progressive":
        return False, f"non-progressive (s1={s1_ct}, s2={s2_ct})"

    s1_fps = float(src1_props.get("fps") or 0)
    s2_fps = float(src2_props.get("fps") or 0)
    if s1_fps <= 0 or s2_fps <= 0:
        return False, "missing fps"
    if abs(s1_fps - s2_fps) / max(s1_fps, s2_fps) > FPS_TOLERANCE_PCT / 100.0:
        return False, f"fps mismatch (s1={s1_fps:.3f}, s2={s2_fps:.3f})"

    return True, ""


# ---------------------------------------------------------------------------
# pHash sliding match (mirrors the existing matcher's window-average logic)
# ---------------------------------------------------------------------------


def _confirm_offset_via_sliding(
    src2_desc: np.ndarray,
    src1_desc: np.ndarray,
) -> tuple[int, float]:
    """Return ``(best_offset_position, best_mean_similarity)``.

    ``src2_desc`` is the per-frame descriptors for the anchor window
    (length S); ``src1_desc`` is the candidate-target window (length T).
    We slide ``src2_desc`` over ``src1_desc`` and at each position
    compute the mean cosine similarity over the paired rows. The
    descriptors are already L2-normalized by the pHash backend, so the
    inner product per row IS the cosine similarity.
    """
    import numpy as _np

    S = len(src2_desc)
    T = len(src1_desc)
    if T < S:
        return 0, 0.0
    best_pos = 0
    best_score = -2.0
    for p in range(T - S + 1):
        sim = float(_np.sum(src2_desc * src1_desc[p : p + S], axis=1).mean())
        if sim > best_score:
            best_score = sim
            best_pos = p
    return best_pos, best_score


def _find_seam_edges(
    sim: np.ndarray,
    *,
    offset_before: int,
    offset_after: int,
    match_threshold: float = MATCH_THRESHOLD,
    reject_threshold: float = REJECT_THRESHOLD,
) -> tuple[int, int]:
    """Identify the last-BEFORE and first-AFTER src2 indices in the
    dead zone via strict classification.

    A src2 row is "strictly BEFORE" iff its match at the BEFORE offset
    is >= ``match_threshold`` AND its match at the AFTER offset is <
    ``reject_threshold``. Symmetric for AFTER. Frames where both offsets
    match strongly (generic content — fades, black) are skipped as
    ambiguous.

    Walk forward to find the first strictly-AFTER index; then walk
    backward from there to find the last strictly-BEFORE index that
    precedes it. Returns ``(-1, -1)`` when none could be identified.
    """
    M, N = sim.shape

    def _s(i: int, j: int) -> float:
        if 0 <= j < N:
            return float(sim[i, j])
        return -1.0

    classifications: list[str] = []
    for i in range(M):
        s_b = _s(i, i + offset_before)
        s_a = _s(i, i + offset_after)
        if s_b >= match_threshold and s_a < reject_threshold:
            classifications.append("before")
        elif s_a >= match_threshold and s_b < reject_threshold:
            classifications.append("after")
        elif max(s_b, s_a) < reject_threshold:
            classifications.append("unmatched")
        else:
            classifications.append("ambiguous")

    first_after = -1
    for i, c in enumerate(classifications):
        if c == "after":
            first_after = i
            break

    last_before = -1
    if first_after >= 0:
        for i in range(first_after - 1, -1, -1):
            if classifications[i] == "before":
                last_before = i
                break
    else:
        for i in range(M - 1, -1, -1):
            if classifications[i] == "before":
                last_before = i
                break

    return last_before, first_after


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def refine_splice_points(
    splice_points: list[SplicePoint],
    *,
    src1_video_path: str | None,
    src2_video_path: str | None,
    src1_props: dict[str, Any] | None,
    src2_props: dict[str, Any] | None,
    settings: AppSettings,
    temp_dir: Path | None,
    log: Callable[[str], None],
) -> list[SplicePoint]:
    """Refine each splice point's src2 time to the exact first-AFTER
    video frame, when content + fps gates permit it. Splice points
    whose refinement was skipped or fell back are returned unchanged
    (with a ``FrameRefinementResult`` attached for audit).

    This function NEVER raises on per-transition failures — every
    branch returns a SplicePoint with appropriate metadata so the
    caller can blindly use the result.
    """
    if not getattr(settings, "stepping_frame_refinement_enabled", True):
        return _stamp_all(splice_points, mode="skipped_disabled", reason="setting off")

    if not src1_video_path or not src2_video_path:
        return _stamp_all(
            splice_points, mode="skipped_no_video", reason="missing source video path"
        )

    ok, reason = _is_progressive_pair(src1_props, src2_props)
    if not ok:
        log(f"[FrameRefine] gated — {reason}")
        return _stamp_all(splice_points, mode="skipped_gate", reason=reason)

    # Lazy heavy imports — only loaded when we actually plan to refine.
    try:
        import torch
        import vapoursynth as vs

        from ...models.settings import AppSettings as _AppSettings
        from ...subtitles.sync_mode_plugins.video_verified.backends.phash import (
            PHashBackend,
        )
        from ...subtitles.sync_mode_plugins.video_verified.sliding_core import (
            open_clip,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        log(f"[FrameRefine] gated — import failed ({exc})")
        return _stamp_all(
            splice_points, mode="skipped_no_video", reason=f"import failed: {exc}"
        )

    fps = float(src2_props.get("fps") if src2_props else 0)  # type: ignore[arg-type]
    if fps <= 0:
        return _stamp_all(splice_points, mode="skipped_gate", reason="bad fps")
    period_ms = 1000.0 / fps

    # Bring up pHash + VS clips once for the whole batch.
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    backend_settings = _AppSettings()
    backend_settings.video_verified_hash_size = HASH_SIZE
    backend = PHashBackend()
    backend.load(device, backend_settings)

    try:
        _, src1_rgb, _ = open_clip(src1_video_path, vs, temp_dir)
        _, src2_rgb, _ = open_clip(src2_video_path, vs, temp_dir)
    except Exception as exc:  # pragma: no cover
        log(f"[FrameRefine] failed to open clips ({exc}) — skipping all transitions")
        return _stamp_all(
            splice_points, mode="skipped_no_video", reason=f"open_clip failed: {exc}"
        )

    refined: list[SplicePoint] = []
    for idx, sp in enumerate(splice_points):
        refined_sp = _refine_one(
            sp,
            idx=idx,
            backend=backend,
            device=device,
            src1_rgb=src1_rgb,
            src2_rgb=src2_rgb,
            fps=fps,
            period_ms=period_ms,
            log=log,
        )
        refined.append(refined_sp)

    return refined


def _refine_one(
    sp: SplicePoint,
    *,
    idx: int,
    backend,
    device,
    src1_rgb,
    src2_rgb,
    fps: float,
    period_ms: float,
    log: Callable[[str], None],
) -> SplicePoint:
    """Refine a single splice point. Always returns a SplicePoint
    (refined or with fallback metadata)."""
    name = f"T{idx + 1}"
    audio_src2_t = sp.src2_time_s
    audio_jump_f = int(round(sp.correction_ms / period_ms))

    src2_silence_frame = int(audio_src2_t * fps)
    anchor_frames = int(ANCHOR_WIDTH_S * fps)
    gap_frames = int(ANCHOR_GAP_S * fps)

    b_end = src2_silence_frame - gap_frames
    b_start = b_end - anchor_frames + 1
    if b_start < 0:
        return _annotate_unchanged(
            sp,
            mode="skipped_gate",
            reason="BEFORE anchor below frame 0",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
        )

    a_start = src2_silence_frame + gap_frames
    a_end = a_start + anchor_frames - 1
    if a_end >= src2_rgb.num_frames:
        return _annotate_unchanged(
            sp,
            mode="skipped_gate",
            reason="AFTER anchor past clip end",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
        )

    # --- BEFORE anchor ---
    dly_b_f = int(round(sp.delay_before_ms / period_ms))
    src1_b_lo = b_start + dly_b_f - SLIDE_RANGE_FRAMES
    src1_b_hi = b_start + dly_b_f + anchor_frames + SLIDE_RANGE_FRAMES
    src1_b_lo = max(0, src1_b_lo)
    src1_b_hi = min(src1_rgb.num_frames - 1, src1_b_hi)
    if src1_b_hi < src1_b_lo + anchor_frames:
        return _annotate_unchanged(
            sp,
            mode="skipped_gate",
            reason="BEFORE src1 window too small",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
        )

    src2_b = list(range(b_start, b_end + 1))
    src1_b = list(range(src1_b_lo, src1_b_hi + 1))
    s2_b_desc = backend._extract_descriptors(src2_rgb, src2_b, device, 32)
    s1_b_desc = backend._extract_descriptors(src1_rgb, src1_b, device, 32)
    bp, b_score = _confirm_offset_via_sliding(s2_b_desc, s1_b_desc)
    abs_off_before = (src1_b[0] + bp) - b_start

    # --- AFTER anchor ---
    dly_a_f = int(round(sp.delay_after_ms / period_ms))
    src1_a_lo = a_start + dly_a_f - SLIDE_RANGE_FRAMES
    src1_a_hi = a_start + dly_a_f + anchor_frames + SLIDE_RANGE_FRAMES
    src1_a_lo = max(0, src1_a_lo)
    src1_a_hi = min(src1_rgb.num_frames - 1, src1_a_hi)
    if src1_a_hi < src1_a_lo + anchor_frames:
        return _annotate_unchanged(
            sp,
            mode="skipped_gate",
            reason="AFTER src1 window too small",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
        )

    src2_a = list(range(a_start, a_end + 1))
    src1_a = list(range(src1_a_lo, src1_a_hi + 1))
    s2_a_desc = backend._extract_descriptors(src2_rgb, src2_a, device, 32)
    s1_a_desc = backend._extract_descriptors(src1_rgb, src1_a, device, 32)
    ap, a_score = _confirm_offset_via_sliding(s2_a_desc, s1_a_desc)
    abs_off_after = (src1_a[0] + ap) - a_start

    measured_jump = abs_off_after - abs_off_before

    log(
        f"[FrameRefine] {name} @ src2_t={audio_src2_t:.3f}s — "
        f"BEFORE +{abs_off_before:+d}f (score {b_score:.3f}), "
        f"AFTER +{abs_off_after:+d}f (score {a_score:.3f}), "
        f"jump {measured_jump:+d}f (audio {audio_jump_f:+d}f)"
    )

    # Confidence gate
    if min(b_score, a_score) < MIN_ANCHOR_SCORE:
        return _annotate_unchanged(
            sp,
            mode="skipped_low_confidence",
            reason=(
                f"anchor score < {MIN_ANCHOR_SCORE} "
                f"(BEFORE {b_score:.2f}, AFTER {a_score:.2f})"
            ),
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
            before_off=abs_off_before,
            after_off=abs_off_after,
            before_score=b_score,
            after_score=a_score,
            measured_jump=measured_jump,
        )

    # Jump sanity check — measured jump should equal audio's expected
    # jump within tolerance. A 1-frame mismatch suggests sub-frame
    # alignment drift; >1 frame mismatch suggests something is wrong
    # with the audio or video analysis.
    if abs(measured_jump - audio_jump_f) > 1:
        return _annotate_unchanged(
            sp,
            mode="skipped_jump_mismatch",
            reason=(
                f"jump {measured_jump:+d}f vs audio +{audio_jump_f:+d}f "
                f"(difference > 1 frame)"
            ),
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
            before_off=abs_off_before,
            after_off=abs_off_after,
            before_score=b_score,
            after_score=a_score,
            measured_jump=measured_jump,
        )

    # --- Dead zone seam search ---
    dead_start = b_end + 1
    dead_end = a_start - 1
    if dead_end <= dead_start:
        return _annotate_unchanged(
            sp,
            mode="skipped_gate",
            reason="dead zone too small",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
            before_off=abs_off_before,
            after_off=abs_off_after,
            before_score=b_score,
            after_score=a_score,
            measured_jump=measured_jump,
        )

    src2_dead = list(range(dead_start, dead_end + 1))
    src1_dead_lo = max(0, dead_start + min(abs_off_before, abs_off_after) - 5)
    src1_dead_hi = min(
        src1_rgb.num_frames - 1, dead_end + max(abs_off_before, abs_off_after) + 5
    )
    src1_dead = list(range(src1_dead_lo, src1_dead_hi + 1))
    s2_dd = backend._extract_descriptors(src2_rgb, src2_dead, device, 32)
    s1_dd = backend._extract_descriptors(src1_rgb, src1_dead, device, 32)
    sim_dead = s2_dd @ s1_dd.T
    rel_off_b = (dead_start + abs_off_before) - src1_dead[0]
    rel_off_a = (dead_start + abs_off_after) - src1_dead[0]
    lb_rel, fa_rel = _find_seam_edges(
        sim_dead, offset_before=rel_off_b, offset_after=rel_off_a
    )

    if fa_rel < 0:
        return _annotate_unchanged(
            sp,
            mode="fallback_no_first_after",
            reason="could not identify first-AFTER frame in dead zone",
            audio_src2_t=audio_src2_t,
            fps=fps,
            expected_jump=audio_jump_f,
            before_off=abs_off_before,
            after_off=abs_off_after,
            before_score=b_score,
            after_score=a_score,
            measured_jump=measured_jump,
        )

    first_after_frame = dead_start + fa_rel
    last_before_frame = (dead_start + lb_rel) if lb_rel >= 0 else None
    video_src2_t = first_after_frame / fps

    # --- Safety: video-derived splice must be inside the silence zone
    # the boundary refiner picked for this transition. ---
    silence = sp.silence_zone
    if silence is not None:
        if not (silence.start_s <= video_src2_t <= silence.end_s):
            return _annotate_unchanged(
                sp,
                mode="fallback_outside_silence",
                reason=(
                    f"video frame {first_after_frame} (t={video_src2_t:.3f}s) "
                    f"lies outside silence zone "
                    f"[{silence.start_s:.3f}, {silence.end_s:.3f}]"
                ),
                audio_src2_t=audio_src2_t,
                fps=fps,
                expected_jump=audio_jump_f,
                before_off=abs_off_before,
                after_off=abs_off_after,
                before_score=b_score,
                after_score=a_score,
                measured_jump=measured_jump,
                first_after=first_after_frame,
                last_before=last_before_frame,
            )

    # All gates passed — refine the splice point to video-derived time.
    frame_drift_ms = (video_src2_t - audio_src2_t) * 1000.0
    fr = FrameRefinementResult(
        mode="refined",
        reason="",
        before_anchor_offset_frames=abs_off_before,
        after_anchor_offset_frames=abs_off_after,
        before_anchor_score=b_score,
        after_anchor_score=a_score,
        audio_expected_jump_frames=audio_jump_f,
        measured_jump_frames=measured_jump,
        jump_confirmed=True,
        last_before_frame=last_before_frame,
        first_after_frame=first_after_frame,
        audio_src2_time_s=audio_src2_t,
        video_src2_time_s=video_src2_t,
        frame_drift_ms=frame_drift_ms,
        target_fps=fps,
    )
    log(
        f"[FrameRefine] {name} → refined splice src2_time: "
        f"{audio_src2_t:.3f}s → {video_src2_t:.3f}s "
        f"(drift {frame_drift_ms:+.1f} ms, first-AFTER frame {first_after_frame})"
    )
    return replace(sp, src2_time_s=video_src2_t, frame_refinement=fr)


# ---------------------------------------------------------------------------
# Helpers — stamping results on splice points without changing their times
# ---------------------------------------------------------------------------


def _stamp_all(
    splice_points: list[SplicePoint], *, mode: str, reason: str
) -> list[SplicePoint]:
    """Attach a uniform 'no-op' FrameRefinementResult to every splice point."""
    out: list[SplicePoint] = []
    for sp in splice_points:
        fr = FrameRefinementResult(
            mode=mode,
            reason=reason,
            audio_src2_time_s=sp.src2_time_s,
        )
        out.append(replace(sp, frame_refinement=fr))
    return out


def _annotate_unchanged(
    sp: SplicePoint,
    *,
    mode: str,
    reason: str,
    audio_src2_t: float,
    fps: float,
    expected_jump: int | None,
    before_off: int | None = None,
    after_off: int | None = None,
    before_score: float = 0.0,
    after_score: float = 0.0,
    measured_jump: int | None = None,
    first_after: int | None = None,
    last_before: int | None = None,
) -> SplicePoint:
    """Return ``sp`` unchanged but with a populated FrameRefinementResult."""
    fr = FrameRefinementResult(
        mode=mode,
        reason=reason,
        before_anchor_offset_frames=before_off,
        after_anchor_offset_frames=after_off,
        before_anchor_score=before_score,
        after_anchor_score=after_score,
        audio_expected_jump_frames=expected_jump,
        measured_jump_frames=measured_jump,
        jump_confirmed=bool(
            measured_jump is not None
            and expected_jump is not None
            and abs(measured_jump - expected_jump) <= 1
        ),
        last_before_frame=last_before,
        first_after_frame=first_after,
        audio_src2_time_s=audio_src2_t,
        video_src2_time_s=None,
        frame_drift_ms=0.0,
        target_fps=fps,
    )
    return replace(sp, frame_refinement=fr)
