# vsg_core/postprocess/final_auditor.py
"""
Final Audit Orchestrator - Coordinates all post-merge validation checks.
Enhanced with drift correction and global shift auditors.
"""

import json
from pathlib import Path

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context

from .auditors import (
    AttachmentsAuditor,
    AudioChannelsAuditor,
    AudioObjectBasedAuditor,
    AudioQualityAuditor,
    AudioSyncAuditor,
    ChaptersAuditor,
    CodecIntegrityAuditor,
    DolbyVisionAuditor,
    DriftCorrectionAuditor,
    GlobalShiftAuditor,
    LanguageTagsAuditor,
    SteppingCorrectionAuditor,
    SubtitleClampingAuditor,
    SubtitleFormatsAuditor,
    TrackFlagsAuditor,
    TrackNamesAuditor,
    TrackOrderAuditor,
    VideoMetadataAuditor,
)


class FinalAuditor:
    """
    Comprehensive post-merge validation orchestrator.
    Runs all audit modules and aggregates results.
    """

    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.log = runner._log_message
        self._shared_ffprobe_cache: dict[str, dict | None] = {}
        self._shared_mkvmerge_cache: dict[str, dict | None] = {}

    def run(self, final_mkv_path: Path):
        """
        Comprehensive audit of the final file - checks everything but modifies nothing.
        """
        self.log("========================================")
        self.log("=== POST-MERGE FINAL AUDIT STARTING ===")
        self.log("========================================")

        # Detect if enhanced ffprobe is needed based on applied delays
        # Check if any track has a delay > 5000ms from the merge plan
        self.needs_enhanced_probe = False
        max_applied_delay = 0

        for item in self.ctx.extracted_items:
            # Calculate the actual delay applied (using same logic as options_builder)
            global_shift = self.ctx.delays.global_shift_ms if self.ctx.delays else 0

            if item.track.source == "Source 1":
                actual_delay = item.container_delay_ms + global_shift
            else:
                sync_key = (
                    item.sync_to
                    if item.track.source == "External"
                    else item.track.source
                )
                # Check subtitle-specific delays first, then fall back to correlation delays
                if item.track.type == "subtitles" and sync_key in self.ctx.subtitle_delays_ms:
                    actual_delay = round(self.ctx.subtitle_delays_ms.get(sync_key, 0))
                else:
                    actual_delay = (
                        self.ctx.delays.source_delays_ms.get(sync_key, 0)
                        if self.ctx.delays
                        else 0
                    )

            max_applied_delay = max(max_applied_delay, abs(actual_delay))

        if max_applied_delay > 5000:
            self.needs_enhanced_probe = True
            self.log(
                f"[INFO] Detected large sync delays (max: {max_applied_delay:.0f}ms). Enhanced ffprobe will be used for accurate metadata detection."
            )

        final_mkvmerge_data = self._get_metadata(str(final_mkv_path), "mkvmerge")
        if not final_mkvmerge_data or "tracks" not in final_mkvmerge_data:
            self.log("[ERROR] Could not read metadata from final file. Aborting audit.")
            return

        final_tracks = final_mkvmerge_data.get("tracks", [])

        has_preserved_tracks = any(
            item.is_preserved for item in self.ctx.extracted_items
        )

        if has_preserved_tracks:
            self.log(
                "[INFO] Preserved tracks found. Re-sorting audit plan to match final mux order."
            )

            original_plan_items = self.ctx.extracted_items

            final_items = [
                item for item in original_plan_items if not item.is_preserved
            ]
            preserved_audio = [
                item
                for item in original_plan_items
                if item.is_preserved and item.track.type == "audio"
            ]
            preserved_subs = [
                item
                for item in original_plan_items
                if item.is_preserved and item.track.type == "subtitles"
            ]

            if preserved_audio:
                last_audio_idx = -1
                for i, item in enumerate(final_items):
                    if item.track.type == "audio":
                        last_audio_idx = i
                if last_audio_idx != -1:
                    final_items[last_audio_idx + 1 : last_audio_idx + 1] = (
                        preserved_audio
                    )
                else:
                    final_items.extend(preserved_audio)

            if preserved_subs:
                last_sub_idx = -1
                for i, item in enumerate(final_items):
                    if item.track.type == "subtitles":
                        last_sub_idx = i
                if last_sub_idx != -1:
                    final_items[last_sub_idx + 1 : last_sub_idx + 1] = preserved_subs
                else:
                    final_items.extend(preserved_subs)

            self.ctx.extracted_items = final_items

        total_issues = 0

        final_plan_items = self.ctx.extracted_items

        if len(final_tracks) != len(final_plan_items):
            self.log(
                f"[WARNING] Track count mismatch! Plan expected {len(final_plan_items)}, but final file has {len(final_tracks)}."
            )
            total_issues += 1

        final_ffprobe_data = self._get_metadata(str(final_mkv_path), "ffprobe")

        self.log("\n--- Auditing Track Flags (Default/Forced) ---")
        auditor = TrackFlagsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        if final_ffprobe_data:
            self.log("\n--- Auditing Video Core Metadata (HDR, 3D, Color) ---")
            auditor = VideoMetadataAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

            self.log("\n--- Auditing Dolby Vision Metadata ---")
            auditor = DolbyVisionAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

            self.log("\n--- Auditing Object-Based Audio (Atmos/DTS:X) ---")
            auditor = AudioObjectBasedAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

            self.log("\n--- Auditing Codec Integrity ---")
            auditor = CodecIntegrityAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

            self.log("\n--- Auditing Audio Channel Layouts ---")
            auditor = AudioChannelsAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

            self.log("\n--- Auditing Audio Quality Parameters ---")
            auditor = AudioQualityAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(
                final_mkv_path, final_mkvmerge_data, final_ffprobe_data
            )

        self.log("\n--- Auditing Drift Corrections ---")
        auditor = DriftCorrectionAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Stepping Correction Quality ---")
        auditor = SteppingCorrectionAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Global Shift ---")
        auditor = GlobalShiftAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Audio Sync Delays ---")
        auditor = AudioSyncAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Subtitle Formats ---")
        auditor = SubtitleFormatsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing FrameLocked Subtitle Quality ---")
        total_issues += self._audit_framelocked_stats()

        self.log("\n--- Auditing Subtitle Timestamp Clamping ---")
        auditor = SubtitleClampingAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Chapters ---")
        auditor = ChaptersAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Track Order ---")
        auditor = TrackOrderAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Language Tags ---")
        auditor = LanguageTagsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Track Names ---")
        auditor = TrackNamesAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        self.log("\n--- Auditing Attachments ---")
        auditor = AttachmentsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(
            final_mkv_path, final_mkvmerge_data, final_ffprobe_data
        )

        # Check for stepping detected in source-separated sources (manual review needed)
        if self.ctx.stepping_detected_separated:
            self.log("\n--- WARNING: Stepping Detected in Source-Separated Sources ---")
            self.log(
                "[WARNING] Stepping patterns were detected in sources using source separation."
            )
            self.log(
                "[WARNING] Automatic stepping correction is unreliable on separated stems."
            )
            self.log("[WARNING] The following sources may have timing inconsistencies:")
            for source_key in self.ctx.stepping_detected_separated:
                self.log(
                    f"  - {source_key}: Stepping detected but correction skipped (source separation enabled)"
                )
            self.log("[RECOMMENDATION] Manually review sync quality for these sources.")
            self.log(
                "[RECOMMENDATION] If timing issues exist, consider re-syncing without source separation"
            )
            self.log("[RECOMMENDATION] if same-language audio tracks are available.")
            total_issues += len(self.ctx.stepping_detected_separated)

        self.log("\n========================================")
        if total_issues == 0:
            self.log("✅ FINAL AUDIT PASSED - NO ISSUES FOUND")
        else:
            self.log(f"⚠️  FINAL AUDIT FOUND {total_issues} POTENTIAL ISSUE(S)")
            self.log("    Please review the warnings above.")
        self.log("========================================\n")
        return total_issues

    def _audit_framelocked_stats(self) -> int:
        """Audit FrameLocked subtitle sync quality - report actual final duration changes."""
        issues = 0

        # Find all subtitle items that used FrameLocked sync
        framelocked_items = [
            item
            for item in self.ctx.extracted_items
            if hasattr(item, "framelocked_stats") and item.framelocked_stats
        ]

        if not framelocked_items:
            self.log("[INFO] No FrameLocked subtitles found - skipping audit")
            return 0

        for item in framelocked_items:
            stats = item.framelocked_stats
            track_name = item.track.props.name or f"Track {item.track.id}"

            # Get the actual final change stats
            final_duration_changed = stats.get("final_duration_changed", 0)
            final_end_adjusted = stats.get("final_end_adjusted", 0)
            total_events = stats.get("total_events", 0)

            self.log(f"[FrameLocked] {track_name}:")
            self.log(f"  - Total Events: {total_events}")
            self.log(f"  - Final Duration Changed: {final_duration_changed}")
            self.log(f"  - Final End Adjusted: {final_end_adjusted}")

            # Warn if durations were unexpectedly modified
            if final_duration_changed > 0:
                self.log(
                    f"[WARNING] {final_duration_changed} subtitle(s) had duration changes"
                )
                self.log(
                    "          This may indicate timing issues or intentional zero-duration effects becoming visible"
                )
                issues += 1

            # Warn if ends were adjusted beyond the global delay
            if final_end_adjusted > 0:
                self.log(
                    f"[WARNING] {final_end_adjusted} subtitle(s) had end times adjusted beyond delay"
                )
                self.log(
                    "          This may indicate duration modifications for frame visibility"
                )
                issues += 1

            if final_duration_changed == 0 and final_end_adjusted == 0:
                self.log(
                    "[OK] All durations preserved correctly (zero-duration effects stayed zero-duration)"
                )

        return issues

    def _get_metadata(self, file_path: str, tool: str) -> dict | None:
        """Gets metadata using either mkvmerge or ffprobe with enhanced probing for large delays."""
        try:
            if tool == "mkvmerge":
                cmd = ["mkvmerge", "-J", str(file_path)]
                out = self.runner.run(cmd, self.ctx.tool_paths)
                return json.loads(out) if out else None
            elif tool == "ffprobe":
                # Build ffprobe command
                cmd = ["ffprobe", "-v", "quiet", "-print_format", "json"]

                # Use enhanced probe parameters if large delays were detected at audit start
                # This prevents ffprobe from failing to detect metadata due to large timestamp offsets
                if hasattr(self, "needs_enhanced_probe") and self.needs_enhanced_probe:
                    # analyzeduration: 30 seconds (30000M microseconds) - matches typical correlation window
                    # probesize: 100MB - sufficient for most video streams
                    cmd += ["-analyzeduration", "30000M", "-probesize", "100M"]

                cmd += ["-show_streams", "-show_format", str(file_path)]
                out = self.runner.run(cmd, self.ctx.tool_paths)
                return json.loads(out) if out else None
            else:
                return None
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to get {tool} metadata: {e}")
            return None
