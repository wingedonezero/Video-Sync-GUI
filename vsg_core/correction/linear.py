# vsg_core/correction/linear.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import copy

from ..orchestrator.steps.context import Context
from ..io.runner import CommandRunner
from ..models.enums import TrackType
from ..models.media import StreamProps, Track

def run_linear_correction(ctx: Context, runner: CommandRunner) -> Context:
    """Corrects constant audio drift by resampling the audio speed."""
    for analysis_track_key, flag_info in ctx.linear_drift_flags.items():
        source_key = analysis_track_key.split('_')[0]
        drift_rate_ms_s = flag_info.get('rate', 0.0)

        target_item = next((item for item in ctx.extracted_items if item.track.source == source_key and item.track.type == TrackType.AUDIO and not item.is_preserved), None)

        if not target_item:
            runner._log_message(f"[LinearCorrector] Could not find a target audio track for {source_key} in the layout. Skipping.")
            continue

        runner._log_message(f"[LinearCorrector] Applying drift correction to track from {source_key} (rate: {drift_rate_ms_s:.2f} ms/s)...")

        original_path = target_item.extracted_path
        corrected_path = original_path.parent / f"drift_corrected_{original_path.stem}.flac"

        # Calculate the tempo multiplier. If drift is +1ms/s, the new duration is 1001ms, so tempo should be 1000/1001.
        tempo_ratio = 1000.0 / (1000.0 + drift_rate_ms_s)

        # FFmpeg's atempo filter is limited to values between 0.5 and 100.0.
        # This is fine, as our drift rates will be very small.
        if not (0.5 <= tempo_ratio <= 100.0):
             raise ValueError(f"Calculated tempo ratio {tempo_ratio:.4f} is outside ffmpeg's supported range.")

        cmd = [
            'ffmpeg', '-y', '-nostdin', '-v', 'error',
            '-i', str(original_path),
            '-af', f'atempo={tempo_ratio}',
            '-c:a', 'flac',
            str(corrected_path)
        ]

        if runner.run(cmd, ctx.tool_paths) is None:
            raise RuntimeError(f"Linear drift correction failed for {original_path.name}.")

        runner._log_message(f"[SUCCESS] Linear drift correction successful for '{original_path.name}'")

        # Preserve the original track for reference
        preserved_item = copy.deepcopy(target_item)
        preserved_item.is_preserved = True
        preserved_item.is_default = False
        original_props = preserved_item.track.props
        preserved_item.track = Track(
            source=preserved_item.track.source, id=preserved_item.track.id, type=preserved_item.track.type,
            props=StreamProps(
                codec_id=original_props.codec_id,
                lang=original_props.lang,
                name=f"{original_props.name} (Original)" if original_props.name else "Original"
            )
        )

        # Update the main track item to point to the new, corrected FLAC file
        target_item.extracted_path = corrected_path
        target_item.is_corrected = True
        target_item.track = Track(
            source=target_item.track.source, id=target_item.track.id, type=target_item.track.type,
            props=StreamProps(
                codec_id="FLAC",
                lang=original_props.lang,
                name=f"{original_props.name} (Drift Corrected)" if original_props.name else "Drift Corrected"
            )
        )
        target_item.apply_track_name = True

        ctx.extracted_items.append(preserved_item)

    return ctx
