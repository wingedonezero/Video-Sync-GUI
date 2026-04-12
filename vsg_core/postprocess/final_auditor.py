# vsg_core/postprocess/final_auditor.py
"""
Final Audit Orchestrator - Coordinates all post-merge validation checks.

Each concrete auditor extends ``BaseAuditor`` and reports issues via
``self._report()`` / ``self._track_issue()``. This orchestrator runs them
all, collects their structured issues into a single list, and returns
both the total count and the list so the pipeline can surface the
details in the batch report dialog.
"""

import json
from pathlib import Path

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context

from .auditors import (
    AttachmentsAuditor,
    AudioChannelsAuditor,
    AudioDurationAuditor,
    AudioObjectBasedAuditor,
    AudioQualityAuditor,
    AudioSyncAuditor,
    AuditIssue,
    BaseAuditor,
    ChaptersAuditor,
    CodecIntegrityAuditor,
    DolbyVisionAuditor,
    DriftCorrectionAuditor,
    FrameAuditAuditor,
    FrameLockedAuditor,
    GlobalShiftAuditor,
    LanguageTagsAuditor,
    SlidingConfidenceAuditor,
    SteppingCorrectionAuditor,
    SteppingSeparatedAuditor,
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

    def run(self, final_mkv_path: Path) -> tuple[int, list[AuditIssue]]:
        """
        Comprehensive audit of the final file - checks everything but modifies nothing.

        Returns:
            (total_issues, collected_issues) tuple. ``total_issues`` is an int
            for backwards compatibility; ``collected_issues`` is the structured
            list of :class:`AuditIssue` to surface in the batch report.
        """
        self.log("========================================")
        self.log("=== POST-MERGE FINAL AUDIT STARTING ===")
        self.log("========================================")

        all_issues: list[AuditIssue] = []

        # Detect if enhanced ffprobe is needed based on applied delays
        # Check if any track has a delay > 5000ms from the merge plan
        self.needs_enhanced_probe = False
        max_applied_delay = 0

        for item in self.ctx.extracted_items or []:
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
                if (
                    item.track.type == "subtitles"
                    and sync_key in self.ctx.subtitle_delays_ms
                ):
                    actual_delay = round(
                        self.ctx.subtitle_delays_ms.get(sync_key or "", 0)
                    )
                else:
                    actual_delay = (
                        self.ctx.delays.source_delays_ms.get(sync_key or "", 0)
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
            return 0, all_issues

        final_tracks = final_mkvmerge_data.get("tracks", [])

        has_preserved_tracks = any(
            item.is_preserved for item in (self.ctx.extracted_items or [])
        )

        if has_preserved_tracks:
            self.log(
                "[INFO] Preserved tracks found. Re-sorting audit plan to match final mux order."
            )

            original_plan_items = self.ctx.extracted_items or []

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

        final_plan_items = self.ctx.extracted_items or []

        if len(final_tracks) != len(final_plan_items):
            msg = (
                f"Track count mismatch! Plan expected "
                f"{len(final_plan_items)}, but final file has "
                f"{len(final_tracks)}."
            )
            self.log(f"[WARNING] {msg}")
            all_issues.append(
                AuditIssue(
                    auditor="FinalAuditor",
                    severity="warning",
                    message=msg,
                )
            )

        final_ffprobe_data = self._get_metadata(str(final_mkv_path), "ffprobe")

        # ------------------------------------------------------------------
        # Auditor dispatch table. Each entry is (label, auditor_class,
        # needs_ffprobe). needs_ffprobe=True means the auditor requires
        # ffprobe data and is skipped if ffprobe metadata is unavailable.
        # ------------------------------------------------------------------
        auditors: list[tuple[str, type[BaseAuditor], bool]] = [
            ("Track Flags (Default/Forced)", TrackFlagsAuditor, False),
            ("Video Core Metadata (HDR, 3D, Color)", VideoMetadataAuditor, True),
            ("Dolby Vision Metadata", DolbyVisionAuditor, True),
            ("Object-Based Audio (Atmos/DTS:X)", AudioObjectBasedAuditor, True),
            ("Codec Integrity", CodecIntegrityAuditor, True),
            ("Audio Channel Layouts", AudioChannelsAuditor, True),
            ("Audio Quality Parameters", AudioQualityAuditor, True),
            ("Drift Corrections", DriftCorrectionAuditor, False),
            ("Stepping Correction Quality", SteppingCorrectionAuditor, False),
            (
                "Stepping Detected in Source-Separated Sources",
                SteppingSeparatedAuditor,
                False,
            ),
            ("Global Shift", GlobalShiftAuditor, False),
            ("Audio Sync Delays", AudioSyncAuditor, False),
            ("Audio Duration vs Video", AudioDurationAuditor, True),
            ("Subtitle Formats", SubtitleFormatsAuditor, False),
            (
                "Sliding-Window Verification Confidence",
                SlidingConfidenceAuditor,
                False,
            ),
            ("FrameLocked Subtitle Quality", FrameLockedAuditor, False),
            ("Frame Alignment (Rounding Drift)", FrameAuditAuditor, False),
            ("Subtitle Timestamp Clamping", SubtitleClampingAuditor, False),
            ("Chapters", ChaptersAuditor, False),
            ("Track Order", TrackOrderAuditor, False),
            ("Language Tags", LanguageTagsAuditor, False),
            ("Track Names", TrackNamesAuditor, False),
            ("Attachments", AttachmentsAuditor, False),
        ]

        for label, auditor_cls, needs_ffprobe in auditors:
            if needs_ffprobe and not final_ffprobe_data:
                continue
            self.log(f"\n--- Auditing {label} ---")
            auditor = auditor_cls(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            try:
                auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)
            except Exception as e:
                msg = f"{label}: auditor crashed with {type(e).__name__}: {e}"
                self.log(f"[ERROR] {msg}")
                all_issues.append(
                    AuditIssue(
                        auditor=auditor_cls.__name__.removesuffix("Auditor"),
                        severity="error",
                        message=msg,
                    )
                )
                continue
            all_issues.extend(auditor.issues)

        total_issues = len(all_issues)

        self.log("\n========================================")
        if total_issues == 0:
            self.log("✅ FINAL AUDIT PASSED - NO ISSUES FOUND")
        else:
            self.log(f"⚠️  FINAL AUDIT FOUND {total_issues} POTENTIAL ISSUE(S)")
            self.log("    Please review the warnings above.")
        self.log("========================================\n")
        return total_issues, all_issues

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
