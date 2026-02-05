# vsg_core/correction/linear.py
from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

from ..models.media import StreamProps, Track

if TYPE_CHECKING:
    from ..io.runner import CommandRunner
    from ..orchestrator.steps.context import Context


def _get_sample_rate(file_path: str, runner: CommandRunner, tool_paths: dict) -> int:
    """Helper to get the sample rate of the first audio stream."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-of",
        "json",
        str(file_path),
    ]
    out = runner.run(cmd, tool_paths)
    if not out:
        runner._log_message(
            "[WARN] Could not probe sample rate, defaulting to 48000 Hz."
        )
        return 48000
    try:
        stream_info = json.loads(out)["streams"][0]
        return int(stream_info.get("sample_rate", 48000))
    except (json.JSONDecodeError, IndexError, KeyError):
        runner._log_message(
            "[WARN] Failed to parse sample rate, defaulting to 48000 Hz."
        )
        return 48000


def run_linear_correction(ctx: Context, runner: CommandRunner) -> Context:
    """Corrects constant audio drift by resampling the audio speed."""
    for analysis_track_key, flag_info in ctx.linear_drift_flags.items():
        source_key = analysis_track_key.split("_")[0]
        drift_rate_ms_s = flag_info.get("rate", 0.0)

        # FIXED: Find ALL audio tracks from this source, not just first
        target_items = [
            item
            for item in ctx.extracted_items
            if item.track.source == source_key
            and item.track.type == "audio"
            and not item.is_preserved
        ]

        if not target_items:
            runner._log_message(
                f"[LinearCorrector] Could not find target audio tracks for {source_key} in the layout. Skipping."
            )
            continue

        runner._log_message(
            f"[LinearCorrector] Applying drift correction to {len(target_items)} track(s) from {source_key} (rate: {drift_rate_ms_s:.2f} ms/s)..."
        )

        # FIXED: Apply correction to ALL audio tracks from this source
        for target_item in target_items:
            original_path = target_item.extracted_path
            corrected_path = (
                original_path.parent / f"drift_corrected_{original_path.stem}.flac"
            )

            tempo_ratio = 1000.0 / (1000.0 + drift_rate_ms_s)
            sample_rate = _get_sample_rate(str(original_path), runner, ctx.tool_paths)

            resample_engine = ctx.settings.segment_resample_engine
            filter_chain = ""

            if resample_engine == "rubberband":
                runner._log_message(
                    "    - Using 'rubberband' engine for high-quality resampling."
                )
                rb_opts = [f"tempo={tempo_ratio}"]

                if not ctx.settings.segment_rb_pitch_correct:
                    rb_opts.append(f"pitch={tempo_ratio}")

                rb_opts.append(f"transients={ctx.settings.segment_rb_transients}")

                if ctx.settings.segment_rb_smoother:
                    rb_opts.append("smoother=on")

                if ctx.settings.segment_rb_pitchq:
                    rb_opts.append("pitchq=on")

                filter_chain = "rubberband=" + ":".join(rb_opts)

            elif resample_engine == "atempo":
                runner._log_message("    - Using 'atempo' engine for fast resampling.")
                filter_chain = f"atempo={tempo_ratio}"

            else:  # Default to aresample
                runner._log_message(
                    "    - Using 'aresample' engine for high-quality resampling."
                )
                new_sample_rate = sample_rate * tempo_ratio
                filter_chain = f"asetrate={new_sample_rate},aresample={sample_rate}"

            resample_cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(original_path),
                "-af",
                filter_chain,
                "-c:a",
                "flac",
                str(corrected_path),
            ]

            if runner.run(resample_cmd, ctx.tool_paths) is None:
                error_msg = f"Linear drift correction with '{resample_engine}' failed for {original_path.name}."
                if resample_engine == "rubberband":
                    error_msg += " (Ensure your FFmpeg build includes 'librubberband')."
                raise RuntimeError(error_msg)

            runner._log_message(
                f"[SUCCESS] Linear drift correction successful for '{original_path.name}'"
            )

            # Preserve the original track
            preserved_item = copy.deepcopy(target_item)
            preserved_item.is_preserved = True
            preserved_item.is_default = False
            original_props = preserved_item.track.props
            preserved_item.track = Track(
                source=preserved_item.track.source,
                id=preserved_item.track.id,
                type=preserved_item.track.type,
                props=StreamProps(
                    codec_id=original_props.codec_id,
                    lang=original_props.lang,
                    name=f"{original_props.name} (Original)"
                    if original_props.name
                    else "Original",
                ),
            )

            # Update the main track to point to corrected FLAC
            target_item.extracted_path = corrected_path
            target_item.is_corrected = True
            target_item.container_delay_ms = 0  # FIXED: New FLAC has no container delay

            # FIXED: Properly indicate the track is corrected and ensure the name is applied
            target_item.track = Track(
                source=target_item.track.source,
                id=target_item.track.id,
                type=target_item.track.type,
                props=StreamProps(
                    codec_id="FLAC",
                    lang=original_props.lang,
                    name=f"{original_props.name} (Drift Corrected)"
                    if original_props.name
                    else "Drift Corrected",  # ENHANCED: Clearer name
                ),
            )
            target_item.apply_track_name = True

            ctx.extracted_items.append(preserved_item)

    return ctx
