# vsg_core/orchestrator/steps/audio_trim.py
"""
Optional pre-mux step: trims audio tracks that extend past the video end.

Useful when a streaming audio source (e.g. Netflix) is longer than the
disc video (e.g. Blu-ray) — for instance an OP/ED that only exists in
the streaming version.  Without trimming, players show a black screen
with audio still playing after the video ends.

Gated behind ``AppSettings.trim_audio_to_video_duration`` (off by default).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.jobs import Delays, PlanItem
    from vsg_core.orchestrator.steps.context import Context

# Audio extending past video by less than this (seconds) is left alone.
_OVERHANG_THRESHOLD_S = 0.5

# Extra seconds added to the trim point so ffmpeg's frame-boundary cut
# doesn't land short.  50 ms covers the largest common audio frame
# (EAC-3 = 32 ms) with comfortable margin.
_PADDING_S = 0.05


def trim_audio_to_video(
    ctx: Context, runner: CommandRunner, log: Callable[[str], None]
) -> Context:
    """Trim audio tracks whose data would extend past the video end.

    Modifies ``extracted_path`` on affected items in-place so that
    ``MuxStep`` picks up the trimmed files automatically.
    """
    items = ctx.extracted_items or []
    delays = ctx.delays

    if not delays:
        log("[AudioTrim] No delay data available — skipping.")
        return ctx

    # --- Find the video item and probe its duration ---
    video_item = _find_video_item(items)
    if video_item is None or video_item.extracted_path is None:
        log("[AudioTrim] No video track found — skipping.")
        return ctx

    # Extracted video is often a raw elementary stream (.h264/.hevc) with no
    # container metadata, so ffprobe can't report its duration.  Fall back to
    # probing the source MKV which always has a container duration.
    video_dur_s = _probe_duration_s(video_item.extracted_path, runner)
    if video_dur_s is None:
        source_path = ctx.sources.get(video_item.track.source)
        if source_path:
            video_dur_s = _probe_duration_s(source_path, runner)
    if video_dur_s is None:
        log("[AudioTrim] Could not probe video duration — skipping.")
        return ctx

    video_delay_s = _effective_delay_s(video_item, delays, ctx.subtitle_delays_ms)
    video_end_s = video_dur_s + video_delay_s

    log(
        f"[AudioTrim] Video duration: {video_dur_s:.3f}s, "
        f"delay: {video_delay_s * 1000:+.0f}ms, "
        f"effective end: {video_end_s:.3f}s"
    )

    # --- Check each non-Source-1 audio track ---
    trimmed_count = 0
    for item in items:
        if item.track.type != "audio" or item.extracted_path is None:
            continue
        # Never trim Source 1 audio — it is the reference timeline.
        if item.track.source == "Source 1":
            continue

        audio_dur_s = _probe_duration_s(item.extracted_path, runner)
        if audio_dur_s is None:
            continue

        audio_delay_s = _effective_delay_s(item, delays, ctx.subtitle_delays_ms)
        audio_end_s = audio_dur_s + audio_delay_s
        overhang_s = audio_end_s - video_end_s

        track_label = (
            f"{item.track.props.name or f'Track {item.track.id}'} ({item.track.source})"
        )

        if overhang_s <= _OVERHANG_THRESHOLD_S:
            log(
                f"[AudioTrim] {track_label}: ends at {audio_end_s:.3f}s — "
                f"OK (delta {overhang_s:+.3f}s)"
            )
            continue

        # --- Trim this track ---
        target_dur_s = (video_end_s - audio_delay_s) + _PADDING_S
        # Ensure we don't extend past the original duration
        target_dur_s = min(target_dur_s, audio_dur_s)

        trimmed_path = _trim_audio(
            item.extracted_path, target_dur_s, ctx.temp_dir, runner
        )
        if trimmed_path is None:
            log(
                f"[AudioTrim] WARNING: Failed to trim {track_label} — "
                f"keeping original ({overhang_s:.1f}s overhang)"
            )
            continue

        log(
            f"[AudioTrim] {track_label}: trimmed {overhang_s:.1f}s overhang "
            f"(audio {audio_end_s:.1f}s → video end {video_end_s:.1f}s)"
        )
        log(f"[AudioTrim]   Original: {item.extracted_path}")
        log(f"[AudioTrim]   Trimmed:  {trimmed_path}")
        log(
            f"[AudioTrim]   Target duration: {target_dur_s:.3f}s "
            f"(includes {_PADDING_S * 1000:.0f}ms safety padding)"
        )

        item.extracted_path = trimmed_path
        trimmed_count += 1

    if trimmed_count == 0:
        log("[AudioTrim] All audio tracks within video duration — no trimming needed.")
    else:
        log(f"[AudioTrim] Trimmed {trimmed_count} audio track(s).")

    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_video_item(items: list[PlanItem]) -> PlanItem | None:
    """Return the first non-preserved video PlanItem."""
    for item in items:
        if item.track.type == "video" and not item.is_preserved:
            return item
    return None


def _probe_duration_s(path: Path | str, runner: CommandRunner) -> float | None:
    """Probe the duration of a media file via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration",
        str(path),
    ]
    try:
        out = runner.run(cmd, {})
        if not out:
            return None
        data = json.loads(out)
        dur_str = data.get("format", {}).get("duration")
        if dur_str is None:
            return None
        return float(dur_str)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _effective_delay_s(
    item: PlanItem,
    delays: Delays,
    subtitle_delays_ms: dict[str, float],
) -> float:
    """Calculate the mkvmerge delay for a track, in seconds.

    Mirrors ``MkvmergeOptionsBuilder._effective_delay_ms`` so the trim
    calculation matches what mkvmerge will actually apply.
    """
    tr = item.track

    if tr.source == "Source 1" and tr.type == "video":
        return delays.global_shift_ms / 1000.0

    if tr.source == "Source 1" and tr.type == "audio":
        return (round(item.container_delay_ms) + delays.global_shift_ms) / 1000.0

    # Stepping-corrected tracks with pre-baked alignment: mkvmerge only applies
    # Source 1's audio-container delay (stashed in container_delay_ms) — the
    # correlation shift is already in the FLAC samples.  Mirror options_builder.
    if item.is_pre_aligned:
        return round(item.container_delay_ms) / 1000.0

    # Subtitles with baked-in timing get 0 delay
    if tr.type == "subtitles" and (item.stepping_adjusted or item.frame_adjusted):
        return 0.0

    sync_key = item.sync_to if tr.source == "External" else tr.source
    if sync_key is None:
        return 0.0

    if tr.type == "subtitles" and sync_key in subtitle_delays_ms:
        return round(subtitle_delays_ms[sync_key]) / 1000.0

    return round(delays.source_delays_ms.get(sync_key, 0)) / 1000.0


def _trim_audio(
    src: Path, target_duration_s: float, temp_dir: Path, runner: CommandRunner
) -> Path | None:
    """Trim *src* to *target_duration_s* using ffmpeg stream copy.

    Returns the path to the trimmed file, or ``None`` on failure.
    """
    # Round duration to 3 decimal places for clean ffmpeg argument
    dur_arg = f"{target_duration_s:.3f}"
    trimmed = temp_dir / f"trimmed_{src.name}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-t",
        dur_arg,
        "-c",
        "copy",
        str(trimmed),
    ]
    result = runner.run(cmd, {})
    if result is None or not trimmed.exists():
        return None
    return trimmed
