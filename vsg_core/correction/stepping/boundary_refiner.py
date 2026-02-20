# vsg_core/correction/stepping/boundary_refiner.py
"""
Find precise splice points at transition boundaries.

For each transition zone the EDL builder identified, this module:
  1. Converts to Source 2 timeline (correct subtract convention)
  2. Searches Source 2 PCM for silence (RMS + VAD combined)
  3. Detects transients (drum hits, impacts) to avoid them
  4. Snaps to the CENTER of the best silence zone
  5. Nudges to nearest zero-crossing to prevent clicks
  6. Optionally aligns to a video keyframe
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from . import timeline
from .types import BoundaryResult, SilenceZone, SplicePoint, TransitionZone

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...models.settings import AppSettings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def refine_boundaries(
    transition_zones: list[TransitionZone],
    src2_pcm: np.ndarray,
    src2_sr: int,
    settings: AppSettings,
    log: Callable[[str], None],
    ref_video_path: str | None = None,
    tool_paths: dict[str, str | None] | None = None,
    runner: object | None = None,
) -> list[SplicePoint]:
    """For each transition zone, find the best splice point in Source 2 audio.

    Parameters
    ----------
    src2_pcm : np.ndarray
        Mono int32 PCM of Source 2 (the target / analysis track).
    src2_sr : int
        Sample rate of src2_pcm.
    """
    splice_points: list[SplicePoint] = []

    for i, zone in enumerate(transition_zones):
        log(
            f"  [Boundary {i + 1}] Refining transition "
            f"(correction {zone.correction_ms:+.0f}ms)..."
        )

        # Midpoint of the transition zone in ref timeline
        ref_mid = (zone.ref_start_s + zone.ref_end_s) / 2.0
        # Convert to Source 2 timeline using delay BEFORE the transition
        src2_mid = timeline.ref_to_src2(ref_mid, zone.delay_before_ms)

        search_window_s = settings.stepping_silence_search_window_s
        search_start = max(0.0, src2_mid - search_window_s)
        search_end = src2_mid + search_window_s

        log(
            f"    Ref midpoint: {ref_mid:.2f}s → "
            f"Src2 search: [{search_start:.2f}s - {search_end:.2f}s]"
        )

        # --- Find silence zones ---
        boundary = _find_best_silence(
            src2_pcm,
            src2_sr,
            search_start,
            search_end,
            src2_mid,
            settings,
            log,
        )
        best_zone = boundary.zone

        # Determine splice time
        if best_zone is not None:
            splice_src2 = best_zone.center_s
            log(
                f"    Splice: {splice_src2:.3f}s  "
                f"(silence {best_zone.duration_ms:.0f}ms @ {best_zone.avg_db:.1f}dB, "
                f"source={best_zone.source}, score={boundary.score:.1f})"
            )
        else:
            splice_src2 = src2_mid
            log(f"    ⚠  No silence found — using raw midpoint {splice_src2:.3f}s")

        # --- Zero-crossing snap (prevents waveform discontinuity clicks) ---
        pre_zc = splice_src2
        splice_src2 = _snap_to_zero_crossing(src2_pcm, src2_sr, splice_src2)
        if splice_src2 != pre_zc:
            log(
                f"    Zero-crossing snap: {pre_zc:.4f}s -> {splice_src2:.4f}s "
                f"(shift {(splice_src2 - pre_zc) * 1000:.2f}ms)"
            )

        # --- Optional video snap ---
        snap_meta: dict[str, object] = {}
        if (
            settings.stepping_snap_to_video_frames
            and ref_video_path
            and tool_paths
            and runner is not None
        ):
            splice_ref = timeline.src2_to_ref(splice_src2, zone.delay_before_ms)
            snapped_ref = _snap_to_video_frame(
                splice_ref, ref_video_path, settings, tool_paths, runner, log
            )
            if snapped_ref is not None and snapped_ref != splice_ref:
                # Ensure the snapped position is still within (or near) the
                # silence zone so we don't create a click.
                snapped_src2 = timeline.ref_to_src2(snapped_ref, zone.delay_before_ms)
                if best_zone is not None:
                    if best_zone.start_s <= snapped_src2 <= best_zone.end_s:
                        splice_src2 = snapped_src2
                        snap_meta["video_snapped"] = True
                        snap_meta["video_snap_offset_s"] = snapped_ref - splice_ref
                        log(
                            f"    Video snap: {splice_ref:.3f}s → {snapped_ref:.3f}s "
                            "(within silence zone)"
                        )
                    else:
                        log(
                            f"    Video snap rejected: {snapped_src2:.3f}s "
                            "falls outside silence zone"
                        )

        splice_ref_final = timeline.src2_to_ref(splice_src2, zone.delay_before_ms)
        splice_points.append(
            SplicePoint(
                ref_time_s=splice_ref_final,
                src2_time_s=splice_src2,
                delay_before_ms=zone.delay_before_ms,
                delay_after_ms=zone.delay_after_ms,
                correction_ms=zone.correction_ms,
                silence_zone=best_zone,
                boundary_result=boundary,
                snap_metadata=snap_meta,
            )
        )

    return splice_points


# ---------------------------------------------------------------------------
# Combined silence finder
# ---------------------------------------------------------------------------


def _find_best_silence(
    pcm: np.ndarray,
    sr: int,
    start_s: float,
    end_s: float,
    target_s: float,
    settings: AppSettings,
    log: Callable[[str], None],
) -> BoundaryResult:
    """Find the best splice-worthy silence zone near *target_s*.

    Combines RMS energy detection, WebRTC VAD, and transient avoidance.
    The intersection of "RMS quiet" + "VAD non-speech" gives the safest
    splice candidates.  Falls back to RMS-only or VAD-only if the
    intersection is empty.

    Returns a BoundaryResult with the zone, score, and audit flags.
    """
    threshold_db = settings.stepping_silence_threshold_db
    min_duration_ms = settings.stepping_silence_min_duration_ms

    # RMS silence detection
    rms_zones = find_silence_zones_rms(
        pcm, sr, start_s, end_s, threshold_db, min_duration_ms
    )
    log(f"    RMS: {len(rms_zones)} silence zone(s)")

    # VAD non-speech gap detection
    vad_gaps: list[SilenceZone] = []
    if settings.stepping_vad_enabled:
        vad_gaps = find_vad_gaps(
            pcm,
            sr,
            start_s,
            end_s,
            settings.stepping_vad_aggressiveness,
            min_gap_ms=min_duration_ms,
        )
        log(f"    VAD: {len(vad_gaps)} non-speech gap(s)")

    # Transient detection
    transient_times: list[float] = []
    if settings.stepping_transient_detection_enabled:
        transient_times = detect_transients(
            pcm,
            sr,
            start_s,
            end_s,
            threshold_db=settings.stepping_transient_threshold,
        )
        if transient_times:
            log(f"    Transients: {len(transient_times)} detected")

    # Try intersection first
    combined = _intersect_zones(rms_zones, vad_gaps) if vad_gaps else []
    log(f"    Combined: {len(combined)} overlapping zone(s)")

    # Pick best from combined -> rms -> vad (preference order)
    candidates = combined or rms_zones or vad_gaps
    if not candidates:
        return BoundaryResult(
            zone=None, score=0.0, near_transient=False, overlaps_speech=False
        )

    best_zone, score, near_transient = _pick_best_zone(
        candidates,
        target_s,
        settings,
        log,
        transient_times=transient_times,
    )

    # If VAD was enabled and we fell back to RMS-only (no combined zones),
    # the winning zone likely overlaps speech detected by VAD.
    overlaps_speech = (
        settings.stepping_vad_enabled
        and len(vad_gaps) > 0
        and len(combined) == 0
        and best_zone.source == "rms"
    )

    return BoundaryResult(
        zone=best_zone,
        score=score,
        near_transient=near_transient,
        overlaps_speech=overlaps_speech,
    )


# ---------------------------------------------------------------------------
# RMS silence detection (extracted from old _find_silence_zones)
# ---------------------------------------------------------------------------


def find_silence_zones_rms(
    pcm: np.ndarray,
    sample_rate: int,
    start_s: float,
    end_s: float,
    threshold_db: float,
    min_duration_ms: float,
) -> list[SilenceZone]:
    """Find contiguous quiet regions using RMS energy in 50 ms windows."""
    start_sample = max(0, int(start_s * sample_rate))
    end_sample = min(len(pcm), int(end_s * sample_rate))
    if end_sample <= start_sample:
        return []

    window_size = max(1, int(0.05 * sample_rate))
    min_silence_samples = int((min_duration_ms / 1000.0) * sample_rate)

    zones: list[SilenceZone] = []
    run_start: float | None = None
    run_dbs: list[float] = []

    for pos in range(start_sample, end_sample - window_size, window_size):
        window = pcm[pos : pos + window_size]
        if len(window) == 0:
            continue

        rms = np.sqrt(np.mean(window.astype(np.float64) ** 2))
        db = 20.0 * np.log10(rms / 2147483648.0) if rms > 1e-10 else -96.0

        if db < threshold_db:
            if run_start is None:
                run_start = pos / sample_rate
                run_dbs = [db]
            else:
                run_dbs.append(db)
        elif run_start is not None:
            _maybe_emit_zone(
                zones,
                run_start,
                pos / sample_rate,
                run_dbs,
                min_silence_samples,
                sample_rate,
                "rms",
            )
            run_start = None
            run_dbs = []

    if run_start is not None:
        _maybe_emit_zone(
            zones,
            run_start,
            end_sample / sample_rate,
            run_dbs,
            min_silence_samples,
            sample_rate,
            "rms",
        )

    return zones


# ---------------------------------------------------------------------------
# VAD non-speech gap detection
# ---------------------------------------------------------------------------


def find_vad_gaps(
    pcm: np.ndarray,
    sample_rate: int,
    start_s: float,
    end_s: float,
    aggressiveness: int = 2,
    min_gap_ms: float = 30.0,
) -> list[SilenceZone]:
    """Find non-speech gaps using WebRTC VAD.

    Returns the *gaps* (regions where VAD says no speech), each tagged
    with the RMS energy measured from the original PCM.
    """
    try:
        import webrtcvad
    except ImportError:
        return []

    vad_sr = 16000 if sample_rate >= 16000 else 8000
    frame_ms = 30
    frame_samples = int(vad_sr * frame_ms / 1000)
    frame_bytes = frame_samples * 2  # int16

    start_sample = max(0, int(start_s * sample_rate))
    end_sample = min(len(pcm), int(end_s * sample_rate))
    segment = pcm[start_sample:end_sample]
    if len(segment) == 0:
        return []

    # Downsample if needed (simple decimation)
    if sample_rate != vad_sr:
        step = sample_rate // vad_sr
        segment = segment[::step]

    # int32 → int16
    audio_int16 = (segment / 65536).astype(np.int16)
    audio_bytes = audio_int16.tobytes()

    vad = webrtcvad.Vad(aggressiveness)

    # Collect per-frame speech decisions
    gap_start: float | None = None
    gaps: list[SilenceZone] = []

    for i in range(0, len(audio_bytes) - frame_bytes, frame_bytes):
        frame = audio_bytes[i : i + frame_bytes]
        t = start_s + (i / 2 / vad_sr)
        is_speech = vad.is_speech(frame, vad_sr)

        if not is_speech:
            if gap_start is None:
                gap_start = t
        elif gap_start is not None:
            gap_end = t
            dur_ms = (gap_end - gap_start) * 1000.0
            if dur_ms >= min_gap_ms:
                avg_db = _rms_db_range(pcm, sample_rate, gap_start, gap_end)
                gaps.append(
                    SilenceZone(
                        start_s=gap_start,
                        end_s=gap_end,
                        center_s=(gap_start + gap_end) / 2.0,
                        avg_db=avg_db,
                        duration_ms=dur_ms,
                        source="vad",
                    )
                )
            gap_start = None

    # Close trailing gap
    if gap_start is not None:
        gap_end = end_s
        dur_ms = (gap_end - gap_start) * 1000.0
        if dur_ms >= min_gap_ms:
            avg_db = _rms_db_range(pcm, sample_rate, gap_start, gap_end)
            gaps.append(
                SilenceZone(
                    start_s=gap_start,
                    end_s=gap_end,
                    center_s=(gap_start + gap_end) / 2.0,
                    avg_db=avg_db,
                    duration_ms=dur_ms,
                    source="vad",
                )
            )

    return gaps


# ---------------------------------------------------------------------------
# Zone intersection + scoring
# ---------------------------------------------------------------------------


def _intersect_zones(
    rms_zones: list[SilenceZone],
    vad_gaps: list[SilenceZone],
) -> list[SilenceZone]:
    """Return the temporal overlaps between RMS zones and VAD gaps."""
    combined: list[SilenceZone] = []
    for rz in rms_zones:
        for vg in vad_gaps:
            ol_start = max(rz.start_s, vg.start_s)
            ol_end = min(rz.end_s, vg.end_s)
            if ol_end > ol_start:
                dur_ms = (ol_end - ol_start) * 1000.0
                combined.append(
                    SilenceZone(
                        start_s=ol_start,
                        end_s=ol_end,
                        center_s=(ol_start + ol_end) / 2.0,
                        avg_db=rz.avg_db,
                        duration_ms=dur_ms,
                        source="combined",
                    )
                )
    return combined


def _pick_best_zone(
    candidates: list[SilenceZone],
    target_s: float,
    settings: AppSettings,
    log: Callable[[str], None],
    transient_times: list[float] | None = None,
) -> tuple[SilenceZone, float, bool]:
    """Pick the best silence zone from *candidates*.

    Scoring:
      - Closeness to *target_s* (most important)
      - Duration (longer is safer)
      - Depth (quieter is better)
      - Transient penalty (zones containing transients score lower)

    Returns:
        (best_zone, score, near_transient) — the winning zone, its composite
        score, and whether transients were detected near it.
    """
    threshold_db = settings.stepping_silence_threshold_db
    search_window = settings.stepping_silence_search_window_s

    weight_silence = settings.stepping_fusion_weight_silence
    weight_duration = settings.stepping_fusion_weight_duration
    transients = transient_times or []

    best: SilenceZone | None = None
    best_score = -float("inf")
    best_near_transient = False

    for zone in candidates:
        distance = abs(zone.center_s - target_s)
        distance_score = max(0.0, (search_window - distance) / search_window) * 5.0
        depth_score = max(0.0, (threshold_db - zone.avg_db) / 10.0) * weight_silence
        dur_score = min(zone.duration_ms / 1000.0, 1.0) * weight_duration

        # Transient penalty: count transients within or near (±50ms) the zone
        transient_penalty = 0.0
        zone_has_transient = False
        if transients:
            margin = 0.05  # 50ms safety margin
            count = sum(
                1
                for t in transients
                if (zone.start_s - margin) <= t <= (zone.end_s + margin)
            )
            zone_has_transient = count > 0
            # Each transient near the zone applies a heavy penalty
            transient_penalty = count * 3.0

        score = distance_score + depth_score + dur_score - transient_penalty

        if score > best_score:
            best_score = score
            best = zone
            best_near_transient = zone_has_transient

    assert best is not None  # candidates is non-empty
    return best, best_score, best_near_transient


# ---------------------------------------------------------------------------
# Transient detection
# ---------------------------------------------------------------------------


def detect_transients(
    pcm: np.ndarray,
    sr: int,
    start_s: float,
    end_s: float,
    threshold_db: float = 8.0,
    window_ms: float = 10.0,
) -> list[float]:
    """Detect transients (sudden amplitude jumps) in a PCM region.

    Scans with small RMS windows and looks for frame-to-frame dB jumps
    that exceed *threshold_db*.  Returns the timestamps (in seconds)
    where transients are detected.

    These are places we do NOT want to splice — drum hits, impacts,
    consonant onsets — because cutting there produces audible clicks.
    """
    start_sample = max(0, int(start_s * sr))
    end_sample = min(len(pcm), int(end_s * sr))
    if end_sample <= start_sample:
        return []

    window_size = max(1, int((window_ms / 1000.0) * sr))
    transients: list[float] = []
    prev_db: float | None = None

    for pos in range(start_sample, end_sample - window_size, window_size):
        window = pcm[pos : pos + window_size]
        if len(window) == 0:
            continue

        rms = np.sqrt(np.mean(window.astype(np.float64) ** 2))
        db = 20.0 * np.log10(rms / 2147483648.0) if rms > 1e-10 else -96.0

        if prev_db is not None:
            jump = db - prev_db  # positive = sudden louder
            if jump >= threshold_db:
                t = pos / sr
                transients.append(t)

        prev_db = db

    return transients


# ---------------------------------------------------------------------------
# Zero-crossing snap
# ---------------------------------------------------------------------------


def _snap_to_zero_crossing(
    pcm: np.ndarray,
    sr: int,
    target_s: float,
    search_radius_ms: float = 2.0,
) -> float:
    """Nudge *target_s* to the nearest zero crossing in the PCM.

    A zero crossing is where the waveform crosses through zero amplitude.
    Splicing at a zero crossing avoids the discontinuity that causes an
    audible click.  Searches ±search_radius_ms around the target.

    Returns the snapped time (seconds), or the original if no crossing
    is found within the radius.
    """
    target_sample = int(target_s * sr)
    radius_samples = max(1, int((search_radius_ms / 1000.0) * sr))

    lo = max(0, target_sample - radius_samples)
    hi = min(len(pcm) - 1, target_sample + radius_samples)
    if hi <= lo:
        return target_s

    segment = pcm[lo : hi + 1].astype(np.float64)
    # Sign changes: where consecutive samples have different signs
    signs = np.sign(segment)
    crossings = np.where(np.diff(signs) != 0)[0]

    if len(crossings) == 0:
        return target_s

    # Find crossing closest to target_sample
    crossing_abs = crossings + lo
    nearest_idx = crossing_abs[np.argmin(np.abs(crossing_abs - target_sample))]
    return nearest_idx / sr


# ---------------------------------------------------------------------------
# Video frame snapping (extracted from old _snap_boundary_to_video_frame)
# ---------------------------------------------------------------------------


def _snap_to_video_frame(
    boundary_ref_s: float,
    video_file: str,
    settings: AppSettings,
    tool_paths: dict[str, str | None],
    runner: object,
    log: Callable[[str], None],
) -> float | None:
    """Try to snap *boundary_ref_s* to a nearby keyframe.

    Returns the snapped position or ``None`` if nothing suitable.
    """
    max_offset = settings.stepping_video_snap_max_offset_s

    # Get keyframe positions via ffprobe
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,flags",
        "-of",
        "json",
        video_file,
    ]

    try:
        result = runner.run(cmd, tool_paths)  # type: ignore[attr-defined]
        if result is None:
            return None
        data = json.loads(result)
        keyframes = [
            float(p["pts_time"])
            for p in data.get("packets", [])
            if "K" in p.get("flags", "") and "pts_time" in p
        ]
    except Exception:
        return None

    if not keyframes:
        return None

    nearest = min(keyframes, key=lambda x: abs(x - boundary_ref_s))
    if abs(nearest - boundary_ref_s) <= max_offset:
        return nearest
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rms_db_range(pcm: np.ndarray, sr: int, start_s: float, end_s: float) -> float:
    """Compute RMS dB for a time range in int32 PCM."""
    s = max(0, int(start_s * sr))
    e = min(len(pcm), int(end_s * sr))
    if e <= s:
        return -96.0
    segment = pcm[s:e].astype(np.float64)
    rms = np.sqrt(np.mean(segment * segment))
    return 20.0 * np.log10(rms / 2147483648.0) if rms > 1e-10 else -96.0


def _maybe_emit_zone(
    zones: list[SilenceZone],
    run_start: float,
    run_end: float,
    run_dbs: list[float],
    min_silence_samples: int,
    sample_rate: int,
    source: str,
) -> None:
    """Append a SilenceZone if it meets the minimum duration."""
    dur_samples = (run_end - run_start) * sample_rate
    if dur_samples >= min_silence_samples:
        avg_db = float(np.mean(run_dbs))
        zones.append(
            SilenceZone(
                start_s=run_start,
                end_s=run_end,
                center_s=(run_start + run_end) / 2.0,
                avg_db=avg_db,
                duration_ms=(run_end - run_start) * 1000.0,
                source=source,
            )
        )
