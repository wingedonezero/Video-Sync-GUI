# vsg_core/correction/stepping/run.py
"""
Stepping correction entry points.

``run_stepping_correction`` is the main coordinator called by
``AudioCorrectionStep``.  It orchestrates the pipeline:

  1. Load dense analysis data from temp folder
  2. Build transition zones from clusters
  3. Refine boundaries with silence detection in Source 2
  4. Assemble corrected audio from EDL
  5. QA-check the result
  6. Apply the verified EDL to all audio tracks from the same source
"""

from __future__ import annotations

import copy
import gc
from pathlib import Path
from typing import TYPE_CHECKING

from ...analysis.correlation import get_audio_stream_info
from ...models.media import StreamProps, Track
from .audio_assembly import (
    assemble_corrected_audio,
    decode_to_memory,
    get_audio_properties,
)
from .boundary_refiner import refine_boundaries
from .data_io import load_stepping_data
from .edl_builder import build_segments_from_splice_points, find_transition_zones
from .qa_check import verify_correction

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...io.runner import CommandRunner
    from ...models.settings import AppSettings
    from ...orchestrator.steps.context import Context
    from .types import AudioSegment


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_stepping_correction(ctx: Context, runner: CommandRunner) -> Context:
    """Stepping correction coordinator — called by AudioCorrectionStep."""
    log = runner._log_message
    settings = ctx.settings
    ref_file_path = ctx.sources.get("Source 1")

    for analysis_track_key, flag_info in ctx.segment_flags.items():
        source_key = analysis_track_key.split("_")[0]
        subs_only: bool = flag_info.get("subs_only", False)

        # Find audio tracks from this source to correct
        target_items = [
            item
            for item in (ctx.extracted_items or [])
            if item.track.source == source_key
            and item.track.type == "audio"
            and not item.is_preserved
        ]

        if not target_items and not subs_only:
            log(
                f"[SteppingCorrection] Skipping {source_key}: "
                "no audio tracks to correct."
            )
            continue

        # --- Load dense data ---
        data_path = flag_info.get("stepping_data_path")
        if not data_path:
            log(
                f"[SteppingCorrection] ERROR: No dense data for "
                f"{analysis_track_key}. Cannot proceed."
            )
            continue

        log(f"[SteppingCorrection] Loading dense data from {Path(data_path).name}...")
        stepping_data = load_stepping_data(data_path)
        log(
            f"  {len(stepping_data.windows)} windows, "
            f"{len(stepping_data.clusters)} clusters"
        )

        # --- Extract Source 2 chapter markers for noise recovery ---
        chapter_times: list[float] | None = None
        src2_path_for_chapters = ctx.sources.get(source_key)
        if src2_path_for_chapters and settings.stepping_noise_recovery_enabled:
            chapter_times = _extract_chapter_times(
                src2_path_for_chapters, runner, ctx.tool_paths, log
            )

        # --- Build transition zones from clusters ---
        zones = find_transition_zones(
            stepping_data,
            flag_info,
            settings,
            log,
            chapter_times=chapter_times,
        )

        if not zones:
            # No transitions detected — uniform delay
            log(
                "[SteppingCorrection] No transitions found. "
                "Audio delay appears uniform."
            )
            continue

        # --- Decode Source 2 mono PCM for silence detection ---
        analysis_item = _find_analysis_track(ctx, analysis_track_key, runner)
        if analysis_item is None:
            continue

        analysis_path = str(analysis_item)
        idx, _ = get_audio_stream_info(analysis_path, None, runner, ctx.tool_paths)
        if idx is None:
            log(f"[ERROR] No audio stream in {analysis_path}")
            continue

        _, _, src2_sr = get_audio_properties(analysis_path, idx, runner, ctx.tool_paths)
        src2_pcm = decode_to_memory(
            analysis_path, idx, src2_sr, runner, ctx.tool_paths, channels=1, log=log
        )
        if src2_pcm is None:
            continue

        # Resolve Source 2 video path for scene detection
        src2_video_path = ctx.sources.get(source_key)

        # Ensure Silero VAD model if enabled
        silero_model_path: str | None = None
        if settings.stepping_silero_vad_enabled:
            try:
                from .silero_vad import ensure_silero_model

                silero_model_path = str(ensure_silero_model(log=log))
            except Exception as exc:
                log(
                    f"[SteppingCorrection] Silero VAD unavailable: {exc} "
                    "— falling back to WebRTC VAD"
                )

        # Collect multi-track stream indices for validation
        src2_track_streams: dict[str, int] | None = None
        src2_file_str: str | None = None
        if silero_model_path and src2_video_path:
            src2_file_str = src2_video_path
            src2_track_streams = _build_audio_track_map(
                src2_video_path, runner, ctx.tool_paths
            )

        try:
            # --- Refine boundaries (scene detection + silence + VAD) ---
            splice_points = refine_boundaries(
                transition_zones=zones,
                src2_pcm=src2_pcm,
                src2_sr=src2_sr,
                settings=settings,
                log=log,
                ref_video_path=ref_file_path,
                tool_paths=ctx.tool_paths,
                runner=runner,
                src2_video_path=src2_video_path,
                silero_model_path=silero_model_path,
                src2_track_streams=src2_track_streams,
                src2_file_path=src2_file_str,
            )

            if not splice_points:
                log(
                    "[SteppingCorrection] Boundary refinement produced no splice points."
                )
                continue

            # --- Build final EDL ---
            # Anchor = first cluster's delay
            first_cluster = min(
                stepping_data.clusters,
                key=lambda c: c.time_range[0],
            )
            anchor_ms = int(round(first_cluster.mean_delay_ms))
            anchor_raw = first_cluster.mean_delay_ms

            # Convert splice points to segment tuples
            seg_tuples: list[tuple[float, float, float]] = []
            for sp in splice_points:
                seg_tuples.append(
                    (sp.src2_time_s, sp.delay_after_ms, sp.delay_after_ms)
                )

            edl = build_segments_from_splice_points(
                anchor_delay_ms=anchor_ms,
                anchor_delay_raw=anchor_raw,
                splice_points=seg_tuples,
                log=log,
            )

            if len(edl) <= 1:
                log(
                    "[SteppingCorrection] Only one segment — "
                    "no stepping correction needed."
                )
                continue

            # Store EDL for subtitle adjustment
            ctx.stepping_edls[source_key] = edl

            if subs_only:
                log(
                    f"[SteppingCorrection] Subs-only mode — "
                    f"EDL with {len(edl)} segments stored."
                )
                continue

            # --- QA: Assemble a mono check track and verify ---
            qa_path = ctx.temp_dir / f"qa_{source_key.replace(' ', '_')}.flac"
            qa_ok = assemble_corrected_audio(
                edl=edl,
                target_audio_path=analysis_path,
                output_path=qa_path,
                runner=runner,
                tool_paths=ctx.tool_paths,
                settings=settings,
                log=log,
                channels=1,
                channel_layout="mono",
                sample_rate=src2_sr,
                target_pcm=src2_pcm,
            )
            if not qa_ok:
                log("[SteppingCorrection] QA assembly failed.")
                del ctx.stepping_edls[source_key]
                continue

            if ref_file_path is None:
                log("[SteppingCorrection] No Source 1 file — skipping QA check.")
                del ctx.stepping_edls[source_key]
                continue

            # QA: the corrected FLAC is pre-aligned to Source 1's audio-content
            # timeline, so median correlation delay should be 0 (not the
            # first-cluster delay the way the old flow measured it).
            passed, _qa_meta = verify_correction(
                corrected_path=str(qa_path),
                ref_file_path=ref_file_path,
                base_delay_ms=0,
                settings=settings,
                runner=runner,
                tool_paths=ctx.tool_paths,
                log=log,
            )
            if not passed:
                log("[SteppingCorrection] QA check FAILED — skipping correction.")
                del ctx.stepping_edls[source_key]
                continue

            # Store audit metadata from splice points for post-mux auditor
            if analysis_track_key in ctx.segment_flags:
                boundary_audit: list[dict[str, object]] = []
                for sp in splice_points:
                    br = sp.boundary_result
                    entry: dict[str, object] = {
                        "target_time_s": sp.src2_time_s,
                        "delay_change_ms": sp.correction_ms,
                        "no_silence_found": sp.silence_zone is None,
                        "zone_start": sp.silence_zone.start_s if sp.silence_zone else 0,
                        "zone_end": sp.silence_zone.end_s if sp.silence_zone else 0,
                        "avg_db": sp.silence_zone.avg_db if sp.silence_zone else 0,
                        "score": br.score if br else 0,
                        "overlaps_speech": br.overlaps_speech if br else False,
                        "near_transient": br.near_transient if br else False,
                        "video_snap_skipped": sp.snap_metadata.get(
                            "video_snap_skipped", False
                        ),
                    }
                    boundary_audit.append(entry)
                ctx.segment_flags[analysis_track_key]["audit_metadata"] = boundary_audit

            # --- Apply to all audio tracks from this source ---
            log(
                f"[SteppingCorrection] QA passed — applying to "
                f"{len(target_items)} audio track(s)."
            )
            for target_item in target_items:
                if target_item.extracted_path is None:
                    log("[ERROR] Skipping track with no extracted path.")
                    continue
                corrected_path = ctx.temp_dir / (
                    f"corrected_{target_item.extracted_path.stem}.flac"
                )
                ok = assemble_corrected_audio(
                    edl=edl,
                    target_audio_path=str(target_item.extracted_path),
                    output_path=corrected_path,
                    runner=runner,
                    tool_paths=ctx.tool_paths,
                    settings=settings,
                    log=log,
                )
                if not ok:
                    log(
                        f"[ERROR] Assembly failed for "
                        f"{target_item.extracted_path.name} — keeping original."
                    )
                    continue

                _swap_corrected_track(ctx, target_item, corrected_path, settings, log)

        finally:
            del src2_pcm
            gc.collect()

    return ctx


# ---------------------------------------------------------------------------
# apply_plan_to_file (kept for external use / subtitle EDL replay)
# ---------------------------------------------------------------------------


def apply_plan_to_file(
    target_audio_path: str,
    edl: list[AudioSegment],
    temp_dir: Path,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    settings: AppSettings,
    log: Callable[[str], None] | None = None,
) -> Path | None:
    """Apply a pre-generated EDL to a given audio file.

    Returns the path to the corrected FLAC, or ``None`` on failure.
    """
    _log = log or runner._log_message

    corrected_path = temp_dir / f"corrected_{Path(target_audio_path).stem}.flac"
    ok = assemble_corrected_audio(
        edl=edl,
        target_audio_path=target_audio_path,
        output_path=corrected_path,
        runner=runner,
        tool_paths=tool_paths,
        settings=settings,
        log=_log,
    )
    return corrected_path if ok else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_chapter_times(
    video_path: str,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    log: Callable[[str], None],
) -> list[float] | None:
    """Extract chapter start times from a video file via ffprobe."""
    import json as _json

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_chapters",
        "-of",
        "json",
        video_path,
    ]
    try:
        out = runner.run(cmd, tool_paths)
        if not out:
            return None
        data = _json.loads(out)
        chapters = data.get("chapters", [])
        if not chapters:
            return None
        times = [float(c["start_time"]) for c in chapters if "start_time" in c]
        if times:
            log(f"[SteppingCorrection] {len(times)} chapter markers found")
        return times or None
    except Exception:
        return None


def _build_audio_track_map(
    src_path: str,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> dict[str, int] | None:
    """Return ``{label: ffmpeg_audio_stream_idx}`` for every audio track.

    Queries mkvmerge for the audio tracks in *src_path* and builds a map
    that ``_validate_tracks_silero`` can feed to ``ffmpeg -map 0:a:N``.
    Label format: ``LANG_CODEC`` (e.g. ``jpn_TrueHD``).  Validates ALL
    language tracks — the disc timeline is shared, so every audio track
    gets the same splice, and we want the speech check to cover any of
    them that could overlap the edit point.
    """
    import json as _json

    out = runner.run(["mkvmerge", "-J", src_path], tool_paths)
    if not out or not isinstance(out, str):
        return None
    try:
        info = _json.loads(out)
    except Exception:
        return None
    audio_tracks = [t for t in info.get("tracks", []) if t.get("type") == "audio"]
    if not audio_tracks:
        return None

    result: dict[str, int] = {}
    for i, t in enumerate(audio_tracks):
        props = t.get("properties", {}) or {}
        lang = (props.get("language") or "und").lower()
        codec = (t.get("codec") or "audio").replace(" ", "").replace("/", "")
        label = f"{lang}_{codec}"
        if label in result:
            label = f"{label}_{i}"
        result[label] = i
    return result or None


def _find_analysis_track(
    ctx: Context,
    analysis_track_key: str,
    runner: CommandRunner,
) -> Path | None:
    """Locate the extracted analysis audio track, extracting if needed."""
    from ...extraction.tracks import extract_tracks

    extracted_audio_map = {
        f"{item.track.source}_{item.track.id}": item
        for item in (ctx.extracted_items or [])
        if item.track.type == "audio"
    }

    analysis_item = extracted_audio_map.get(analysis_track_key)
    if analysis_item:
        return analysis_item.extracted_path

    # Not in layout — extract internally
    source_key = analysis_track_key.split("_", maxsplit=1)[0]
    track_id = int(analysis_track_key.split("_")[1])
    source_path = ctx.sources.get(source_key)
    if source_path is None:
        runner._log_message(
            f"[ERROR] No source path for {source_key} — cannot extract analysis track."
        )
        return None

    runner._log_message(
        f"[SteppingCorrection] Analysis track {analysis_track_key} "
        "not in layout — extracting internally..."
    )
    try:
        internal = extract_tracks(
            source_path,
            ctx.temp_dir,
            runner,
            ctx.tool_paths,
            role=f"{source_key}_internal",
            specific_tracks=[track_id],
        )
        if internal:
            return Path(internal[0]["path"])
    except Exception as exc:
        runner._log_message(
            f"[ERROR] Internal extraction failed for {analysis_track_key}: {exc}"
        )
    return None


def _swap_corrected_track(
    ctx: Context,
    target_item: object,
    corrected_path: Path,
    settings: AppSettings,
    log: Callable[[str], None],
) -> None:
    """Preserve the original and point the item to the corrected FLAC."""

    # Preserve original
    preserved = copy.deepcopy(target_item)
    preserved.is_preserved = True  # type: ignore[attr-defined]
    preserved.is_default = False  # type: ignore[attr-defined]
    original_props = preserved.track.props  # type: ignore[attr-defined]

    # Build names
    preserved_label = settings.stepping_preserved_track_label
    if preserved_label:
        preserved_name = (
            f"{original_props.name} ({preserved_label})"
            if original_props.name
            else preserved_label
        )
    else:
        preserved_name = original_props.name

    preserved.track = Track(  # type: ignore[attr-defined]
        source=preserved.track.source,  # type: ignore[attr-defined]
        id=preserved.track.id,  # type: ignore[attr-defined]
        type=preserved.track.type,  # type: ignore[attr-defined]
        props=StreamProps(
            codec_id=original_props.codec_id,
            lang=original_props.lang,
            name=preserved_name,
        ),
    )

    # Update main track → corrected FLAC
    target_item.extracted_path = corrected_path  # type: ignore[attr-defined]
    target_item.is_corrected = True  # type: ignore[attr-defined]
    # The corrected FLAC is pre-aligned to Source 1's audio-content timeline.
    # We still need to apply Source 1's own audio-container delay at mux time
    # so the corrected track matches where Source 1's audio lands in the
    # final MKV container.  We stash that value in container_delay_ms and
    # flip the is_pre_aligned flag; the options builder and audio trim both
    # read this path for pre-aligned tracks (bypassing the correlation-delay
    # lookup, which would double-apply the shift we already baked in).
    target_item.is_pre_aligned = True  # type: ignore[attr-defined]
    target_item.container_delay_ms = int(  # type: ignore[attr-defined]
        round(ctx.source1_audio_container_delay_ms)
    )

    corrected_label = settings.stepping_corrected_track_label
    if corrected_label:
        corrected_name = (
            f"{original_props.name} ({corrected_label})"
            if original_props.name
            else corrected_label
        )
    else:
        corrected_name = original_props.name

    target_item.track = Track(  # type: ignore[attr-defined]
        source=target_item.track.source,  # type: ignore[attr-defined]
        id=target_item.track.id,  # type: ignore[attr-defined]
        type=target_item.track.type,  # type: ignore[attr-defined]
        props=StreamProps(
            codec_id="FLAC",
            lang=original_props.lang,
            name=corrected_name,
        ),
    )
    # Inherit apply_track_name from the user's manual-selection layout
    # (same treatment the preserved track gets via deep-copy).  If the
    # user had "keep name" unchecked, the corrected FLAC comes out
    # unnamed in the final MKV — options_builder skips --track-name when
    # apply_track_name is False and custom_name is empty.  The stepping
    # correction shouldn't unilaterally override a per-track choice.
    if ctx.extracted_items is not None:
        ctx.extracted_items.append(preserved)  # type: ignore[arg-type]

    log(f"[SUCCESS] Stepping correction applied for {original_props.name or 'track'}")
