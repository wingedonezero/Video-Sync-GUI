# vsg_core/postprocess/final_auditor.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from vsg_core.orchestrator.steps.context import Context
from vsg_core.io.runner import CommandRunner
from vsg_core.models.enums import TrackType
from vsg_core.models.jobs import PlanItem

class FinalAuditor:
    """
    A SAFER version that only logs warnings instead of trying to "fix" things.
    The original was too aggressive and could corrupt files.
    """
    def __init__(self, ctx: Context, runner: CommandRunner):
        self.ctx = ctx
        self.runner = runner
        self.tool_paths = ctx.tool_paths
        self.log = runner._log_message
        self._source_ffprobe_cache: Dict[str, Optional[Dict]] = {}
        self._source_mkvmerge_cache: Dict[str, Optional[Dict]] = {}

    def run(self, final_mkv_path: Path):
        """
        Comprehensive audit of the final file - checks everything but modifies nothing.
        """
        self.log("--- Post-Merge: Running Final Audit ---")

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

        # Audit track flags
        self.log("--- Auditing Track Flags (Default/Forced) ---")
        flag_issues = self._audit_track_flags(final_tracks, final_plan_items)
        total_issues += flag_issues

        # Get detailed ffprobe data for advanced checks
        final_ffprobe_data = self._get_metadata(str(final_mkv_path), 'ffprobe')
        if final_ffprobe_data:
            final_streams = final_ffprobe_data.get('streams', [])

            # Check HDR/DV/Color metadata
            self.log("--- Auditing Video Core Metadata (HDR, 3D, Color) ---")
            video_issues = self._audit_video_metadata_detailed(final_streams, final_mkvmerge_data, final_plan_items)
            total_issues += video_issues

            # Check Dolby Vision
            self.log("--- Auditing Dolby Vision Metadata ---")
            dv_issues = self._audit_dolby_vision(final_streams, final_plan_items)
            total_issues += dv_issues

            # Check Object-Based Audio
            self.log("--- Auditing Object-Based Audio (Atmos/DTS:X) ---")
            audio_issues = self._audit_object_based_audio(final_streams, final_plan_items)
            total_issues += audio_issues

        # Check attachments
        self.log("--- Auditing Attachments ---")
        self._audit_attachments(final_mkvmerge_data.get('attachments', []))

        # Final summary
        if total_issues == 0:
            self.log("✅ Final audit passed. No issues found.")
        else:
            self.log(f"⚠️ Final audit found {total_issues} potential issue(s). Please review the warnings above.")

    def _audit_track_flags(self, actual_tracks: List[Dict], plan_items: List[PlanItem]) -> int:
        """
        Compares expected vs actual flags and logs warnings.
        Returns the number of issues found.
        """
        issues = 0

        # Group tracks by type for proper default flag checking
        video_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'video']
        audio_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'audio']
        subtitle_tracks = [(i, t) for i, t in enumerate(actual_tracks) if t.get('type') == 'subtitles']

        # Check if there's exactly one default per type (where it matters)
        default_videos = sum(1 for _, t in video_tracks if t.get('properties', {}).get('default_track', False))
        default_audios = sum(1 for _, t in audio_tracks if t.get('properties', {}).get('default_track', False))
        default_subs = sum(1 for _, t in subtitle_tracks if t.get('properties', {}).get('default_track', False))

        if default_videos > 1:
            self.log(f"[WARNING] Multiple default video tracks found ({default_videos}). Players may behave unexpectedly.")
            issues += 1

        if default_audios == 0 and audio_tracks:
            self.log("[WARNING] No default audio track set. Some players may not play audio automatically.")
            issues += 1
        elif default_audios > 1:
            self.log(f"[WARNING] Multiple default audio tracks found ({default_audios}).")
            issues += 1

        if default_subs > 1:
            self.log(f"[WARNING] Multiple default subtitle tracks found ({default_subs}).")
            issues += 1

        # Check forced flags on subtitles
        forced_subs = sum(1 for _, t in subtitle_tracks if t.get('properties', {}).get('forced_track', False))
        if forced_subs > 1:
            self.log(f"[WARNING] Multiple forced subtitle tracks found ({forced_subs}). Only one should be forced.")
            issues += 1

        return issues

    def _audit_video_metadata_detailed(self, actual_streams: List[Dict], actual_mkvmerge_data: Dict, plan_items: List[PlanItem]) -> int:
        """Comprehensive check of video metadata preservation."""
        issues = 0
        video_items = [item for item in plan_items if item.track.type == TrackType.VIDEO]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            # Get both mkvmerge and ffprobe data for the source
            source_mkv_data = self._get_metadata(source_file, 'mkvmerge')
            source_ffprobe_data = self._get_metadata(source_file, 'ffprobe')
            if not source_ffprobe_data:
                continue

            source_video = next((s for s in source_ffprobe_data.get('streams', []) if s.get('codec_type') == 'video'), None)
            actual_video = next((s for s in actual_streams if s.get('codec_type') == 'video'), None)

            if not source_video or not actual_video:
                continue

            # Check resolution
            if source_video.get('width') != actual_video.get('width') or source_video.get('height') != actual_video.get('height'):
                self.log(f"[WARNING] Resolution mismatch! Source: {source_video.get('width')}x{source_video.get('height')}, "
                        f"Output: {actual_video.get('width')}x{actual_video.get('height')}")
                issues += 1

            # Check interlacing/field order (CRITICAL for telecined content)
            source_field_order = source_video.get('field_order', 'progressive')
            actual_field_order = actual_video.get('field_order', 'progressive')

            if source_field_order != actual_field_order:
                self.log(f"[WARNING] Field order mismatch! Source: '{source_field_order}', Output: '{actual_field_order}'")
                if source_field_order in ['tt', 'bb', 'tb', 'bt'] and actual_field_order == 'progressive':
                    self.log("         CRITICAL: Interlaced content marked as progressive! This will cause playback issues.")
                issues += 1

            # Check for telecine patterns in codec level
            source_codec_tag = source_video.get('codec_tag_string', '')
            actual_codec_tag = actual_video.get('codec_tag_string', '')

            # Check MKV-specific field order from mkvmerge data
            if source_mkv_data:
                source_mkv_video = next((t for t in source_mkv_data.get('tracks', []) if t.get('type') == 'video'), None)
                actual_mkv_video = next((t for t in actual_mkvmerge_data.get('tracks', []) if t.get('type') == 'video'), None)

                if source_mkv_video and actual_mkv_video:
                    source_mkv_field = source_mkv_video.get('properties', {}).get('field_order')
                    actual_mkv_field = actual_mkv_video.get('properties', {}).get('field_order')

                    if source_mkv_field != actual_mkv_field:
                        self.log(f"[WARNING] MKV field_order flag mismatch! Source: {source_mkv_field}, Output: {actual_mkv_field}")
                        if source_mkv_field and not actual_mkv_field:
                            self.log("         Field order information was lost! May cause deinterlacing issues.")
                        issues += 1

                    # Check stereo mode (3D)
                    source_stereo = source_mkv_video.get('properties', {}).get('stereo_mode')
                    actual_stereo = actual_mkv_video.get('properties', {}).get('stereo_mode')

                    if source_stereo != actual_stereo:
                        self.log(f"[WARNING] Stereo mode (3D) mismatch! Source: {source_stereo}, Output: {actual_stereo}")
                        issues += 1

            # Check HDR metadata in detail
            source_color_transfer = source_video.get('color_transfer', '')
            actual_color_transfer = actual_video.get('color_transfer', '')

            if source_color_transfer and source_color_transfer != actual_color_transfer:
                self.log(f"[WARNING] Color transfer mismatch! Source: '{source_color_transfer}', Output: '{actual_color_transfer}'")
                if source_color_transfer == 'smpte2084':
                    self.log("         HDR10 metadata was lost!")
                elif source_color_transfer == 'arib-std-b67':
                    self.log("         HLG metadata was lost!")
                issues += 1

            # Check color primaries
            if source_video.get('color_primaries') != actual_video.get('color_primaries'):
                self.log(f"[WARNING] Color primaries mismatch! Source: '{source_video.get('color_primaries')}', "
                        f"Output: '{actual_video.get('color_primaries')}'")
                issues += 1

            # Check color space/matrix coefficients
            if source_video.get('color_space') != actual_video.get('color_space'):
                self.log(f"[WARNING] Color space mismatch! Source: '{source_video.get('color_space')}', "
                        f"Output: '{actual_video.get('color_space')}'")
                issues += 1

            # Check pixel format (important for HDR)
            if source_video.get('pix_fmt') != actual_video.get('pix_fmt'):
                self.log(f"[WARNING] Pixel format mismatch! Source: '{source_video.get('pix_fmt')}', "
                        f"Output: '{actual_video.get('pix_fmt')}'")
                if 'yuv420p10' in source_video.get('pix_fmt', '') and 'yuv420p' in actual_video.get('pix_fmt', ''):
                    self.log("         CRITICAL: 10-bit video downgraded to 8-bit!")
                issues += 1

            # Check color range (limited vs full)
            if source_video.get('color_range') != actual_video.get('color_range'):
                self.log(f"[WARNING] Color range mismatch! Source: '{source_video.get('color_range')}', "
                        f"Output: '{actual_video.get('color_range')}'")
                issues += 1

            # Check chroma location
            if source_video.get('chroma_location') != actual_video.get('chroma_location'):
                self.log(f"[WARNING] Chroma location mismatch! Source: '{source_video.get('chroma_location')}', "
                        f"Output: '{actual_video.get('chroma_location')}'")
                issues += 1

            # Check aspect ratios
            source_dar = source_video.get('display_aspect_ratio')
            actual_dar = actual_video.get('display_aspect_ratio')
            if source_dar != actual_dar:
                self.log(f"[WARNING] Display aspect ratio mismatch! Source: '{source_dar}', Output: '{actual_dar}'")
                issues += 1

            # Check frame rate (should match exactly)
            source_fps = source_video.get('avg_frame_rate')
            actual_fps = actual_video.get('avg_frame_rate')
            if source_fps != actual_fps:
                self.log(f"[WARNING] Frame rate mismatch! Source: '{source_fps}', Output: '{actual_fps}'")
                issues += 1

            # Check mastering display metadata
            source_mastering = self._get_mastering_display(source_video)
            actual_mastering = self._get_mastering_display(actual_video)

            if source_mastering and not actual_mastering:
                self.log("[WARNING] Mastering display metadata (HDR10) was lost during merge!")
                self.log(f"         Lost data: {source_mastering}")
                issues += 1
            elif source_mastering and actual_mastering:
                # Check if values match
                for key in ['red_x', 'red_y', 'green_x', 'green_y', 'blue_x', 'blue_y',
                           'white_point_x', 'white_point_y', 'max_luminance', 'min_luminance']:
                    if source_mastering.get(key) != actual_mastering.get(key):
                        self.log(f"[WARNING] Mastering display {key} mismatch!")
                        issues += 1

            # Check content light level
            source_cll = self._get_content_light_level(source_video)
            actual_cll = self._get_content_light_level(actual_video)

            if source_cll and not actual_cll:
                self.log("[WARNING] Content light level metadata (MaxCLL/MaxFALL) was lost during merge!")
                self.log(f"         Lost data: MaxCLL={source_cll.get('max_content')}, MaxFALL={source_cll.get('max_average')}")
                issues += 1
            elif source_cll and actual_cll:
                if source_cll.get('max_content') != actual_cll.get('max_content') or \
                   source_cll.get('max_average') != actual_cll.get('max_average'):
                    self.log(f"[WARNING] Content light level mismatch! "
                            f"Source: MaxCLL={source_cll.get('max_content')}/MaxFALL={source_cll.get('max_average')}, "
                            f"Output: MaxCLL={actual_cll.get('max_content')}/MaxFALL={actual_cll.get('max_average')}")
                    issues += 1

        if issues == 0:
            self.log("✅ All video metadata preserved correctly.")

        return issues

    def _audit_dolby_vision(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """Detailed Dolby Vision metadata check."""
        issues = 0
        video_items = [item for item in plan_items if item.track.type == TrackType.VIDEO]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            source_video = next((s for s in source_data.get('streams', []) if s.get('codec_type') == 'video'), None)
            actual_video = next((s for s in actual_streams if s.get('codec_type') == 'video'), None)

            if not source_video or not actual_video:
                continue

            source_has_dv = self._has_dolby_vision(source_video)
            actual_has_dv = self._has_dolby_vision(actual_video)

            if source_has_dv and not actual_has_dv:
                self.log("[WARNING] Dolby Vision metadata was present in source but is MISSING from the output!")
                self.log("         This is a significant quality loss for compatible displays.")
                issues += 1
            elif source_has_dv and actual_has_dv:
                self.log("✅ Dolby Vision metadata preserved successfully.")

        if not any(self._has_dolby_vision(next((s for s in self._get_metadata(self.ctx.sources.get(item.track.source), 'ffprobe').get('streams', [])
                                               if s.get('codec_type') == 'video'), {}))
                  for item in video_items if item.track.type == TrackType.VIDEO and self.ctx.sources.get(item.track.source)):
            self.log("✅ No Dolby Vision metadata to preserve.")

        return issues

    def _audit_object_based_audio(self, actual_streams: List[Dict], plan_items: List[PlanItem]) -> int:
        """Detailed object-based audio check."""
        issues = 0
        audio_items = [item for item in plan_items if item.track.type == TrackType.AUDIO]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            # Find the matching audio stream in source
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id < len(source_audio_streams):
                source_audio = source_audio_streams[plan_item.track.id]
            else:
                continue

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            for i, item in enumerate([it for it in plan_items if it.track.type == TrackType.AUDIO]):
                if item == plan_item and i < len(actual_audio_streams):
                    actual_audio = actual_audio_streams[i]
                    break

            if not actual_audio:
                continue

            source_profile = source_audio.get('profile', '')
            actual_profile = actual_audio.get('profile', '')

            # Check for Atmos
            if 'Atmos' in source_profile and 'Atmos' not in actual_profile:
                self.log(f"[WARNING] Dolby Atmos metadata was lost for audio track from {plan_item.track.source}!")
                issues += 1
            elif 'Atmos' in source_profile and 'Atmos' in actual_profile:
                self.log(f"✅ Dolby Atmos preserved for track from {plan_item.track.source}.")

            # Check for DTS:X
            if 'DTS:X' in source_profile and 'DTS:X' not in actual_profile:
                self.log(f"[WARNING] DTS:X metadata was lost for audio track from {plan_item.track.source}!")
                issues += 1
            elif 'DTS:X' in source_profile and 'DTS:X' in actual_profile:
                self.log(f"✅ DTS:X preserved for track from {plan_item.track.source}.")

        if issues == 0:
            self.log("✅ All object-based audio metadata preserved correctly.")

        return issues

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

    def _audit_attachments(self, actual_attachments: List[Dict]):
        """Checks if expected attachments are present."""
        if not self.ctx.attachments:
            if not actual_attachments:
                self.log("✅ No attachments were planned or found.")
            else:
                self.log(f"[INFO] File contains {len(actual_attachments)} attachment(s) (likely from source files).")
            return

        expected_count = len(self.ctx.attachments)
        actual_count = len(actual_attachments)

        if actual_count < expected_count:
            self.log(f"[WARNING] Expected {expected_count} attachments but only found {actual_count}.")
            self.log("         Some fonts may be missing, which could affect subtitle rendering.")
        else:
            self.log(f"✅ Found {actual_count} attachment(s) as expected.")

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

            out = self.runner.run(cmd, self.tool_paths)
            return json.loads(out) if out else None
        except (json.JSONDecodeError, Exception) as e:
            self.log(f"[ERROR] Failed to get {tool} metadata: {e}")
            return None
