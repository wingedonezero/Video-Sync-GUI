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
from .types import (
    AudioSegment,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...io.runner import CommandRunner
    from ...models.settings import AppSettings
    from ...orchestrator.steps.context import Context


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

        # --- Build transition zones from clusters ---
        zones = find_transition_zones(stepping_data, flag_info, settings, log)

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

        try:
            # --- Refine boundaries (silence detection in Source 2) ---
            splice_points = refine_boundaries(
                transition_zones=zones,
                src2_pcm=src2_pcm,
                src2_sr=src2_sr,
                settings=settings,
                log=log,
                ref_video_path=ref_file_path,
                tool_paths=ctx.tool_paths,
                runner=runner,
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

            passed, _qa_meta = verify_correction(
                corrected_path=str(qa_path),
                ref_file_path=ref_file_path,
                base_delay_ms=anchor_ms,
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
                ctx.segment_flags[analysis_track_key]["audit_metadata"] = (
                    boundary_audit
                )

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
    target_item.container_delay_ms = 0  # type: ignore[attr-defined]

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
    target_item.apply_track_name = True  # type: ignore[attr-defined]
    if ctx.extracted_items is not None:
        ctx.extracted_items.append(preserved)  # type: ignore[arg-type]

    log(f"[SUCCESS] Stepping correction applied for {original_props.name or 'track'}")
