# vsg_core/postprocess/auditors/audio_channels.py
# -*- coding: utf-8 -*-
from typing import Dict
from pathlib import Path

from vsg_core.models.enums import TrackType
from .base import BaseAuditor


class AudioChannelsAuditor(BaseAuditor):
    """Verifies channel counts and layouts weren't altered during muxing."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Audits audio channel layouts to detect downmixing.
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

            source_data = self._get_metadata(source_file, 'ffprobe')
            if not source_data:
                continue

            # Find the source audio stream
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id >= len(source_audio_streams):
                continue

            source_audio = source_audio_streams[plan_item.track.id]

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

            # Compare channel counts
            source_channels = source_audio.get('channels', 0)
            actual_channels = actual_audio.get('channels', 0)

            if source_channels != actual_channels:
                track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"
                self.log(f"[WARNING] Channel count mismatch for '{track_name}' ({plan_item.track.source}):")
                self.log(f"          Source: {source_channels} channels")
                self.log(f"          Output: {actual_channels} channels")

                if actual_channels < source_channels:
                    self.log(f"          CRITICAL: Audio was downmixed!")

                issues += 1
            else:
                # Also check channel layout if available
                source_layout = source_audio.get('channel_layout', '')
                actual_layout = actual_audio.get('channel_layout', '')

                if source_layout and actual_layout and source_layout != actual_layout:
                    track_name = plan_item.track.props.name or f"Track {plan_item.track.id}"
                    self.log(f"[WARNING] Channel layout changed for '{track_name}':")
                    self.log(f"          Source: {source_layout}")
                    self.log(f"          Output: {actual_layout}")
                    issues += 1

        if issues == 0:
            self.log("✅ All audio channel layouts preserved correctly.")

        return issues
