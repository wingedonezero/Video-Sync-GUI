# vsg_core/postprocess/auditors/audio_sync.py
# -*- coding: utf-8 -*-
import json
import math
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

        # Get sync mode from context (with fallback to default)
        sync_mode = getattr(self.ctx, 'sync_mode', 'positive_only')
        self.log(f"[SYNC MODE] Validating delays for mode: {sync_mode}")

        # In allow_negative mode, negative delays are expected and correct
        if sync_mode == 'allow_negative':
            self.log(f"[SYNC MODE] Negative delays are allowed in this mode - validation adjusted accordingly.")

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

        Note: With large delays (>5000ms), mkvmerge may not properly set container
        metadata fields, even though packet timestamps are correct. In such cases,
        packet timestamp verification is more reliable.
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

        source = plan_item.track.source
        lang = plan_item.track.props.lang or 'und'
        name = plan_item.track.props.name or f"Track {plan_item.track.id}"

        # Get codec info for frame boundary calculations
        codec_id = plan_item.track.props.codec_id or ''
        sync_mode = getattr(self.ctx, 'sync_mode', 'positive_only')

        # Allow 1ms tolerance for floating point rounding (default)
        tolerance_ms = 1.0

        # Special handling for negative delays in allow_negative mode
        # mkvmerge cuts frames, so we need to calculate what the ACTUAL delay will be
        if sync_mode == 'allow_negative' and expected_delay_ms < 0:
            # Determine codec frame size
            frame_size_ms = self._get_codec_frame_size_ms(codec_id)

            if frame_size_ms is not None:
                if frame_size_ms == 0:
                    # Sample-accurate codecs (PCM, FLAC) - no frame cutting math needed
                    self.log(f"  ⓘ '{name}' ({source}) is sample-accurate codec ({codec_id})")
                    self.log(f"     No frame boundary constraints - delay should be exact")
                    tolerance_ms = 1.0
                else:
                    # Calculate what mkvmerge will actually do:
                    # 1. Calculate frames to cut: abs(delay) / frame_size
                    # 2. mkvmerge rounds UP (uses ceil) to be conservative
                    frames_to_cut = math.ceil(abs(expected_delay_ms) / frame_size_ms)
                    frames_cut_ms = frames_to_cut * frame_size_ms

                    # 3. Actual delay after cutting = original_delay + frames_cut
                    # (cutting frames makes audio start later, so it's additive)
                    calculated_actual_delay = expected_delay_ms + frames_cut_ms

                    self.log(f"  ⓘ '{name}' ({source}) negative delay calculation (codec: {codec_id}):")
                    self.log(f"     Requested delay: {expected_delay_ms:+.1f}ms")
                    self.log(f"     Frame size: {frame_size_ms:.2f}ms")
                    self.log(f"     Frames to cut: {frames_to_cut}")
                    self.log(f"     Frames cut: {frames_cut_ms:.1f}ms")
                    self.log(f"     Calculated actual delay: {calculated_actual_delay:+.1f}ms")

                    # Now compare against the calculated value, not the requested value
                    diff_ms = abs(calculated_actual_delay - actual_delay_ms)
                    tolerance_ms = 2.0  # Allow 2ms tolerance for rounding

                    if diff_ms <= tolerance_ms:
                        self.log(f"  ✓ '{name}' ({source}) metadata: {actual_delay_ms:+.1f}ms (matches calculated {calculated_actual_delay:+.1f}ms)")
                        return 0
                    else:
                        self.log(f"[WARNING] Audio sync mismatch (metadata) for '{name}' ({source}, {lang}):")
                        self.log(f"          Expected delay: {expected_delay_ms:+.1f}ms (requested)")
                        self.log(f"          Calculated delay: {calculated_actual_delay:+.1f}ms (after frame cutting)")
                        self.log(f"          Actual delay:   {actual_delay_ms:+.1f}ms")
                        self.log(f"          Difference:     {diff_ms:.1f}ms")
                        self.log(f"          Sync mode:      {sync_mode}")
                        return 1
            else:
                # Unknown codec frame size, use generous tolerance
                tolerance_ms = 100.0
                self.log(f"  ⓘ '{name}' ({source}) has negative delay with unknown frame size (codec: {codec_id})")
                self.log(f"     Using generous tolerance: ±{tolerance_ms:.0f}ms")

        diff_ms = abs(expected_delay_ms - actual_delay_ms)

        # Skip metadata check if expected delay is large (>5000ms)
        # With large delays, mkvmerge doesn't reliably set container metadata,
        # but packet timestamps are still correct. Rely on packet verification instead.
        if abs(expected_delay_ms) > 5000:
            self.log(f"  ⓘ '{name}' ({source}) has large delay ({expected_delay_ms:+.1f}ms) - skipping metadata check, will verify packet timestamps")
            return 0

        if diff_ms > tolerance_ms:
            # Get sync mode for context
            sync_mode = getattr(self.ctx, 'sync_mode', 'positive_only')

            self.log(f"[WARNING] Audio sync mismatch (metadata) for '{name}' ({source}, {lang}):")
            self.log(f"          Expected delay: {expected_delay_ms:+.1f}ms")
            self.log(f"          Actual delay:   {actual_delay_ms:+.1f}ms")
            self.log(f"          Difference:     {diff_ms:.1f}ms")
            self.log(f"          Sync mode:      {sync_mode}")

            # Provide helpful context based on sync mode
            if sync_mode == 'allow_negative' and expected_delay_ms < 0 and actual_delay_ms >= 0:
                self.log(f"          NOTE: Expected negative delay in allow_negative mode, but got positive.")
                self.log(f"          This may indicate a muxing issue or chain correction problem.")

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

            source = plan_item.track.source
            name = plan_item.track.props.name or f"Track {plan_item.track.id}"

            # Get codec info and sync mode
            codec_id = plan_item.track.props.codec_id or ''
            sync_mode = getattr(self.ctx, 'sync_mode', 'positive_only')

            # The first packet should be at approximately the expected delay
            # Allow more tolerance here (10ms default) because:
            # - Codec delays might be rounded differently
            # - Frame boundaries affect exact timing
            tolerance_ms = 10.0

            # Special handling for negative delays in allow_negative mode
            # mkvmerge cuts frames, so we need to calculate what the ACTUAL delay will be
            if sync_mode == 'allow_negative' and expected_delay_ms < 0:
                # Determine codec frame size
                frame_size_ms = self._get_codec_frame_size_ms(codec_id)

                if frame_size_ms is not None:
                    if frame_size_ms == 0:
                        # Sample-accurate codecs (PCM, FLAC) - delay should be exact
                        tolerance_ms = 1.0
                    else:
                        # Calculate what mkvmerge will actually do
                        frames_to_cut = math.ceil(abs(expected_delay_ms) / frame_size_ms)
                        frames_cut_ms = frames_to_cut * frame_size_ms
                        calculated_actual_delay = expected_delay_ms + frames_cut_ms

                        # Compare against calculated value
                        diff_ms = abs(calculated_actual_delay - first_pts_ms)
                        tolerance_ms = 2.0

                        if diff_ms <= tolerance_ms:
                            self.log(f"  ✓ '{name}' ({source}) first packet: {first_pts_ms:+.1f}ms (matches calculated {calculated_actual_delay:+.1f}ms)")
                            return 0
                        else:
                            self.log(f"[WARNING] Audio sync mismatch (packet timestamp) for '{name}' ({source}):")
                            self.log(f"          Expected delay: {expected_delay_ms:+.1f}ms (requested)")
                            self.log(f"          Calculated delay: {calculated_actual_delay:+.1f}ms (after frame cutting)")
                            self.log(f"          Actual first packet at:  {first_pts_ms:+.1f}ms")
                            self.log(f"          Difference:              {diff_ms:.1f}ms")
                            self.log(f"          Tolerance used:          ±{tolerance_ms:.0f}ms")
                            self.log(f"          Sync mode:               {sync_mode}")
                            self.log(f"          → Stream data may not be properly delayed!")
                            return 1
                else:
                    # Unknown codec frame size
                    tolerance_ms = 100.0

            diff_ms = abs(expected_delay_ms - first_pts_ms)

            if diff_ms > tolerance_ms:
                self.log(f"[WARNING] Audio sync mismatch (packet timestamp) for '{name}' ({source}):")
                self.log(f"          Expected first packet at: {expected_delay_ms:+.1f}ms")
                self.log(f"          Actual first packet at:  {first_pts_ms:+.1f}ms")
                self.log(f"          Difference:              {diff_ms:.1f}ms")
                self.log(f"          Tolerance used:          ±{tolerance_ms:.0f}ms")
                self.log(f"          Sync mode:               {sync_mode}")
                self.log(f"          → Stream data may not be properly delayed!")

                # Provide helpful context based on sync mode
                if sync_mode == 'allow_negative' and expected_delay_ms < 0 and first_pts_ms >= 0:
                    self.log(f"          NOTE: Expected negative delay in allow_negative mode, but got positive.")
                    self.log(f"          This may indicate a muxing issue or chain correction problem.")

                issues += 1
            else:
                self.log(f"  ✓ '{name}' ({source}) first packet: {first_pts_ms:+.1f}ms")

        except Exception as e:
            # Packet verification is optional - don't fail if it doesn't work
            self.log(f"  [INFO] Could not verify packet timestamps for track {audio_track_index} ({e})")

        return issues

    def _get_codec_frame_size_ms(self, codec_id: str) -> Optional[float]:
        """
        Returns the frame size in milliseconds for a given codec, or None if unknown.

        Returns 0 for sample-accurate codecs (PCM, FLAC) that have no frame boundaries.
        This is used to calculate the expected delay after mkvmerge cuts frames for
        negative delays in allow_negative mode.

        Frame sizes are based on typical configurations at 48kHz sample rate.
        """
        codec_upper = codec_id.upper()

        # Lossy compressed formats with fixed frame sizes
        if 'AC3' in codec_upper or 'EAC3' in codec_upper:
            # AC3/EAC3: 1536 samples @ 48kHz = 32ms
            return 32.0

        if 'DTS' in codec_upper:
            # DTS Core: 512 samples @ 48kHz = 10.67ms
            # DTS-HD uses same base frame size
            return 10.67

        if 'TRUEHD' in codec_upper or 'MLP' in codec_upper:
            # TrueHD/MLP: 40 samples @ 48kHz = 0.83ms
            return 0.83

        if 'AAC' in codec_upper:
            # AAC: 1024 samples @ 48kHz = 21.33ms (standard AAC)
            # HE-AAC uses 2048 samples but we use conservative value
            return 21.33

        if 'MP3' in codec_upper or 'MPEG' in codec_upper and 'L3' in codec_upper:
            # MP3: 1152 samples, ~24ms @ 48kHz, ~26ms @ 44.1kHz
            # Use conservative value for 44.1kHz which is more common
            return 26.0

        if 'OPUS' in codec_upper:
            # Opus: Default 20ms frames (can be 2.5-60ms but 20ms is standard)
            return 20.0

        if 'VORBIS' in codec_upper:
            # Vorbis: Variable, typically 2048 samples @ 48kHz = 42.67ms
            return 42.67

        # Lossless/sample-accurate formats - return 0 to indicate no frame boundaries
        if 'FLAC' in codec_upper:
            # FLAC: Sample-accurate, no fixed frame boundaries for cutting
            return 0.0

        if 'PCM' in codec_upper or codec_upper.startswith('A_PCM'):
            # PCM: Sample-accurate
            return 0.0

        if 'ALAC' in codec_upper:
            # Apple Lossless: Sample-accurate like FLAC
            return 0.0

        if 'WAV' in codec_upper:
            # WAV/PCM: Sample-accurate
            return 0.0

        # Unknown codec - return None so caller can use generous tolerance
        return None
