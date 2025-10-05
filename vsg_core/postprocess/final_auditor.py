# vsg_core/postprocess/final_auditor.py
# -*- coding: utf-8 -*-
"""
Final Audit Orchestrator - Coordinates all post-merge validation checks.
Each specific audit is handled by a dedicated module in the auditors/ folder.
"""
import json
from pathlib import Path
from typing import Dict, Optional

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner

from .auditors import (
    TrackFlagsAuditor,
    VideoMetadataAuditor,
    DolbyVisionAuditor,
    AudioObjectBasedAuditor,
    CodecIntegrityAuditor,
    AudioChannelsAuditor,
    AudioQualityAuditor,
    AudioSyncAuditor,
    SubtitleFormatsAuditor,
    ChaptersAuditor,
    TrackOrderAuditor,
    LanguageTagsAuditor,
    TrackNamesAuditor,
    AttachmentsAuditor,
)


class FinalAuditor:
    """
    Comprehensive post-merge validation orchestrator.
    Runs all audit modules and aggregates results.
    Only logs warnings - does not attempt fixes (those indicate pipeline bugs).
    """
    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.log = runner._log_message
        # Shared caches for all auditors (performance optimization)
        self._shared_ffprobe_cache: Dict[str, Optional[Dict]] = {}
        self._shared_mkvmerge_cache: Dict[str, Optional[Dict]] = {}

    def run(self, final_mkv_path: Path):
        """
        Comprehensive audit of the final file - checks everything but modifies nothing.
        """
        self.log("========================================")
        self.log("=== POST-MERGE FINAL AUDIT STARTING ===")
        self.log("========================================")

        # Get metadata from the final file
        final_mkvmerge_data = self._get_metadata(str(final_mkv_path), 'mkvmerge')
        if not final_mkvmerge_data or 'tracks' not in final_mkvmerge_data:
            self.log("[ERROR] Could not read metadata from final file. Aborting audit.")
            return

        final_tracks = final_mkvmerge_data.get('tracks', [])
        final_plan_items = self.ctx.extracted_items
        total_issues = 0

        # Track count check
        if len(final_tracks) != len(final_plan_items):
            self.log(f"[WARNING] Track count mismatch! Plan expected {len(final_plan_items)}, but final file has {len(final_tracks)}.")
            total_issues += 1

        # Get detailed ffprobe data for advanced checks
        final_ffprobe_data = self._get_metadata(str(final_mkv_path), 'ffprobe')

        # === RUN ALL AUDIT MODULES ===
        # The order matters for logical grouping in the output

        self.log("\n--- Auditing Track Flags (Default/Forced) ---")
        auditor = TrackFlagsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        if final_ffprobe_data:
            self.log("\n--- Auditing Video Core Metadata (HDR, 3D, Color) ---")
            auditor = VideoMetadataAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

            self.log("\n--- Auditing Dolby Vision Metadata ---")
            auditor = DolbyVisionAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

            self.log("\n--- Auditing Object-Based Audio (Atmos/DTS:X) ---")
            auditor = AudioObjectBasedAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

            self.log("\n--- Auditing Codec Integrity ---")
            auditor = CodecIntegrityAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

            self.log("\n--- Auditing Audio Channel Layouts ---")
            auditor = AudioChannelsAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

            self.log("\n--- Auditing Audio Quality Parameters ---")
            auditor = AudioQualityAuditor(self.ctx, self.runner)
            auditor._source_ffprobe_cache = self._shared_ffprobe_cache
            auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
            total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Audio Sync Delays ---")
        auditor = AudioSyncAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Subtitle Formats ---")
        auditor = SubtitleFormatsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Chapters ---")
        auditor = ChaptersAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Track Order ---")
        auditor = TrackOrderAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Language Tags ---")
        auditor = LanguageTagsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Track Names ---")
        auditor = TrackNamesAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        self.log("\n--- Auditing Attachments ---")
        auditor = AttachmentsAuditor(self.ctx, self.runner)
        auditor._source_ffprobe_cache = self._shared_ffprobe_cache
        auditor._source_mkvmerge_cache = self._shared_mkvmerge_cache
        total_issues += auditor.run(final_mkv_path, final_mkvmerge_data, final_ffprobe_data)

        # Final summary
        self.log("\n========================================")
        if total_issues == 0:
            self.log("✅ FINAL AUDIT PASSED - NO ISSUES FOUND")
        else:
            self.log(f"⚠️  FINAL AUDIT FOUND {total_issues} POTENTIAL ISSUE(S)")
            self.log("    Please review the warnings above.")
        self.log("========================================\n")

    def _get_metadata(self, file_path: str, tool: str) -> Optional[Dict]:
        """Gets metadata using either mkvmerge or ffprobe."""
        try:
            if tool == 'mkvmerge':
                cmd = ['mkvmerge', '-J', str(file_path)]
            elif tool == 'ffprobe':
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                       '-show_streams', '-show_format', str(file_path)]
            else:
                return None

            out = self.runner.run(cmd, self.ctx.tool_paths)
            return json.loads(out) if out else None
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to get {tool} metadata: {e}")
            return None
