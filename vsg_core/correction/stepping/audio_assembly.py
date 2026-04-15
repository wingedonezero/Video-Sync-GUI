# vsg_core/correction/stepping/audio_assembly.py
"""
Audio reconstruction from an EDL (Edit Decision List).

Given a list of ``AudioSegment`` entries, this module:
  1. Inserts silence where the delay increases (gap between clusters)
  2. Trims audio where the delay decreases (overlap)
  3. Applies per-segment drift correction when needed
  4. Concatenates all pieces via FFmpeg into a single FLAC
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...io.runner import CommandRunner
    from ...models.settings import AppSettings
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
    if pcm_bytes:
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
# Assembly
# ---------------------------------------------------------------------------


def assemble_corrected_audio(
    edl: list[AudioSegment],
    target_audio_path: str,
    output_path: Path,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    settings: AppSettings,
    log: Callable[[str], None],
    channels: int | None = None,
    channel_layout: str | None = None,
    sample_rate: int | None = None,
    target_pcm: np.ndarray | None = None,
) -> bool:
    """Build a corrected FLAC from *edl*.

    If *target_pcm*, *channels*, *channel_layout*, *sample_rate* are supplied
    the file is not re-decoded.  Otherwise the function probes and decodes
    *target_audio_path* itself.

    Returns ``True`` on success.
    """
    from ...analysis.correlation import get_audio_stream_info

    # Probe / decode if needed
    if (
        target_pcm is None
        or channels is None
        or channel_layout is None
        or sample_rate is None
    ):
        idx, _ = get_audio_stream_info(target_audio_path, None, runner, tool_paths)
        if idx is None:
            log(f"[ERROR] No audio stream in {target_audio_path}")
            return False
        channels, channel_layout, sample_rate = get_audio_properties(
            target_audio_path, idx, runner, tool_paths
        )
        target_pcm = decode_to_memory(
            target_audio_path,
            idx,
            sample_rate,
            runner,
            tool_paths,
            channels=channels,
            log=log,
        )
        if target_pcm is None:
            return False

    log(f"  [Assembly] Building {len(edl)} segment(s) → {output_path.name}")

    assembly_dir = output_path.parent / f"assembly_{output_path.stem}"
    assembly_dir.mkdir(exist_ok=True)

    segment_files: list[str] = []
    # Bake the first-cluster delay (edl[0].delay_ms) directly into the FLAC's
    # PCM content so the output is pre-aligned to Source 1's audio-content
    # timeline.  Starting current_delay at 0 makes the first loop iteration
    # compute gap_ms = edl[0].delay_ms - 0, which then takes the existing
    # silence-prepend branch (positive delay) or the skip-leading-samples
    # branch (negative delay).  After the mux step sees an is_pre_aligned
    # track, it applies only Source 1's audio container delay — no negative
    # --sync, no FLAC-block-alignment residual.
    current_delay = 0

    try:
        pcm_duration_s = len(target_pcm) / float(sample_rate * channels)
        first_delay_ms = edl[0].delay_ms
        pcm_duration_ms = pcm_duration_s * 1000.0
        if first_delay_ms < 0 and abs(first_delay_ms) >= pcm_duration_ms:
            raise RuntimeError(
                f"First-cluster delay ({first_delay_ms}ms) is >= audio "
                f"duration ({pcm_duration_ms:.0f}ms) — cannot pre-align "
                f"(would skip past end of file)."
            )

        for i, segment in enumerate(edl):
            gap_ms = segment.delay_ms - current_delay

            if abs(gap_ms) > 10:
                if gap_ms > 0:
                    # Insert silence
                    log(f"    At {segment.start_s:.3f}s: insert {gap_ms}ms silence")
                    silence_file = assembly_dir / f"silence_{i:03d}.flac"
                    silence_samples = int((gap_ms / 1000.0) * sample_rate) * channels
                    silence_pcm = np.zeros(silence_samples, dtype=np.int32)

                    if not _encode_flac(
                        silence_pcm,
                        silence_file,
                        sample_rate,
                        channels,
                        channel_layout,
                        runner,
                        tool_paths,
                    ):
                        raise RuntimeError(f"Silence encode failed at segment {i}")
                    segment_files.append(f"file '{silence_file.name}'")
                else:
                    # Remove audio (negative gap)
                    log(f"    At {segment.start_s:.3f}s: remove {-gap_ms}ms audio")

            current_delay = segment.delay_ms

            # Extract this segment's audio
            seg_start = segment.start_s
            seg_end = edl[i + 1].start_s if i + 1 < len(edl) else pcm_duration_s

            if gap_ms < 0:
                seg_start += abs(gap_ms) / 1000.0

            if seg_end <= seg_start:
                continue

            start_sample = int(seg_start * sample_rate) * channels
            end_sample = min(int(seg_end * sample_rate) * channels, len(target_pcm))
            chunk = target_pcm[start_sample:end_sample]

            if chunk.size == 0:
                continue

            seg_file = assembly_dir / f"segment_{i:03d}.flac"
            if not _encode_flac(
                chunk,
                seg_file,
                sample_rate,
                channels,
                channel_layout,
                runner,
                tool_paths,
            ):
                raise RuntimeError(f"Segment {i} encode failed")

            # Apply drift correction if significant
            if abs(segment.drift_rate_ms_s) > 0.5:
                log(
                    f"    Drift correction ({segment.drift_rate_ms_s:+.2f} ms/s) "
                    f"on segment {i}"
                )
                corrected_file = assembly_dir / f"segment_{i:03d}_corrected.flac"
                if not _apply_drift_correction(
                    seg_file,
                    corrected_file,
                    segment.drift_rate_ms_s,
                    sample_rate,
                    settings,
                    runner,
                    tool_paths,
                    log,
                ):
                    raise RuntimeError(f"Drift correction failed for segment {i}")
                seg_file = corrected_file

            segment_files.append(f"file '{seg_file.name}'")

        if not segment_files:
            raise RuntimeError("No segments generated for assembly.")

        # Concatenate
        concat_list = assembly_dir / "concat_list.txt"
        concat_list.write_text("\n".join(segment_files), encoding="utf-8")

        concat_cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-map_metadata",
            "-1",
            "-map_metadata:s:a",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:a",
            "flac",
            str(output_path),
        ]
        if runner.run(concat_cmd, tool_paths) is None:
            raise RuntimeError("FFmpeg concat failed.")

        log(f"  [Assembly] ✓ {output_path.name}")
        return True

    except Exception as exc:
        log(f"  [Assembly] ERROR: {exc}")
        return False
    finally:
        if assembly_dir.exists():
            shutil.rmtree(assembly_dir, ignore_errors=True)


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


def _apply_drift_correction(
    input_path: Path,
    output_path: Path,
    drift_rate_ms_s: float,
    sample_rate: int,
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    log: Callable[[str], None],
) -> bool:
    """Apply tempo change to correct within-segment drift."""
    tempo_ratio = 1000.0 / (1000.0 + drift_rate_ms_s)
    engine = settings.segment_resample_engine

    if engine == "rubberband":
        rb_opts = [f"tempo={tempo_ratio}"]
        if not settings.segment_rb_pitch_correct:
            rb_opts.append(f"pitch={tempo_ratio}")
        rb_opts.append(f"transients={settings.segment_rb_transients}")
        if settings.segment_rb_smoother:
            rb_opts.append("smoother=on")
        if settings.segment_rb_pitchq:
            rb_opts.append("pitchq=on")
        filter_chain = "rubberband=" + ":".join(rb_opts)
    elif engine == "atempo":
        filter_chain = f"atempo={tempo_ratio}"
    else:  # aresample (default)
        new_sr = sample_rate * tempo_ratio
        filter_chain = f"asetrate={new_sr},aresample={sample_rate}"

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-af",
        filter_chain,
        "-map_metadata",
        "-1",
        "-map_metadata:s:a",
        "-1",
        "-fflags",
        "+bitexact",
        str(output_path),
    ]
    result = runner.run(cmd, tool_paths)
    if result is None:
        msg = f"Drift correction with '{engine}' failed."
        if engine == "rubberband":
            msg += " (Ensure FFmpeg includes librubberband)."
        log(f"    [ERROR] {msg}")
        return False
    return True
