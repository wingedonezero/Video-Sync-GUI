# vsg_core/postprocess/auditors/audio_duration.py
"""
Checks whether audio streams in the final MKV extend past the video track.

With "trim audio to the video end" on, AudioProcessingStep cuts every track
that is not from Source 1 and runs past the video end: FLAC-converted tracks
to the sample, tracks kept in their codec (passthrough) after the last unit
that starts before it. Those must end where planned (up to the container's
whole-ms timestamps). Any other track is warned about only when it
overshoots by more than the threshold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from vsg_core.orchestrator.steps.audio_processing_step import item_label

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path

# Threshold for flagging overhang on tracks that were not trimmed.
_WARN_THRESHOLD_S = 0.6
# A trimmed track ends within a sample of the video end; the two end times
# compared here are read back from whole-ms container timestamps.
_TRIMMED_MAX_DELTA_S = 0.002
# How far past the seek point to read; the seek lands 15 s before the end.
_READ_WINDOW_S = 60


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

        end_trimmed = {
            r.label for r in self.ctx.audio_processing_results if r.samples_trimmed_end
        }
        # Passthrough tracks trimmed in whole units: expected overrun past the
        # video end (< one unit), in seconds.
        cut_overrun_s = {
            r.label: r.cut.end_overrun_ns / 1e9
            for r in self.ctx.audio_processing_results
            if r.route == "passthrough"
            and r.ok
            and r.cut is not None
            and r.cut.end_overrun_ns is not None
        }

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

            label = item_label(plan_audio_items[i]) if i < len(plan_audio_items) else ""
            if label in cut_overrun_s:
                expected_s = cut_overrun_s[label]
                if abs(overhang_s - expected_s) > _TRIMMED_MAX_DELTA_S:
                    self._report(
                        f"{track_label} was cut at the video end in whole units to end "
                        f"{expected_s * 1000:+.1f} ms after it, but ends "
                        f"{overhang_s * 1000:+.1f} ms from it ({audio_end:.3f}s vs "
                        f"{video_end:.3f}s)"
                    )
                else:
                    self.log(
                        f"  {track_label}: cut at the video end in its codec — ends at "
                        f"{audio_end:.3f}s (delta {overhang_s * 1000:+.1f} ms, planned "
                        f"{expected_s * 1000:+.1f} ms, less than one unit)"
                    )
                continue

            trimmed = (
                i < len(plan_audio_items)
                and plan_audio_items[i].delay_baked
                and item_label(plan_audio_items[i]) in end_trimmed
            )
            if trimmed:
                if abs(overhang_s) > _TRIMMED_MAX_DELTA_S:
                    self._report(
                        f"{track_label} was trimmed to the video end but ends "
                        f"{overhang_s * 1000:+.1f} ms from it ({audio_end:.3f}s vs "
                        f"{video_end:.3f}s)"
                    )
                else:
                    self.log(
                        f"  {track_label}: trimmed to the video end — ends at "
                        f"{audio_end:.3f}s (delta {overhang_s * 1000:+.1f} ms)"
                    )
            elif overhang_s > _WARN_THRESHOLD_S:
                item = plan_audio_items[i] if i < len(plan_audio_items) else None
                if not trim_enabled:
                    hint = "Enable 'Trim audio to the video end' to trim it."
                elif item is not None and item.track.source == "Source 1":
                    hint = "Source 1 audio is never trimmed."
                elif item is not None and item.delay_baked:
                    hint = "Converted but not trimmed; see the audio processing log."
                else:
                    hint = (
                        "Its codec is not cut by the app, or the cut was refused; "
                        "see the audio processing log."
                    )
                self._report(
                    f"{track_label} extends {overhang_s:.1f}s past "
                    f"the video end ({audio_end:.1f}s vs {video_end:.1f}s). {hint}"
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
            # Explicit end: ffprobe 7.1 returns no packets for an open-ended
            # interval ("START") when its stderr is a pipe, as under the runner.
            f"{int(seek_s)}%+{_READ_WINDOW_S}",
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
