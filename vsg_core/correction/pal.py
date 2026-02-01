# vsg_core/correction/pal.py
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from ..models.enums import TrackType
from ..models.media import StreamProps, Track

if TYPE_CHECKING:
    from ..io.runner import CommandRunner
    from ..orchestrator.steps.context import Context


def run_pal_correction(ctx: Context, runner: CommandRunner) -> Context:
    """Corrects audio drift due to PAL speed-up using a pitch-corrected resample."""
    for analysis_track_key, flag_info in ctx.pal_drift_flags.items():
        source_key = analysis_track_key.split("_")[0]

        # FIXED: Find ALL audio tracks from this source, not just first
        target_items = [
            item
            for item in ctx.extracted_items
            if item.track.source == source_key
            and item.track.type == TrackType.AUDIO
            and not item.is_preserved
        ]

        if not target_items:
            runner._log_message(
                f"[PALCorrector] Could not find target audio tracks for {source_key} in the layout. Skipping."
            )
            continue

        runner._log_message(
            f"[PALCorrector] Applying PAL speed correction to {len(target_items)} track(s) from {source_key}..."
        )

        # FIXED: Apply correction to ALL audio tracks from this source
        for target_item in target_items:
            original_path = target_item.extracted_path
            corrected_path = (
                original_path.parent / f"pal_corrected_{original_path.stem}.flac"
            )

            # Use ffmpeg with the rubberband filter for high-quality, pitch-corrected timestretching.
            # The tempo is set to slow down a 25fps source to match a 23.976fps (24000/1001) source.
            tempo_ratio = (24000 / 1001) / 25.0
            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(original_path),
                "-af",
                f"rubberband=tempo={tempo_ratio}",
                "-c:a",
                "flac",
                str(corrected_path),
            ]

            if runner.run(cmd, ctx.tool_paths) is None:
                raise RuntimeError(
                    f"PAL drift correction failed for {original_path.name}. This may be because your ffmpeg build lacks librubberband support."
                )

            runner._log_message(
                f"[SUCCESS] PAL correction successful for '{original_path.name}'"
            )

            # Preserve the original track for reference
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

            # Update the main track item to point to the new, corrected FLAC file
            target_item.extracted_path = corrected_path
            target_item.is_corrected = True
            target_item.container_delay_ms = 0  # FIXED: New FLAC has no container delay
            target_item.track = Track(
                source=target_item.track.source,
                id=target_item.track.id,
                type=target_item.track.type,
                props=StreamProps(
                    codec_id="FLAC",
                    lang=original_props.lang,
                    name=f"{original_props.name} (PAL Corrected)"
                    if original_props.name
                    else "PAL Corrected",  # ENHANCED: Clearer name
                ),
            )
            target_item.apply_track_name = True

            ctx.extracted_items.append(preserved_item)

    return ctx
