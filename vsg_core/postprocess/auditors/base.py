# vsg_core/postprocess/auditors/base.py
# -*- coding: utf-8 -*-
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType
from vsg_core.models.jobs import PlanItem


class BaseAuditor:
    """
    Base class for all audit modules. Provides shared utilities and interface.
    """
    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.tool_paths = ctx.tool_paths
        self.log = runner._log_message
        self._source_ffprobe_cache: Dict[str, Optional[Dict]] = {}
        self._source_mkvmerge_cache: Dict[str, Optional[Dict]] = {}

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data: Optional[Dict] = None) -> int:
        """
        Main entry point for the auditor. Must be implemented by subclasses.

        Returns:
            Number of issues found
        """
        raise NotImplementedError("Subclasses must implement run()")

    # ========================================================================
    # SHARED UTILITY METHODS
    # ========================================================================

    def _get_metadata(self, file_path: str, tool: str) -> Optional[Dict]:
        """Gets metadata using either mkvmerge or ffprobe with caching and enhanced probing for large delays."""
        cache = self._source_mkvmerge_cache if tool == 'mkvmerge' else self._source_ffprobe_cache

        if file_path in cache:
            return cache[file_path]

        try:
            if tool == 'mkvmerge':
                cmd = ['mkvmerge', '-J', str(file_path)]
            elif tool == 'ffprobe':
                # Check if file has large timestamp offsets that require enhanced probing
                # First get mkvmerge data to detect delays (use cached if available)
                mkv_data = None
                if file_path in self._source_mkvmerge_cache:
                    mkv_data = self._source_mkvmerge_cache[file_path]
                else:
                    mkv_data = self._get_metadata(file_path, 'mkvmerge')

                max_delay_ms = 0
                if mkv_data:
                    for track in mkv_data.get('tracks', []):
                        min_ts = track.get('properties', {}).get('minimum_timestamp', 0)
                        if min_ts:
                            delay_ms = min_ts / 1_000_000  # Convert nanoseconds to milliseconds
                            max_delay_ms = max(max_delay_ms, delay_ms)

                # Build ffprobe command
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json']

                # If any track has a delay > 5000ms, use enhanced probe parameters
                # This prevents ffprobe from failing to detect metadata due to large timestamp offsets
                if max_delay_ms > 5000:
                    self.log(f"[INFO] Detected large timestamp offset ({max_delay_ms:.0f}ms) in {Path(file_path).name}. Using enhanced ffprobe parameters.")
                    # analyzeduration: 30 seconds (30000M microseconds) - matches typical correlation window
                    # probesize: 100MB - sufficient for most video streams
                    cmd += ['-analyzeduration', '30000M', '-probesize', '100M']

                cmd += ['-show_streams', '-show_format', str(file_path)]
            else:
                return None

            out = self.runner.run(cmd, self.tool_paths)
            result = json.loads(out) if out else None
            cache[file_path] = result
            return result
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to get {tool} metadata: {e}")
            cache[file_path] = None
            return None

    def _codecs_match(self, mkv_codec: str, ffprobe_codec: str) -> bool:
        """
        Compares codec identifiers from different sources (mkvmerge vs ffprobe).
        Returns True if they represent the same codec, even with different naming.
        """
        # Normalize both to uppercase for comparison
        mkv = mkv_codec.upper()
        ffp = ffprobe_codec.upper()

        # Direct match
        if mkv == ffp:
            return True

        # Create normalization mapping for common codecs
        codec_map = {
            # Video codecs
            'V_MPEGH/ISO/HEVC': 'HEVC',
            'HEVC': 'HEVC',
            'V_MPEG4/ISO/AVC': 'H264',
            'H264': 'H264',
            'V_MPEG2': 'MPEG2',
            'MPEG2VIDEO': 'MPEG2',
            'V_MPEG1': 'MPEG1',
            'MPEG1VIDEO': 'MPEG1',
            'V_VP9': 'VP9',
            'VP9': 'VP9',
            'V_AV1': 'AV1',
            'AV1': 'AV1',

            # Audio codecs
            'A_AC3': 'AC3',
            'AC3': 'AC3',
            'A_EAC3': 'EAC3',
            'EAC3': 'EAC3',
            'A_DTS': 'DTS',
            'DTS': 'DTS',
            'A_TRUEHD': 'TRUEHD',
            'TRUEHD': 'TRUEHD',
            'A_FLAC': 'FLAC',
            'FLAC': 'FLAC',
            'A_AAC': 'AAC',
            'AAC': 'AAC',
            'A_OPUS': 'OPUS',
            'OPUS': 'OPUS',
            'A_VORBIS': 'VORBIS',
            'VORBIS': 'VORBIS',

            # Subtitle codecs
            'S_HDMV/PGS': 'PGS',
            'HDMV_PGS_SUBTITLE': 'PGS',
            'S_TEXT/UTF8': 'SRT',
            'SUBRIP': 'SRT',
            'S_TEXT/ASS': 'ASS',
            'ASS': 'ASS',
            'S_TEXT/SSA': 'SSA',
            'SSA': 'SSA',
            'S_VOBSUB': 'VOBSUB',
            'DVD_SUBTITLE': 'VOBSUB', # THE FIX
        }

        # Normalize both codecs
        normalized_mkv = codec_map.get(mkv, mkv)
        normalized_ffp = codec_map.get(ffp, ffp)

        if normalized_mkv == normalized_ffp:
            return True

        # Handle PCM variants (all PCM types are compatible)
        if 'PCM' in mkv or mkv.startswith('A_PCM'):
            if ffp.startswith('PCM'):
                return True

        # No match found
        return False

    def _calculate_expected_delay(self, plan_item: PlanItem) -> float:
        """
        Calculates what the delay SHOULD be for a given track based on the pipeline logic.
        This mirrors the logic in options_builder.py
        """
        tr = plan_item.track
        global_shift = self.ctx.delays.global_shift_ms if self.ctx.delays else 0

        # Source 1 tracks use their original container delays PLUS the global shift
        # BUT: Only for audio/video, never for subtitles
        if tr.source == "Source 1" and tr.type != TrackType.SUBTITLES:
            return float(plan_item.container_delay_ms + global_shift)

        # For other sources, the delay from the context already includes the global shift
        sync_key = plan_item.sync_to if tr.source == 'External' else tr.source
        delay = self.ctx.delays.source_delays_ms.get(sync_key, 0)

        return float(delay)

    def _get_mastering_display(self, stream: Dict) -> Optional[Dict]:
        """Extracts mastering display metadata from a stream."""
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') == 'Mastering display metadata':
                return side_data
        return None

    def _get_content_light_level(self, stream: Dict) -> Optional[Dict]:
        """Extracts content light level metadata from a stream."""
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') == 'Content light level metadata':
                return side_data
        return None

    def _has_hdr_metadata(self, stream: Dict) -> bool:
        """Checks if a video stream has HDR metadata."""
        # Check for HDR transfer characteristics
        color_transfer = stream.get('color_transfer', '')
        if color_transfer in ['smpte2084', 'arib-std-b67']:
            return True

        # Check for HDR side data
        for side_data in stream.get('side_data_list', []):
            if side_data.get('side_data_type') in ['Mastering display metadata', 'Content light level metadata']:
                return True

        return False

    def _has_dolby_vision(self, stream: Dict) -> bool:
        """Checks if a video stream has Dolby Vision metadata."""
        for side_data in stream.get('side_data_list', []):
            if 'DOVI configuration' in side_data.get('side_data_type', ''):
                return True
        return False
