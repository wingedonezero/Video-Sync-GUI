# vsg_core/postprocess/auditors/dolby_vision.py
from pathlib import Path

from vsg_core.models.enums import TrackType

from .base import BaseAuditor


class DolbyVisionAuditor(BaseAuditor):
    """Detailed Dolby Vision metadata check."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Audits Dolby Vision metadata.
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get("streams", [])
        video_items = [
            item
            for item in self.ctx.extracted_items
            if item.track.type == TrackType.VIDEO
        ]

        for plan_item in video_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            source_data = self._get_metadata(source_file, "ffprobe")
            if not source_data:
                continue

            source_video = next(
                (
                    s
                    for s in source_data.get("streams", [])
                    if s.get("codec_type") == "video"
                ),
                None,
            )
            actual_video = next(
                (s for s in actual_streams if s.get("codec_type") == "video"), None
            )

            if not source_video or not actual_video:
                continue

            source_has_dv = self._has_dolby_vision(source_video)
            actual_has_dv = self._has_dolby_vision(actual_video)

            if source_has_dv and not actual_has_dv:
                self.log(
                    "[WARNING] Dolby Vision metadata was present in source but is MISSING from the output!"
                )
                self.log(
                    "         This is a significant quality loss for compatible displays."
                )
                issues += 1
            elif source_has_dv and actual_has_dv:
                self.log("✅ Dolby Vision metadata preserved successfully.")

        if not any(
            self._has_dolby_vision(
                next(
                    (
                        s
                        for s in self._get_metadata(
                            self.ctx.sources.get(item.track.source), "ffprobe"
                        ).get("streams", [])
                        if s.get("codec_type") == "video"
                    ),
                    {},
                )
            )
            for item in video_items
            if item.track.type == TrackType.VIDEO
            and self.ctx.sources.get(item.track.source)
        ):
            self.log("✅ No Dolby Vision metadata to preserve.")

        return issues
