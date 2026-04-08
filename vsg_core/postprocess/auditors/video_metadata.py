# vsg_core/postprocess/auditors/video_metadata.py
from pathlib import Path

from .base import BaseAuditor


class VideoMetadataAuditor(BaseAuditor):
    """Comprehensive check of video metadata preservation."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Audits video core metadata (HDR, 3D, Color).
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        actual_streams = final_ffprobe_data.get("streams", [])
        video_items = [
            item for item in self.ctx.extracted_items if item.track.type == "video"
        ]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            # Get both mkvmerge and ffprobe data for the source
            source_mkv_data = self._get_metadata(source_file, "mkvmerge")
            source_ffprobe_data = self._get_metadata(source_file, "ffprobe")
            if not source_ffprobe_data:
                continue

            source_video = next(
                (
                    s
                    for s in source_ffprobe_data.get("streams", [])
                    if s.get("codec_type") == "video"
                ),
                None,
            )
            actual_video = next(
                (s for s in actual_streams if s.get("codec_type") == "video"), None
            )

            if not source_video or not actual_video:
                continue

            # Check resolution
            if source_video.get("width") != actual_video.get(
                "width"
            ) or source_video.get("height") != actual_video.get("height"):
                self._report(
                    f"Resolution mismatch! Source: "
                    f"{source_video.get('width')}x{source_video.get('height')}, "
                    f"Output: "
                    f"{actual_video.get('width')}x{actual_video.get('height')}"
                )

            # Check interlacing/field order
            source_field_order = source_video.get("field_order", "progressive")
            actual_field_order = actual_video.get("field_order", "progressive")

            if source_field_order != actual_field_order:
                critical_note = ""
                if (
                    source_field_order in ["tt", "bb", "tb", "bt"]
                    and actual_field_order == "progressive"
                ):
                    critical_note = (
                        " - CRITICAL: Interlaced content marked as "
                        "progressive, will cause playback issues"
                    )
                self._report(
                    f"Field order mismatch! Source: '{source_field_order}', "
                    f"Output: '{actual_field_order}'{critical_note}"
                )

            # Check MKV-specific field order from mkvmerge data
            if source_mkv_data:
                source_mkv_video = next(
                    (
                        t
                        for t in source_mkv_data.get("tracks", [])
                        if t.get("type") == "video"
                    ),
                    None,
                )
                actual_mkv_video = next(
                    (
                        t
                        for t in final_mkvmerge_data.get("tracks", [])
                        if t.get("type") == "video"
                    ),
                    None,
                )

                if source_mkv_video and actual_mkv_video:
                    source_mkv_field = source_mkv_video.get("properties", {}).get(
                        "field_order"
                    )
                    actual_mkv_field = actual_mkv_video.get("properties", {}).get(
                        "field_order"
                    )

                    if source_mkv_field != actual_mkv_field:
                        lost_note = (
                            " - field order information was lost, may cause "
                            "deinterlacing issues"
                            if source_mkv_field and not actual_mkv_field
                            else ""
                        )
                        self._report(
                            f"MKV field_order flag mismatch! Source: "
                            f"{source_mkv_field}, Output: "
                            f"{actual_mkv_field}{lost_note}"
                        )

                    # Check stereo mode (3D)
                    source_stereo = source_mkv_video.get("properties", {}).get(
                        "stereo_mode"
                    )
                    actual_stereo = actual_mkv_video.get("properties", {}).get(
                        "stereo_mode"
                    )

                    if source_stereo != actual_stereo:
                        self._report(
                            f"Stereo mode (3D) mismatch! Source: "
                            f"{source_stereo}, Output: {actual_stereo}"
                        )

            # Check HDR metadata in detail
            source_color_transfer = source_video.get("color_transfer", "")
            actual_color_transfer = actual_video.get("color_transfer", "")

            if source_color_transfer and source_color_transfer != actual_color_transfer:
                hdr_note = ""
                if source_color_transfer == "smpte2084":
                    hdr_note = " - HDR10 metadata was lost"
                elif source_color_transfer == "arib-std-b67":
                    hdr_note = " - HLG metadata was lost"
                self._report(
                    f"Color transfer mismatch! Source: "
                    f"'{source_color_transfer}', Output: "
                    f"'{actual_color_transfer}'{hdr_note}"
                )

            # Check color primaries, space, range, chroma location
            for attr, label in [
                ("color_primaries", "Color primaries"),
                ("color_space", "Color space"),
                ("color_range", "Color range"),
                ("chroma_location", "Chroma location"),
            ]:
                if source_video.get(attr) != actual_video.get(attr):
                    self._report(
                        f"{label} mismatch! Source: "
                        f"'{source_video.get(attr)}', Output: "
                        f"'{actual_video.get(attr)}'"
                    )

            # Check pixel format (important for HDR)
            if source_video.get("pix_fmt") != actual_video.get("pix_fmt"):
                pix_note = ""
                if "yuv420p10" in source_video.get(
                    "pix_fmt", ""
                ) and "yuv420p" in actual_video.get("pix_fmt", ""):
                    pix_note = " - CRITICAL: 10-bit video downgraded to 8-bit"
                self._report(
                    f"Pixel format mismatch! Source: "
                    f"'{source_video.get('pix_fmt')}', Output: "
                    f"'{actual_video.get('pix_fmt')}'{pix_note}"
                )

            # Check chroma subsampling (critical for quality)
            source_chroma = self._get_chroma_subsampling(
                source_video.get("pix_fmt", "")
            )
            actual_chroma = self._get_chroma_subsampling(
                actual_video.get("pix_fmt", "")
            )

            if source_chroma and actual_chroma and source_chroma != actual_chroma:
                # Determine severity
                chroma_quality = {"4:4:4": 3, "4:2:2": 2, "4:2:0": 1}
                source_quality = chroma_quality.get(source_chroma, 0)
                actual_quality = chroma_quality.get(actual_chroma, 0)
                downgrade_note = (
                    " - CRITICAL: chroma subsampling was downgraded (quality loss)"
                    if actual_quality < source_quality
                    else ""
                )
                self._report(
                    f"Chroma subsampling mismatch! Source: {source_chroma}, "
                    f"Output: {actual_chroma}{downgrade_note}"
                )
            elif source_chroma and actual_chroma:
                self.log(f"  ✓ Chroma subsampling preserved: {actual_chroma}")

            # Check aspect ratios - must match exactly
            source_dar = source_video.get("display_aspect_ratio")
            actual_dar = actual_video.get("display_aspect_ratio")

            if source_dar != actual_dar:
                self._report(
                    f"Display aspect ratio mismatch! Source: "
                    f"'{source_dar}', Output: '{actual_dar}'"
                )

            # Check frame rate
            source_fps = source_video.get("avg_frame_rate")
            actual_fps = actual_video.get("avg_frame_rate")
            if source_fps != actual_fps:
                self._report(
                    f"Frame rate mismatch! Source: '{source_fps}', "
                    f"Output: '{actual_fps}'"
                )

            # Check mastering display metadata
            source_mastering = self._get_mastering_display(source_video)
            actual_mastering = self._get_mastering_display(actual_video)

            if source_mastering and not actual_mastering:
                self._report(
                    "Mastering display metadata (HDR10) was lost during "
                    f"merge - lost data: {source_mastering}"
                )
            elif source_mastering and actual_mastering:
                for key in [
                    "red_x",
                    "red_y",
                    "green_x",
                    "green_y",
                    "blue_x",
                    "blue_y",
                    "white_point_x",
                    "white_point_y",
                    "max_luminance",
                    "min_luminance",
                ]:
                    if source_mastering.get(key) != actual_mastering.get(key):
                        self._report(f"Mastering display {key} mismatch")

            # Check content light level
            source_cll = self._get_content_light_level(source_video)
            actual_cll = self._get_content_light_level(actual_video)

            if source_cll and not actual_cll:
                self._report(
                    "Content light level metadata (MaxCLL/MaxFALL) was lost "
                    f"during merge - lost data: "
                    f"MaxCLL={source_cll.get('max_content')}, "
                    f"MaxFALL={source_cll.get('max_average')}"
                )
            elif source_cll and actual_cll:
                if source_cll.get("max_content") != actual_cll.get(
                    "max_content"
                ) or source_cll.get("max_average") != actual_cll.get("max_average"):
                    self._report(
                        f"Content light level mismatch! Source: "
                        f"MaxCLL={source_cll.get('max_content')}/"
                        f"MaxFALL={source_cll.get('max_average')}, "
                        f"Output: MaxCLL={actual_cll.get('max_content')}/"
                        f"MaxFALL={actual_cll.get('max_average')}"
                    )

        if not self.issues:
            self.log("✅ All video metadata preserved correctly.")

        return len(self.issues)

    def _get_chroma_subsampling(self, pix_fmt: str) -> str | None:
        """
        Extract chroma subsampling pattern from pixel format string.

        Returns:
            '4:4:4', '4:2:2', '4:2:0', or None if unknown
        """
        if not pix_fmt:
            return None

        pix_fmt_lower = pix_fmt.lower()

        # 4:4:4 formats (no chroma subsampling)
        if any(x in pix_fmt_lower for x in ["yuv444", "rgb", "gbrp", "gbrap"]):
            return "4:4:4"

        # 4:2:2 formats (horizontal subsampling)
        if any(x in pix_fmt_lower for x in ["yuv422", "yuyv422", "uyvy422"]):
            return "4:2:2"

        # 4:2:0 formats (horizontal and vertical subsampling - most common)
        if any(x in pix_fmt_lower for x in ["yuv420", "nv12", "nv21"]):
            return "4:2:0"

        # 4:1:1 formats (rare)
        if "yuv411" in pix_fmt_lower:
            return "4:1:1"

        # Unknown format
        return None
