# vsg_core/orchestrator/steps/video_correction_step.py
"""Pipeline step: Video stream corrections.

Currently handles:
- MPEG-2 soft pulldown removal (3:2 telecine flag stripping)

Runs after ExtractStep, before AudioCorrectionStep.
Only processes Source 1 video tracks (video is always from Source 1).
The step is gated by the pulldown_removal_enabled setting — if disabled,
it logs that it was skipped and returns immediately.

Both the original and corrected files are kept in the temp folder.
The PlanItem's extracted_path is updated to point to the corrected file
only if the setting is enabled AND removal actually succeeded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.models.context_types import PulldownRemovalInfo
from vsg_core.video.mpeg2_pulldown import remove_pulldown
from vsg_core.video.pulldown_detect import detect_pulldown

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class VideoCorrectionStep:
    """Apply video-level corrections to extracted streams.

    Currently: soft pulldown removal for MPEG-2 DVD sources.
    Future: could host other video corrections (field order fixes, etc.)
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.extracted_items:
            runner._log_message("[VideoCorrection] No extracted items, skipping")
            return ctx

        if not ctx.settings.pulldown_removal_enabled:
            runner._log_message(
                "[VideoCorrection] Pulldown removal is disabled in settings, skipping"
            )
            return ctx

        # Only look at Source 1 video tracks
        video_items = [
            item
            for item in ctx.extracted_items
            if item.track.type == "video" and item.track.source == "Source 1"
        ]

        if not video_items:
            runner._log_message("[VideoCorrection] No Source 1 video tracks, skipping")
            return ctx

        for item in video_items:
            if item.extracted_path is None:
                runner._log_message(
                    f"[VideoCorrection] Track {item.track.id} has no extracted path, "
                    f"skipping"
                )
                continue

            codec_id = item.track.props.codec_id

            # --- Detection ---
            detection = detect_pulldown(
                extracted_path=item.extracted_path,
                codec_id=codec_id,
                log=runner._log_message,
            )

            if not detection.detected:
                runner._log_message(
                    f"[VideoCorrection] Track {item.track.id}: {detection.reason}"
                )
                continue

            if not detection.safe_to_remove:
                runner._log_message(
                    f"[VideoCorrection] Track {item.track.id}: Pulldown detected but "
                    f"NOT safe to remove — {detection.reason}"
                )
                continue

            if detection.scan_result is None:
                runner._log_message(
                    f"[VideoCorrection] Track {item.track.id}: No scan result available"
                )
                continue

            # --- Removal ---
            # Output to a separate file in the same temp folder
            original_path = item.extracted_path
            output_path = original_path.with_stem(
                original_path.stem + "_pulldown_removed"
            )

            runner._log_message(
                f"[VideoCorrection] Removing soft pulldown from track {item.track.id}: "
                f"{detection.source_fps:.3f} fps → {detection.target_fps:.3f} fps"
                if detection.target_fps
                else f"[VideoCorrection] Removing soft pulldown from track {item.track.id}"
            )

            result = remove_pulldown(
                es_path=original_path,
                scan=detection.scan_result,
                output_path=output_path,
            )

            if result.success:
                runner._log_message(
                    f"[VideoCorrection] Pulldown removed successfully: "
                    f"{result.pictures_modified} picture headers modified, "
                    f"{result.sequence_headers_modified} sequence headers updated"
                )
                runner._log_message(
                    f"[VideoCorrection] Original kept at: {original_path.name}"
                )
                runner._log_message(
                    f"[VideoCorrection] Corrected stream: {output_path.name}"
                )

                # Update the PlanItem to use the corrected file for muxing
                item.extracted_path = output_path
                item.pulldown_removed = True

                # Record info in context for audit/reporting
                ctx.pulldown_removal_info = PulldownRemovalInfo(
                    source_fps=result.original_rate,
                    target_fps=result.new_rate,
                    pictures_modified=result.pictures_modified,
                    sequence_headers_modified=result.sequence_headers_modified,
                )

                # Log to audit trail
                if ctx.audit:
                    ctx.audit.append_event(
                        "video_correction",
                        "Soft pulldown removed from MPEG-2 video",
                        {
                            "track_id": item.track.id,
                            "original_file": str(original_path.name),
                            "corrected_file": str(output_path.name),
                            "original_fps": result.original_rate,
                            "new_fps": result.new_rate,
                            "pictures_modified": result.pictures_modified,
                            "sequence_headers_modified": result.sequence_headers_modified,
                        },
                    )
            else:
                runner._log_message(
                    f"[VideoCorrection] Pulldown removal FAILED for track "
                    f"{item.track.id}: {result.reason}"
                )
                runner._log_message(
                    "[VideoCorrection] Original stream will be used unchanged"
                )

        return ctx
