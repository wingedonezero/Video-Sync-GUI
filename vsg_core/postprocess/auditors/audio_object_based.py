# vsg_core/postprocess/auditors/audio_object_based.py
from pathlib import Path


from .base import BaseAuditor


class AudioObjectBasedAuditor(BaseAuditor):
    """Detailed object-based audio check (Atmos, DTS:X)."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Audits object-based audio metadata (Atmos/DTS:X).
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get("streams", [])
        audio_items = [
            item
            for item in self.ctx.extracted_items
            if item.track.type == "audio"
        ]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            # Get both mkvmerge and ffprobe data for the source
            source_mkv_data = self._get_metadata(source_file, "mkvmerge")
            source_ffprobe_data = self._get_metadata(source_file, "ffprobe")
            if not source_mkv_data or not source_ffprobe_data:
                continue

            # Map the mkvmerge track ID to the ffprobe audio stream index
            audio_stream_index = self._get_audio_stream_index_from_track_id(
                source_mkv_data, plan_item.track.id
            )
            if audio_stream_index is None:
                continue

            # Find the source audio stream using the correct index
            source_audio_streams = [
                s
                for s in source_ffprobe_data.get("streams", [])
                if s.get("codec_type") == "audio"
            ]
            if audio_stream_index >= len(source_audio_streams):
                continue

            source_audio = source_audio_streams[audio_stream_index]

            # Find corresponding stream in output
            actual_audio_streams = [
                s for s in actual_streams if s.get("codec_type") == "audio"
            ]
            actual_audio = None
            for i, item in enumerate(
                [
                    it
                    for it in self.ctx.extracted_items
                    if it.track.type == "audio"
                ]
            ):
                if item == plan_item and i < len(actual_audio_streams):
                    actual_audio = actual_audio_streams[i]
                    break

            if not actual_audio:
                continue

            source_profile = source_audio.get("profile", "")
            actual_profile = actual_audio.get("profile", "")

            # Check for Atmos
            if "Atmos" in source_profile and "Atmos" not in actual_profile:
                self.log(
                    f"[WARNING] Dolby Atmos metadata was lost for audio track from {plan_item.track.source}!"
                )
                issues += 1
            elif "Atmos" in source_profile and "Atmos" in actual_profile:
                self.log(
                    f"✅ Dolby Atmos preserved for track from {plan_item.track.source}."
                )

            # Check for DTS:X
            if "DTS:X" in source_profile and "DTS:X" not in actual_profile:
                self.log(
                    f"[WARNING] DTS:X metadata was lost for audio track from {plan_item.track.source}!"
                )
                issues += 1
            elif "DTS:X" in source_profile and "DTS:X" in actual_profile:
                self.log(f"✅ DTS:X preserved for track from {plan_item.track.source}.")

        if issues == 0:
            self.log("✅ All object-based audio metadata preserved correctly.")

        return issues

    def _get_audio_stream_index_from_track_id(
        self, mkv_data: dict, track_id: int
    ) -> int | None:
        """
        Maps an mkvmerge track ID to the corresponding audio stream index in ffprobe output.

        This is needed because mkvmerge track IDs can be non-sequential and include all track types,
        while ffprobe audio streams are indexed sequentially within their type.

        Args:
            mkv_data: mkvmerge -J output
            track_id: The mkvmerge track ID to find

        Returns:
            The 0-based audio stream index, or None if not found
        """
        audio_counter = 0
        for track in mkv_data.get("tracks", []):
            if track["type"] == "audio":
                if track["id"] == track_id:
                    return audio_counter
                audio_counter += 1
        return None
