# vsg_core/postprocess/auditors/audio_duration.py
"""
Checks whether audio streams in the final MKV extend past the video track.

Two modes depending on the trim setting:
- Trim enabled:  reports which tracks were trimmed (informational).
- Trim disabled: warns if any audio overshoots by more than the threshold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path

# Threshold for flagging overhang when trimming is disabled.
_WARN_THRESHOLD_S = 0.6


class AudioDurationAuditor(BaseAuditor):
    """Flags audio tracks whose data extends past the end of the video."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        if not final_ffprobe_data:
            return 0

        streams = final_ffprobe_data.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not video_streams or not audio_streams:
            return 0

        # Get container duration to calculate seek point
        container_dur = (
            final_mkvmerge_data.get("container", {})
            .get("properties", {})
            .get("duration")
        )
        if container_dur is None:
            return 0
        container_dur_s = container_dur / 1e9

        # Seek to near the end to find last packet timestamps
        seek_s = max(0, container_dur_s - 15)

        video_end = self._get_stream_end(final_mkv_path, "v:0", seek_s)
        if video_end is None:
            self.log("[INFO] Could not determine video end time — skipping.")
            return 0

        self.log(f"  Video ends at {video_end:.3f}s")

        trim_enabled = self.ctx.settings.trim_audio_to_video_duration

        plan_audio_items = [
            item
            for item in (self.ctx.extracted_items or [])
            if item.track.type == "audio"
        ]

        for i, _audio_stream in enumerate(audio_streams):
            audio_end = self._get_stream_end(final_mkv_path, f"a:{i}", seek_s)
            if audio_end is None:
                continue

            track_label = f"Audio #{i + 1}"
            if i < len(plan_audio_items):
                item = plan_audio_items[i]
                name = item.track.props.name or f"Track {item.track.id}"
                track_label = f"{name} ({item.track.source})"

            overhang_s = audio_end - video_end

            if trim_enabled:
                # When trimming is on, report what happened for the batch report
                if overhang_s > _WARN_THRESHOLD_S:
                    # Trim was enabled but audio still overshoots — something
                    # unexpected; report as warning.
                    self._report(
                        f"{track_label} still extends {overhang_s:.1f}s past "
                        f"video despite trimming being enabled"
                    )
                elif overhang_s > 0.0:
                    # Any positive overhang when trim is on means the trim was
                    # applied.  Surface in the batch report so the user sees it.
                    self.log(
                        f"  {track_label}: trimmed to {audio_end:.3f}s — "
                        f"{overhang_s:+.3f}s past video (within tolerance)"
                    )
                    self._track_issue(
                        f"{track_label} was trimmed to match video duration "
                        f"(delta {overhang_s:+.3f}s)",
                        "warning",
                    )
                else:
                    self.log(
                        f"  {track_label} ends at {audio_end:.3f}s — OK "
                        f"(delta {overhang_s:+.3f}s)"
                    )
            elif overhang_s > _WARN_THRESHOLD_S:
                # When trimming is off, warn about significant overhang
                self._report(
                    f"{track_label} extends {overhang_s:.1f}s past "
                    f"the video end ({audio_end:.1f}s vs {video_end:.1f}s). "
                    f"Enable 'Trim audio to video duration' to fix this."
                )
            else:
                self.log(
                    f"  {track_label} ends at {audio_end:.3f}s — OK "
                    f"(delta {overhang_s:+.3f}s)"
                )

        if not self.issues:
            self.log("  All audio tracks end within video duration.")

        return len(self.issues)

    def _get_stream_end(
        self, mkv_path: Path, selector: str, seek_s: float
    ) -> float | None:
        """Return the end time of the last packet in *selector*.

        Seeks to *seek_s* and reads all remaining packets for that stream.
        """
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-select_streams",
            selector,
            "-show_entries",
            "packet=pts_time,duration_time",
            "-read_intervals",
            str(int(seek_s)),
            str(mkv_path),
        ]
        try:
            out = self.runner.run(cmd, self.tool_paths)
            if not out:
                return None
            data = json.loads(out)
            packets = data.get("packets", [])
            if not packets:
                return None

            best_end = 0.0
            for pkt in packets:
                pts = pkt.get("pts_time")
                dur = pkt.get("duration_time")
                if pts is None:
                    continue
                end = float(pts) + (float(dur) if dur else 0.0)
                best_end = max(best_end, end)
            return best_end if best_end > 0 else None
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
