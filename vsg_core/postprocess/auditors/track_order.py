# vsg_core/postprocess/auditors/track_order.py
from pathlib import Path

from .base import BaseAuditor


class TrackOrderAuditor(BaseAuditor):
    """Ensures tracks appear in the expected order (video → audio → subtitles)."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None) -> int:
        """
        Audits track order.
        Returns the number of issues found.
        """
        issues = 0
        final_tracks = final_mkvmerge_data.get('tracks', [])
        plan_items = self.ctx.extracted_items

        # Build expected order by type
        type_order = []
        for track in final_tracks:
            track_type = track.get('type', 'unknown')
            type_order.append(track_type)

        # Check that video comes before audio
        video_indices = [i for i, t in enumerate(type_order) if t == 'video']
        audio_indices = [i for i, t in enumerate(type_order) if t == 'audio']
        subtitle_indices = [i for i, t in enumerate(type_order) if t == 'subtitles']

        if video_indices and audio_indices:
            if max(video_indices) > min(audio_indices):
                self.log("[WARNING] Track order issue: Audio tracks appear before some video tracks!")
                issues += 1

        if audio_indices and subtitle_indices:
            if max(audio_indices) > min(subtitle_indices):
                self.log("[WARNING] Track order issue: Subtitle tracks appear before some audio tracks!")
                issues += 1

        # Verify preserved tracks come after main tracks
        for i, item in enumerate(plan_items):
            if item.is_preserved:
                # Find the main track (should be before this one)
                main_track_found = False
                for j in range(i):
                    other_item = plan_items[j]
                    if (other_item.track.source == item.track.source and
                        other_item.track.type == item.track.type and
                        not other_item.is_preserved):
                        main_track_found = True
                        break

                if not main_track_found:
                    track_name = item.track.props.name or f"Track {i}"
                    self.log(f"[WARNING] Preserved track '{track_name}' appears without a main track before it!")
                    issues += 1

        if issues == 0:
            self.log("✅ Track order is correct.")

        return issues
