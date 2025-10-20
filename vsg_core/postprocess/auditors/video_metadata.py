# vsg_core/postprocess/auditors/video_metadata.py
# -*- coding: utf-8 -*-
from typing import Dict, Optional
from pathlib import Path

from vsg_core.models.enums import TrackType
from .base import BaseAuditor


class VideoMetadataAuditor(BaseAuditor):
    """Comprehensive check of video metadata preservation."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Audits video core metadata (HDR, 3D, Color).
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get('streams', [])
        video_items = [item for item in self.ctx.extracted_items if item.track.type == TrackType.VIDEO]

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

            # Check interlacing/field order
            source_field_order = source_video.get('field_order', 'progressive')
            actual_field_order = actual_video.get('field_order', 'progressive')

            if source_field_order != actual_field_order:
                self.log(f"[WARNING] Field order mismatch! Source: '{source_field_order}', Output: '{actual_field_order}'")
                if source_field_order in ['tt', 'bb', 'tb', 'bt'] and actual_field_order == 'progressive':
                    self.log("         CRITICAL: Interlaced content marked as progressive! This will cause playback issues.")
                issues += 1

            # Check MKV-specific field order from mkvmerge data
            if source_mkv_data:
                source_mkv_video = next((t for t in source_mkv_data.get('tracks', []) if t.get('type') == 'video'), None)
                actual_mkv_video = next((t for t in final_mkvmerge_data.get('tracks', []) if t.get('type') == 'video'), None)

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

            # Check color primaries, space, range, chroma location
            for attr, label in [('color_primaries', 'Color primaries'), ('color_space', 'Color space'),
                                ('color_range', 'Color range'), ('chroma_location', 'Chroma location')]:
                if source_video.get(attr) != actual_video.get(attr):
                    self.log(f"[WARNING] {label} mismatch! Source: '{source_video.get(attr)}', Output: '{actual_video.get(attr)}'")
                    issues += 1

            # Check pixel format (important for HDR)
            if source_video.get('pix_fmt') != actual_video.get('pix_fmt'):
                self.log(f"[WARNING] Pixel format mismatch! Source: '{source_video.get('pix_fmt')}', Output: '{actual_video.get('pix_fmt')}'")
                if 'yuv420p10' in source_video.get('pix_fmt', '') and 'yuv420p' in actual_video.get('pix_fmt', ''):
                    self.log("         CRITICAL: 10-bit video downgraded to 8-bit!")
                issues += 1

            # Check chroma subsampling (critical for quality)
            source_chroma = self._get_chroma_subsampling(source_video.get('pix_fmt', ''))
            actual_chroma = self._get_chroma_subsampling(actual_video.get('pix_fmt', ''))

            if source_chroma and actual_chroma and source_chroma != actual_chroma:
                self.log(f"[WARNING] Chroma subsampling mismatch!")
                self.log(f"          Source: {source_chroma}")
                self.log(f"          Output: {actual_chroma}")

                # Determine severity
                chroma_quality = {'4:4:4': 3, '4:2:2': 2, '4:2:0': 1}
                source_quality = chroma_quality.get(source_chroma, 0)
                actual_quality = chroma_quality.get(actual_chroma, 0)

                if actual_quality < source_quality:
                    self.log(f"         CRITICAL: Chroma subsampling was downgraded (quality loss)!")

                issues += 1
            elif source_chroma and actual_chroma:
                self.log(f"  ✓ Chroma subsampling preserved: {actual_chroma}")

            # Check aspect ratios - must match exactly
            source_dar = source_video.get('display_aspect_ratio')
            actual_dar = actual_video.get('display_aspect_ratio')

            if source_dar != actual_dar:
                self.log(f"[WARNING] Display aspect ratio mismatch! Source: '{source_dar}', Output: '{actual_dar}'")
                issues += 1

            # Check frame rate
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

    def _get_chroma_subsampling(self, pix_fmt: str) -> Optional[str]:
        """
        Extract chroma subsampling pattern from pixel format string.

        Returns:
            '4:4:4', '4:2:2', '4:2:0', or None if unknown
        """
        if not pix_fmt:
            return None

        pix_fmt_lower = pix_fmt.lower()

        # 4:4:4 formats (no chroma subsampling)
        if any(x in pix_fmt_lower for x in ['yuv444', 'rgb', 'gbrp', 'gbrap']):
            return '4:4:4'

        # 4:2:2 formats (horizontal subsampling)
        if any(x in pix_fmt_lower for x in ['yuv422', 'yuyv422', 'uyvy422']):
            return '4:2:2'

        # 4:2:0 formats (horizontal and vertical subsampling - most common)
        if any(x in pix_fmt_lower for x in ['yuv420', 'nv12', 'nv21']):
            return '4:2:0'

        # 4:1:1 formats (rare)
        if 'yuv411' in pix_fmt_lower:
            return '4:1:1'

        # Unknown format
        return None
