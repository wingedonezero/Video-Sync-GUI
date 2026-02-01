# vsg_core/postprocess/auditors/track_flags.py
from pathlib import Path

from .base import BaseAuditor


class TrackFlagsAuditor(BaseAuditor):
    """Audits default and forced track flags."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Compares expected vs actual flags and logs warnings.
        Returns the number of issues found.
        """
        issues = 0
        actual_tracks = final_mkvmerge_data.get("tracks", [])

        # Group tracks by type for proper default flag checking
        video_tracks = [
            (i, t) for i, t in enumerate(actual_tracks) if t.get("type") == "video"
        ]
        audio_tracks = [
            (i, t) for i, t in enumerate(actual_tracks) if t.get("type") == "audio"
        ]
        subtitle_tracks = [
            (i, t) for i, t in enumerate(actual_tracks) if t.get("type") == "subtitles"
        ]

        # Check if there's exactly one default per type (where it matters)
        default_videos = sum(
            1
            for _, t in video_tracks
            if t.get("properties", {}).get("default_track", False)
        )
        default_audios = sum(
            1
            for _, t in audio_tracks
            if t.get("properties", {}).get("default_track", False)
        )
        default_subs = sum(
            1
            for _, t in subtitle_tracks
            if t.get("properties", {}).get("default_track", False)
        )

        if default_videos > 1:
            self.log(
                f"[WARNING] Multiple default video tracks found ({default_videos}). Players may behave unexpectedly."
            )
            issues += 1

        if default_audios == 0 and audio_tracks:
            self.log(
                "[WARNING] No default audio track set. Some players may not play audio automatically."
            )
            issues += 1
        elif default_audios > 1:
            self.log(
                f"[WARNING] Multiple default audio tracks found ({default_audios})."
            )
            issues += 1

        if default_subs > 1:
            self.log(
                f"[WARNING] Multiple default subtitle tracks found ({default_subs})."
            )
            issues += 1

        # Check forced flags on subtitles
        forced_subs = sum(
            1
            for _, t in subtitle_tracks
            if t.get("properties", {}).get("forced_track", False)
        )
        if forced_subs > 1:
            self.log(
                f"[WARNING] Multiple forced subtitle tracks found ({forced_subs}). Only one should be forced."
            )
            issues += 1

        if issues == 0:
            self.log("✅ All track flags are correct.")

        return issues
