# vsg_core/correction/stepping/audio_assembly.py
"""
Stepping audio helpers: probe and decode a track for analysis, and write the
mono QA track from an EDL.

The corrected tracks themselves are not built here: AudioProcessingStep runs
the same edits (``edit_plan.edl_to_edits``) through the audio finisher, one
verified encode per track.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .edit_plan import edl_to_edits, render_edits

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...io.runner import CommandRunner
    from .types import AudioSegment


# ---------------------------------------------------------------------------
# Audio probing / decoding helpers
# ---------------------------------------------------------------------------


def get_audio_properties(
    file_path: str,
    stream_index: int,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> tuple[int, str, int]:
    """Return ``(channels, channel_layout, sample_rate)`` via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        f"a:{stream_index}",
        "-show_entries",
        "stream=channels,channel_layout,sample_rate",
        "-of",
        "json",
        str(file_path),
    ]
    out = runner.run(cmd, tool_paths)
    if not out:
        raise RuntimeError(f"Could not probe audio properties for {file_path}")
    try:
        info = json.loads(out)["streams"][0]
        channels = int(info.get("channels", 2))
        layout = info.get(
            "channel_layout",
            {1: "mono", 2: "stereo", 6: "5.1(side)", 8: "7.1"}.get(channels, "stereo"),
        )
        sample_rate = int(info.get("sample_rate", 48000))
        return channels, layout, sample_rate
    except (json.JSONDecodeError, IndexError, KeyError) as exc:
        raise RuntimeError(f"Failed to parse ffprobe audio properties: {exc}")


def decode_to_memory(
    file_path: str,
    stream_index: int,
    sample_rate: int,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    channels: int = 1,
    log: Callable[[str], None] | None = None,
) -> np.ndarray | None:
    """Decode an audio stream to int32 PCM in memory."""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(file_path),
        "-map",
        f"0:a:{stream_index}",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-f",
        "s32le",
        "-",
    ]
    pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
    if isinstance(pcm_bytes, bytes) and pcm_bytes:
        # Ensure buffer alignment (4 bytes per int32 sample)
        elem = np.dtype(np.int32).itemsize
        aligned = (len(pcm_bytes) // elem) * elem
        if aligned != len(pcm_bytes) and log:
            log(
                f"[BUFFER ALIGNMENT] Trimmed {len(pcm_bytes) - aligned} bytes "
                f"from {Path(file_path).name}"
            )
        return np.frombuffer(pcm_bytes[:aligned], dtype=np.int32).copy()
    if log:
        log(
            f"[ERROR] Failed to decode stream {stream_index} from {Path(file_path).name}"
        )
    return None


# ---------------------------------------------------------------------------
# QA track
# ---------------------------------------------------------------------------


def assemble_check_track(
    edl: list[AudioSegment],
    pcm: np.ndarray,
    channels: int,
    channel_layout: str,
    sample_rate: int,
    output_path: Path,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    log: Callable[[str], None],
) -> bool:
    """Write the QA track: ``pcm`` (already decoded, usually mono) with the
    EDL's edits applied, on Source 1's audio-content timeline (no container
    offset), as one FLAC. The real tracks get the same edits through the
    audio finisher. Returns ``True`` on success."""
    log(f"  [Assembly] QA track from {len(edl)} segment(s) -> {output_path.name}")
    try:
        edits = edl_to_edits(edl, sample_rate, 0.0, log)
        if not _encode_flac(
            render_edits(pcm, channels, edits.ops),
            output_path,
            sample_rate,
            channels,
            channel_layout,
            runner,
            tool_paths,
        ):
            raise RuntimeError("FLAC encode failed")
    except (ValueError, RuntimeError) as exc:
        log(f"  [Assembly] ERROR: {exc}")
        return False
    log(f"  [Assembly] ✓ {output_path.name}")
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encode_flac(
    pcm: np.ndarray,
    out_path: Path,
    sample_rate: int,
    channels: int,
    channel_layout: str,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "s32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-channel_layout",
        channel_layout,
        "-i",
        "-",
        "-map_metadata",
        "-1",
        "-map_metadata:s:a",
        "-1",
        "-fflags",
        "+bitexact",
        "-c:a",
        "flac",
        str(out_path),
    ]
    return (
        runner.run(cmd, tool_paths, is_binary=True, input_data=pcm.tobytes())
        is not None
    )
