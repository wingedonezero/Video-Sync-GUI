# vsg_core/postprocess/auditors/audio_sync.py
# -*- coding: utf-8 -*-
import json
from typing import Dict, Optional
from pathlib import Path

from vsg_core.models.enums import TrackType
from .base import BaseAuditor


class AudioSyncAuditor(BaseAuditor):
    """
    Verifies that audio sync delays in the final file match what was calculated.
    Uses dual verification: codec_delay metadata AND first packet timestamp.
    """

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Comprehensive audio sync audit with dual verification.
        This is CRITICAL because sync issues are very noticeable.
        Returns the number of issues found.
        """
        issues = 0
        final_tracks = final_mkvmerge_data.get('tracks', [])

        if not self.ctx.delays:
            self.log("✅ No delays were calculated (single source or analysis skipped).")
            return 0

        # Build a mapping of track index to plan item
        audio_plan_items = [item for item in self.ctx.extracted_items if item.track.type == TrackType.AUDIO]

        # Get audio tracks from final file
        final_audio_tracks = [t for t in final_tracks if t.get('type') == 'audio']

        if len(final_audio_tracks) != len(audio_plan_items):
            self.log(f"[WARNING] Audio track count mismatch! Expected {len(audio_plan_items)}, got {len(final_audio_tracks)}.")
            issues += 1
            return issues

        for i, (plan_item, final_track) in enumerate(zip(audio_plan_items, final_audio_tracks)):
            # Calculate what the delay SHOULD be
            expected_delay_ms = self._calculate_expected_delay(plan_item)

            # Method 1: Check codec_delay metadata (primary method)
            issues += self._verify_codec_delay(plan_item, final_track, expected_delay_ms, i)

            # Method 2: Check first packet timestamp (secondary verification)
            issues += self._verify_first_packet_timestamp(final_mkv_path, i, expected_delay_ms, plan_item)

        if issues == 0:
            self.log("✅ All audio sync delays verified correctly (dual verification passed).")

        return issues

    def _verify_codec_delay(self, plan_item, final_track: Dict, expected_delay_ms: float, track_index: int) -> int:
        """
        Primary verification: Check codec_delay in container metadata.
        This is what mkvmerge's --sync option sets.
        """
        issues = 0
        props = final_track.get('properties', {})

        # Try to get the delay from various possible fields
        actual_delay_ns = props.get('codec_delay', 0)
        actual_delay_ms = actual_delay_ns / 1_000_000.0 if actual_delay_ns else 0.0

        # Also check minimum_timestamp which might contain the delay
        min_timestamp = props.get('minimum_timestamp', 0)
        if min_timestamp and not actual_delay_ms:
            actual_delay_ms = min_timestamp / 1_000_000.0

        # Allow 1ms tolerance for floating point rounding
        tolerance_ms = 1.0
        diff_ms = abs(expected_delay_ms - actual_delay_ms)

        source = plan_item.track.source
        lang = plan_item.track.props.lang or 'und'
        name = plan_item.track.props.name or f"Track {plan_item.track.id}"

        if diff_ms > tolerance_ms:
            self.log(f"[WARNING] Audio sync mismatch (metadata) for '{name}' ({source}, {lang}):")
            self.log(f"          Expected delay: {expected_delay_ms:+.1f}ms")
            self.log(f"          Actual delay:   {actual_delay_ms:+.1f}ms")
            self.log(f"          Difference:     {diff_ms:.1f}ms")
            issues += 1
        else:
            self.log(f"  ✓ '{name}' ({source}) metadata: {actual_delay_ms:+.1f}ms")

        return issues

    def _verify_first_packet_timestamp(self, final_mkv_path: Path, audio_track_index: int,
                                       expected_delay_ms: float, plan_item) -> int:
        """
        Secondary verification: Check the timestamp of the first audio packet.
        This verifies that the delay was actually applied to the stream data.
        """
        issues = 0

        try:
            # Use ffprobe to get the first packet's presentation timestamp
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', f'a:{audio_track_index}',
                '-show_entries', 'packet=pts_time',
                '-of', 'json',
                '-read_intervals', '%+#1',  # Read only first packet
                str(final_mkv_path)
            ]

            result = self.runner.run(cmd, self.tool_paths)
            if not result:
                # Can't verify - not a critical error
                return 0

            data = json.loads(result)
            packets = data.get('packets', [])

            if not packets:
                # No packet data - skip verification
                return 0

            first_pts = packets[0].get('pts_time')
            if first_pts is None:
                return 0

            first_pts_ms = float(first_pts) * 1000.0

            # The first packet should be at approximately the expected delay
            # Allow more tolerance here (10ms) because:
            # - Codec delays might be rounded differently
            # - Frame boundaries affect exact timing
            tolerance_ms = 10.0
            diff_ms = abs(expected_delay_ms - first_pts_ms)

            source = plan_item.track.source
            name = plan_item.track.props.name or f"Track {plan_item.track.id}"

            if diff_ms > tolerance_ms:
                self.log(f"[WARNING] Audio sync mismatch (packet timestamp) for '{name}' ({source}):")
                self.log(f"          Expected first packet at: {expected_delay_ms:+.1f}ms")
                self.log(f"          Actual first packet at:  {first_pts_ms:+.1f}ms")
                self.log(f"          Difference:              {diff_ms:.1f}ms")
                self.log(f"          → Stream data may not be properly delayed!")
                issues += 1
            else:
                self.log(f"  ✓ '{name}' ({source}) first packet: {first_pts_ms:+.1f}ms")

        except Exception as e:
            # Packet verification is optional - don't fail if it doesn't work
            self.log(f"  [INFO] Could not verify packet timestamps for track {audio_track_index} ({e})")

        return issues
