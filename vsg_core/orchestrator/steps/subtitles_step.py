# vsg_core/orchestrator/steps/subtitles_step.py
"""
Unified subtitle processing step using SubtitleData.

Flow:
1. Video-verified preprocessing (if enabled, once per source)
2. For each subtitle track:
   - OCR (if needed)
   - Process through SubtitleData pipeline (or bypass)
   - Apply operations: stepping, sync, styles
   - Save once at end (single rounding point)

All timing is float ms internally - rounding only at final save.

This step is a pure coordinator - all business logic is in subtitle modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class SubtitlesStep:
    """
    Unified subtitle processing step - pure coordinator.

    Delegates to specialized subtitle modules for all business logic.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            runner._log_message(
                "[WARN] No Source 1 file found for subtitle processing reference."
            )

        items_to_add = []

        # ================================================================
        # Video-Verified Pre-Processing (once per source)
        # ================================================================
        # If video-verified mode is enabled, run frame matching once per
        # unique source and update ctx.subtitle_delays_ms. This ensures all subtitle
        # tracks (text, bitmap, OCR'd, preserved) use the corrected delay.
        subtitle_sync_mode = ctx.settings.subtitle_sync_mode
        if subtitle_sync_mode == "video-verified" and source1_file:
            from vsg_core.subtitles.sync_mode_plugins.video_verified.preprocessing import (
                run_per_source_preprocessing,
            )

            run_per_source_preprocessing(ctx, runner, source1_file)

        # ================================================================
        # Process Each Subtitle Track
        # ================================================================
        for item in ctx.extracted_items:
            if item.track.type != "subtitles":
                continue

            # NOTE: user_modified_path is NOT used during job execution
            # Style editor temp files are only for preview during editing
            # Job execution uses fresh extraction + style_patch via SubtitleData

            # ================================================================
            # OCR Processing (if needed)
            # ================================================================
            ocr_subtitle_data = None
            if item.perform_ocr and item.extracted_path:
                from vsg_core.subtitles.ocr.wrapper import (
                    process_ocr_with_preservation,
                )

                ocr_subtitle_data = process_ocr_with_preservation(
                    item, ctx, runner, items_to_add
                )
                if ocr_subtitle_data is None:
                    continue  # OCR failed, skip this track

            # ================================================================
            # Check if we can skip SubtitleData processing for time-based mode
            # This matches old behavior where time-based + mkvmerge just passed
            # the file through unchanged
            # ================================================================
            if self._should_bypass_processing(item, ctx, ocr_subtitle_data):
                # BYPASS: Time-based mode with no other processing needed
                # Pass subtitle file through unchanged - mkvmerge --sync handles delay
                runner._log_message(
                    f"[Subtitles] Track {item.track.id}: BYPASS mode - passing through unchanged for mkvmerge --sync"
                )
                runner._log_message(
                    "[Subtitles]   (No OCR, style ops, stepping, or format conversion needed)"
                )
                continue  # Skip to next track - file is already in item.extracted_path

            # ================================================================
            # Unified SubtitleData Processing
            # ================================================================
            if item.extracted_path:
                ext = item.extracted_path.suffix.lower()
                supported_formats = [".ass", ".ssa", ".srt", ".vtt"]

                if ext in supported_formats or ocr_subtitle_data is not None:
                    try:
                        from vsg_core.subtitles.track_processor import (
                            process_subtitle_track,
                        )

                        process_subtitle_track(
                            item=item,
                            ctx=ctx,
                            runner=runner,
                            source1_file=source1_file,
                            ocr_subtitle_data=ocr_subtitle_data,
                            items_to_add=items_to_add,
                        )
                    except Exception as e:
                        runner._log_message(
                            f"[Subtitles] ERROR processing track {item.track.id}: {e}"
                        )
                        raise
                # Bitmap subtitles (VobSub, PGS) - can't process with unified flow
                # but CAN use video-verified mode for frame-corrected delays
                elif subtitle_sync_mode == "video-verified":
                    from vsg_core.subtitles.sync_mode_plugins.video_verified.preprocessing import (
                        apply_for_bitmap_subtitle,
                    )

                    apply_for_bitmap_subtitle(item, ctx, runner, source1_file)
                else:
                    runner._log_message(
                        f"[Subtitles] Track {item.track.id}: Bitmap format {ext} - using mkvmerge --sync for delay"
                    )

        if items_to_add:
            ctx.extracted_items.extend(items_to_add)

        return ctx

    def _should_bypass_processing(self, item, ctx, ocr_subtitle_data) -> bool:
        """
        Check if we can bypass SubtitleData processing.

        Bypass conditions:
        - Time-based sync mode with bypass enabled
        - No OCR, style operations, stepping, or format conversion needed
        - Text-based subtitle format (not bitmap)

        Returns True if track can bypass SubtitleData processing.
        """
        subtitle_sync_mode = ctx.settings.subtitle_sync_mode
        use_raw_values = ctx.settings.time_based_use_raw_values
        bypass_subtitle_data = ctx.settings.time_based_bypass_subtitle_data

        # Determine if we need SubtitleData processing
        needs_subtitle_data = (
            ocr_subtitle_data is not None  # OCR requires SubtitleData
            or item.perform_ocr  # OCR pending
            or item.style_patch  # Style operations need SubtitleData
            or item.font_replacements  # Font operations need SubtitleData
            or item.rescale  # Rescale needs SubtitleData
            or (
                hasattr(item, "size_multiplier")
                and abs(float(item.size_multiplier or 1.0) - 1.0) > 1e-6
            )  # Size multiplier
            or item.convert_to_ass  # Format conversion needs SubtitleData
            or item.is_generated  # Generated tracks need style filtering
            or (
                subtitle_sync_mode != "time-based"
            )  # Non-time-based modes need SubtitleData
            or use_raw_values  # Raw values mode applies delay in SubtitleData
            or (
                item.track.source in ctx.stepping_edls
                and ctx.settings.stepping_adjust_subtitles
            )  # Stepping needs SubtitleData
        )

        # Can bypass if: no processing needed AND bypass enabled AND time-based mode
        return (
            not needs_subtitle_data
            and bypass_subtitle_data
            and subtitle_sync_mode == "time-based"
        )
