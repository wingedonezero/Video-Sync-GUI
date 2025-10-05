# vsg_core/postprocess/auditors/audio_object_based.py
# -*- coding: utf-8 -*-
from typing import Dict
from pathlib import Path

from vsg_core.models.enums import TrackType
from .base import BaseAuditor


class AudioObjectBasedAuditor(BaseAuditor):
    """Detailed object-based audio check (Atmos, DTS:X)."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Audits object-based audio metadata (Atmos/DTS:X).
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

            # Find the matching audio stream in source
            source_audio_streams = [s for s in source_data.get('streams', []) if s.get('codec_type') == 'audio']
            if plan_item.track.id < len(source_audio_streams):
                source_audio = source_audio_streams[plan_item.track.id]
            else:
                continue

            # Find corresponding stream in output
            actual_audio_streams = [s for s in actual_streams if s.get('codec_type') == 'audio']
            actual_audio = None
            for i, item in enumerate([it for it in self.ctx.extracted_items if it.track.type == TrackType.AUDIO]):
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
