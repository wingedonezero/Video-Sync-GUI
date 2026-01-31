# vsg_core/postprocess/auditors/audio_quality.py
from pathlib import Path

from vsg_core.models.enums import TrackType

from .base import BaseAuditor


class AudioQualityAuditor(BaseAuditor):
    """Checks for audio quality degradation (sample rate, bit depth changes)."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None) -> int:
        """
        Audits audio quality parameters.
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get('streams', [])
        audio_items = [item for item in self.ctx.extracted_items if item.track.type == TrackType.AUDIO]

        for plan_item in audio_items:
            source_file = self.ctx.sources.get(plan_item.track.source)
            if not source_file:
                continue

            # Get both mkvmerge and ffprobe data for the source
            source_mkv_data = self._get_metadata(source_file, 'mkvmerge')
            source_ffprobe_data = self._get_metadata(source_file, 'ffprobe')
            if not source_mkv_data or not source_ffprobe_data:
                continue

            # Map the mkvmerge track ID to the ffprobe audio stream index
            audio_stream_index = self._get_audio_stream_index_from_track_id(
                source_mkv_data, plan_item.track.id
            )
            if audio_stream_index is None:
                continue

            # Find the source audio stream using the correct index
            source_audio_streams = [s for s in source_ffprobe_data.get('streams', [])
                                  if s.get('codec_type') == 'audio']
            if audio_stream_index >= len(source_audio_streams):
                continue

            source_audio = source_audio_streams[audio_stream_index]

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            audio_index = 0
            for item in self.ctx.extracted_items:
                if item.track.type == TrackType.AUDIO:
                    if item == plan_item and audio_index < len(actual_audio_streams):
                        actual_audio = actual_audio_streams[audio_index]
                        break
                    audio_index += 1

            if not actual_audio:
                continue

            track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"

            # Check sample rate
            source_sample_rate = source_audio.get('sample_rate')
            actual_sample_rate = actual_audio.get('sample_rate')

            if source_sample_rate and actual_sample_rate:
                source_rate = int(source_sample_rate)
                actual_rate = int(actual_sample_rate)

                if source_rate != actual_rate:
                    self.log(f"[WARNING] Sample rate changed for '{track_name}' ({plan_item.track.source}):")
                    self.log(f"          Source: {source_rate} Hz")
                    self.log(f"          Output: {actual_rate} Hz")

                    if actual_rate < source_rate:
                        self.log("          CRITICAL: Audio was downsampled!")
                        issues += 1

            # Check bit depth
            source_bits = source_audio.get('bits_per_sample') or source_audio.get('bits_per_raw_sample')
            actual_bits = actual_audio.get('bits_per_sample') or actual_audio.get('bits_per_raw_sample')

            if source_bits and actual_bits:
                try:
                    source_depth = int(source_bits)
                    actual_depth = int(actual_bits)

                    if source_depth != actual_depth:
                        self.log(f"[WARNING] Bit depth changed for '{track_name}' ({plan_item.track.source}):")
                        self.log(f"          Source: {source_depth}-bit")
                        self.log(f"          Output: {actual_depth}-bit")

                        if actual_depth < source_depth:
                            self.log("          CRITICAL: Bit depth reduced!")
                            issues += 1
                except (ValueError, TypeError):
                    pass

        if issues == 0:
            self.log("✅ All audio quality parameters preserved correctly.")

        return issues

    def _get_audio_stream_index_from_track_id(self, mkv_data: dict, track_id: int) -> int | None:
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
        for track in mkv_data.get('tracks', []):
            if track['type'] == 'audio':
                if track['id'] == track_id:
                    return audio_counter
                audio_counter += 1
        return None
