# vsg_core/correction/stepping/boundary_refiner.py
"""
Find precise splice points at transition boundaries.

For each transition zone the EDL builder identified, this module:
  1. Converts to Source 2 timeline (correct subtract convention)
  2. Runs video scene detection on Source 2 (progressive content only)
  3. Searches Source 2 PCM for audio silence zones
  4. Finds overlap between video scene cuts and audio silence
  5. Validates all language tracks at the edit point (Silero VAD + RMS)
  6. Nudges to nearest zero-crossing to prevent clicks
  7. Optionally aligns to a video keyframe

Falls back to the legacy midpoint + silence search when video scene
detection is not available (MPEG-2, interlaced, VapourSynth missing).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from . import timeline
from .scene_detect import SceneDetectResult, can_detect_scenes, detect_scenes
from .types import (
    BoundaryResult,
    SilenceZone,
    SplicePoint,
    TrackValidation,
    TransitionZone,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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
    src2_video_path: str | None = None,
    silero_model_path: str | Path | None = None,
    src2_track_streams: dict[str, int] | None = None,
    src2_file_path: str | None = None,
) -> list[SplicePoint]:
    """For each transition zone, find the best splice point in Source 2 audio.

    Parameters
    ----------
    src2_pcm : np.ndarray
        Mono int32 PCM of Source 2 (the target / analysis track).
    src2_sr : int
        Sample rate of src2_pcm.
    src2_video_path : str | None
        Path to Source 2 video for scene detection.
    silero_model_path : str | Path | None
        Path to Silero VAD .jit model for speech detection.
    src2_track_streams : dict[str, int] | None
        Mapping of track names → ffmpeg audio stream indices for
        multi-track validation (e.g. {"JPN": 2, "ENG": 0}).
    src2_file_path : str | None
        Path to Source 2 file for multi-track audio decoding.
    """
    # Determine if video scene detection is available
    use_video = (
        settings.stepping_scene_detection_enabled
        and src2_video_path is not None
        and can_detect_scenes(src2_video_path, runner)
    )
    if settings.stepping_scene_detection_enabled and not use_video:
        if src2_video_path is None:
            log("  [Scene Detect] No Source 2 video path — skipping video layer")
        else:
            log(
                "  [Scene Detect] Source 2 is MPEG-2 or interlaced — "
                "skipping video layer (audio-only mode)"
            )

    splice_points: list[SplicePoint] = []

    for i, zone in enumerate(transition_zones):
        log(
            f"  [Transition {i + 1}] {zone.correction_ms:+.0f}ms "
            f"({zone.delay_before_ms:+.0f}ms → {zone.delay_after_ms:+.0f}ms)"
        )

        # Convert gap boundaries to Source 2 timeline
        gap_start_src2 = timeline.ref_to_src2(zone.ref_start_s, zone.delay_before_ms)
        gap_end_src2 = timeline.ref_to_src2(zone.ref_end_s, zone.delay_before_ms)
        scan_pad = settings.stepping_silence_search_window_s
        scan_start = max(0.0, gap_start_src2 - scan_pad)
        scan_end = gap_end_src2 + scan_pad

        log(f"    Gap (ref): {zone.ref_start_s:.1f}s - {zone.ref_end_s:.1f}s")
        log(f"    Gap (src2): {gap_start_src2:.1f}s - {gap_end_src2:.1f}s")

        # ── Video scene detection ──
        video_result: SceneDetectResult | None = None
        if use_video:
            assert src2_video_path is not None
            video_result = detect_scenes(src2_video_path, scan_start, scan_end, log)
            if video_result.black_zones:
                for bz in video_result.black_zones:
                    log(
                        f"    [Video] BLACK: {bz.start_s:.3f}s - "
                        f"{bz.end_s:.3f}s ({bz.dur_ms:.0f}ms)"
                    )
            cuts_in_zone = [
                c for c in video_result.cuts if scan_start <= c.time_s <= scan_end
            ]
            if cuts_in_zone:
                # Log top cuts only (avoid noise)
                for c in cuts_in_zone[:5]:
                    log(
                        f"    [Video] {c.cut_type}: {c.time_s:.3f}s "
                        f"(diff={c.diff:.3f}, mean={c.mean:.0f})"
                    )
                if len(cuts_in_zone) > 5:
                    log(f"    [Video] ... and {len(cuts_in_zone) - 5} more")
            elif not video_result.black_zones:
                log("    [Video] No scene changes detected in zone")

        # ── Audio silence detection ──
        threshold_db = settings.stepping_silence_threshold_db
        min_dur_ms = settings.stepping_silence_min_duration_ms
        rms_zones = find_silence_zones_rms(
            src2_pcm,
            src2_sr,
            scan_start,
            scan_end,
            threshold_db,
            min_dur_ms,
        )
        if rms_zones:
            for z in rms_zones:
                fits = " ✓ FITS" if z.duration_ms >= abs(zone.correction_ms) else ""
                log(
                    f"    [Audio] Silence: {z.start_s:.3f}s - {z.end_s:.3f}s "
                    f"({z.duration_ms:.0f}ms, {z.avg_db:.0f}dB){fits}"
                )
        else:
            log("    [Audio] No silence zones found")

        # ── Find video + audio overlap ──
        overlap_start: float | None = None
        overlap_end: float | None = None
        overlap_dur = 0.0

        if video_result and rms_zones:
            all_video_cuts = video_result.cuts or []
            for vc in all_video_cuts:
                for az in rms_zones:
                    # Check if video cut falls within ±500ms of silence zone
                    if az.start_s - 0.5 <= vc.time_s <= az.end_s + 0.5:
                        ol_s = max(vc.time_s, az.start_s)
                        ol_e = az.end_s
                        if video_result.black_zones:
                            for bz in video_result.black_zones:
                                if bz.start_s <= vc.time_s <= bz.end_s + 0.5:
                                    ol_e = min(ol_e, bz.end_s)
                        if ol_e > ol_s or abs(ol_e - ol_s) < 0.05:
                            overlap_start = ol_s
                            overlap_end = ol_e
                            overlap_dur = max(0.0, (ol_e - ol_s) * 1000)
                            break
                if overlap_start is not None:
                    break

        if overlap_start is not None:
            log(
                f"    [Overlap] Video + Audio: {overlap_start:.3f}s - "
                f"{overlap_end:.3f}s ({overlap_dur:.0f}ms)"
            )
        elif video_result and rms_zones:
            log("    [Overlap] ⚠ No direct overlap — using best audio silence")
        elif not video_result and rms_zones:
            log("    [Overlap] Video skipped — using audio silence only")

        # ── Determine edit point ──
        best_zone: SilenceZone | None = None
        zone_overflow_ms = 0.0
        if rms_zones:
            # Prefer the zone that fits the correction amount and is longest
            fitting = [z for z in rms_zones if z.duration_ms >= abs(zone.correction_ms)]
            if fitting:
                best_zone = max(fitting, key=lambda z: z.duration_ms)
            else:
                best_zone = max(rms_zones, key=lambda z: z.duration_ms)
                zone_overflow_ms = abs(zone.correction_ms) - best_zone.duration_ms

        if best_zone is not None:
            # Prefer the video+audio overlap position when available.
            # The overlap is where the video scene cut and audio silence
            # coincide — that's the actual editorial boundary where one
            # source's content differs from the other.  Placing the edit
            # there is more correct than the silence zone start (which
            # can be hundreds of ms before the real content change).
            # Fall back to silence zone start when no overlap exists
            # (e.g., video scene detection was skipped or no cuts found).
            if (
                overlap_start is not None
                and best_zone.start_s <= overlap_start <= best_zone.end_s
            ):
                splice_src2 = overlap_start
                log(
                    f"    [Edit] Position: {splice_src2:.3f}s src2 | "
                    f"{'INSERT' if zone.correction_ms > 0 else 'TRIM'} "
                    f"{abs(zone.correction_ms):.1f}ms "
                    f"(at video+audio overlap)"
                )
            else:
                splice_src2 = best_zone.start_s
                log(
                    f"    [Edit] Position: {splice_src2:.3f}s src2 | "
                    f"{'INSERT' if zone.correction_ms > 0 else 'TRIM'} "
                    f"{abs(zone.correction_ms):.1f}ms "
                    f"(at silence zone start)"
                )
            log(
                f"    [Edit] In silence: {best_zone.start_s:.3f}s - "
                f"{best_zone.end_s:.3f}s ({best_zone.duration_ms:.0f}ms)"
            )
            if zone_overflow_ms > 0:
                log(
                    f"    [⚠ QUALITY] Silence zone too small for correction — "
                    f"{best_zone.duration_ms:.0f}ms silence vs "
                    f"{abs(zone.correction_ms):.0f}ms correction "
                    f"(overflow {zone_overflow_ms:.0f}ms into audio content)"
                )
        else:
            # Fallback: midpoint of gap
            ref_mid = (zone.ref_start_s + zone.ref_end_s) / 2.0
            splice_src2 = timeline.ref_to_src2(ref_mid, zone.delay_before_ms)
            log(f"    [Edit] ⚠ No silence — fallback midpoint: {splice_src2:.3f}s src2")

        # ── Silero VAD track validation ──
        track_vals: list[TrackValidation] = []
        if (
            settings.stepping_silero_vad_enabled
            and silero_model_path
            and src2_track_streams
            and src2_file_path
        ):
            track_vals = _validate_tracks_silero(
                src2_file_path,
                src2_track_streams,
                splice_src2,
                src2_sr,
                silero_model_path,
                settings.stepping_silero_vad_threshold,
                log,
            )
        else:
            log("    [Tracks] Silero VAD not available — track validation skipped")

        # ── Transient detection ──
        near_transient = False
        if settings.stepping_transient_detection_enabled:
            transient_times = detect_transients(
                src2_pcm,
                src2_sr,
                scan_start,
                scan_end,
                threshold_db=settings.stepping_transient_threshold,
            )
            if transient_times:
                # Check if edit point is near a transient
                margin = 0.05
                near_transient = any(
                    abs(t - splice_src2) < margin for t in transient_times
                )
                if near_transient:
                    log(
                        f"    [Transient] ⚠ Transient detected near edit "
                        f"({splice_src2:.3f}s)"
                    )

        # ── Zero-crossing snap ──
        pre_zc = splice_src2
        splice_src2 = _snap_to_zero_crossing(src2_pcm, src2_sr, splice_src2)
        shift_ms = (splice_src2 - pre_zc) * 1000.0
        zone_info = (
            f"zone avg {best_zone.avg_db:.0f}dB" if best_zone is not None else "no zone"
        )
        if abs(shift_ms) > 0.005:
            log(
                f"    [Snap] Zero-crossing: {pre_zc:.4f}s → {splice_src2:.4f}s "
                f"(shift {shift_ms:+.3f}ms, {zone_info})"
            )
        else:
            # Either already on a zero crossing (common in deep silence) or
            # no crossing was found within the search radius.
            log(f"    [Snap] Zero-crossing: already aligned ({zone_info})")

        # ── Optional video keyframe snap ──
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
                snapped_src2 = timeline.ref_to_src2(snapped_ref, zone.delay_before_ms)
                if best_zone is not None:
                    if best_zone.start_s <= snapped_src2 <= best_zone.end_s:
                        splice_src2 = snapped_src2
                        snap_meta["video_snapped"] = True
                        snap_meta["video_snap_offset_s"] = snapped_ref - splice_ref
                        log(
                            f"    [Snap] Video keyframe: "
                            f"{splice_ref:.3f}s → {snapped_ref:.3f}s"
                        )
                    else:
                        log(
                            f"    [Snap] Video keyframe rejected: "
                            f"{snapped_src2:.3f}s outside silence zone"
                        )

        # ── Build SplicePoint ──
        splice_ref_final = timeline.src2_to_ref(splice_src2, zone.delay_before_ms)

        boundary = BoundaryResult(
            zone=best_zone,
            score=best_zone.duration_ms if best_zone else 0.0,
            near_transient=near_transient,
            overlaps_speech=any(tv.is_speech for tv in track_vals),
            video_scene=video_result,
            overlap_start_s=overlap_start,
            overlap_end_s=overlap_end,
            overlap_dur_ms=overlap_dur,
            track_validations=tuple(track_vals),
            zone_overflow_ms=zone_overflow_ms,
        )

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
# Silero VAD track validation
# ---------------------------------------------------------------------------


def _validate_tracks_silero(
    src2_file_path: str,
    track_streams: dict[str, int],
    edit_time_s: float,
    sample_rate: int,
    model_path: str | Path,
    threshold: float,
    log: Callable[[str], None],
) -> list[TrackValidation]:
    """Validate all language tracks at the edit point using Silero VAD."""
    import subprocess

    from .silero_vad import detect_speech_regions

    validations: list[TrackValidation] = []

    for track_name, stream_idx in track_streams.items():
        # Decode 2 seconds around the edit point
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(max(0, edit_time_s - 1)),
            "-t",
            "2",
            "-i",
            src2_file_path,
            "-map",
            f"0:a:{stream_idx}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, check=True)
            pcm_16k = np.frombuffer(result.stdout, dtype=np.float32)
        except Exception:
            validations.append(
                TrackValidation(
                    track_name=track_name,
                    db=-120.0,
                    is_speech=False,
                    status="DECODE_ERROR",
                )
            )
            continue

        # Check speech
        speech_regions = detect_speech_regions(
            pcm_16k,
            16000,
            model_path,
            threshold=threshold,
        )
        # Adjust to absolute time
        base_t = max(0, edit_time_s - 1)
        is_speech = any(
            base_t + s <= edit_time_s <= base_t + e for s, e in speech_regions
        )

        # Check RMS at the edit point (center of the 2s window)
        center_sample = min(len(pcm_16k) - 1600, 16000)  # ~1s into buffer
        chunk = pcm_16k[center_sample : center_sample + 1600]
        if len(chunk) > 0:
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            db = 20.0 * np.log10(rms) if rms > 1e-10 else -120.0
        else:
            db = -120.0

        # Classify
        if db < -100:
            status = "TRUE SILENCE"
        elif db < -70:
            status = "SILENCE"
        elif not is_speech and db < -40:
            status = "QUIET"
        elif not is_speech:
            status = "CROSSFADE"
        else:
            status = "⚠ SPEECH"

        validations.append(
            TrackValidation(
                track_name=track_name,
                db=db,
                is_speech=is_speech,
                status=status,
            )
        )
        log(
            f"    [Tracks] {track_name:>12}: {db:>7.1f}dB  "
            f"VAD={'SPEECH' if is_speech else 'clear':>6}  → {status}"
        )

    return validations


# ---------------------------------------------------------------------------
# RMS silence detection
# ---------------------------------------------------------------------------


def find_silence_zones_rms(
    pcm: np.ndarray,
    sample_rate: int,
    start_s: float,
    end_s: float,
    threshold_db: float,
    min_duration_ms: float,
) -> list[SilenceZone]:
    """Find contiguous quiet regions using RMS energy in 20 ms windows.

    20 ms matches the precision of the original research/test pipeline
    (test_combined_final.py).  Smaller windows catch silence-zone
    boundaries more precisely — detected start/end lands on a 20 ms
    grid instead of a 50 ms grid, which matters for tight splices
    where the available silence only barely fits the correction amount.
    """
    start_sample = max(0, int(start_s * sample_rate))
    end_sample = min(len(pcm), int(end_s * sample_rate))
    if end_sample <= start_sample:
        return []

    window_size = max(1, int(0.02 * sample_rate))
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
