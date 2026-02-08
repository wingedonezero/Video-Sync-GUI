#!/usr/bin/env python3
"""
Subtitle-to-Audio Offset Detector (Test Tool)

Cross-correlates subtitle timing against audio energy to find
the optimal global timing offset for VOB/DVD subtitles.

Usage:
    python tools/test_sub_offset.py VIDEO_FILE SUBTITLE_FILE [--window 500] [--step 10]

Arguments:
    VIDEO_FILE      Video file (MKV, MP4, etc.) containing the audio track
    SUBTITLE_FILE   Subtitle file (ASS or SRT) with timing to test

Options:
    --window MS     Search window in ms, each direction (default: 500)
    --step MS       Step size in ms (default: 10)
    --audio-track N Audio track index to use (default: 0)
    --verbose       Show detailed output
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Subtitle timing parsing (minimal, standalone - no project imports needed)
# ---------------------------------------------------------------------------


def parse_ass_time(time_str: str) -> float:
    """Parse ASS time format 'H:MM:SS.cc' to milliseconds."""
    match = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", time_str.strip())
    if not match:
        return 0.0
    h, m, s, cs = int(match[1]), int(match[2]), int(match[3]), int(match[4])
    return h * 3600000.0 + m * 60000.0 + s * 1000.0 + cs * 10.0


def parse_srt_time(time_str: str) -> float:
    """Parse SRT time format 'HH:MM:SS,mmm' to milliseconds."""
    match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", time_str.strip())
    if not match:
        return 0.0
    h, m, s, ms = int(match[1]), int(match[2]), int(match[3]), int(match[4])
    return h * 3600000.0 + m * 60000.0 + s * 1000.0 + ms


def load_subtitle_timing(path: Path) -> list[tuple[float, float]]:
    """
    Load subtitle start/end times from ASS or SRT file.

    Returns:
        List of (start_ms, end_ms) tuples
    """
    suffix = path.suffix.lower()
    events: list[tuple[float, float]] = []

    text = path.read_text(encoding="utf-8", errors="replace")

    if suffix in (".ass", ".ssa"):
        # Parse ASS Dialogue lines
        in_events = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("[events]"):
                in_events = True
                continue
            if stripped.startswith("[") and in_events:
                break  # Next section
            if in_events and stripped.startswith("Dialogue:"):
                # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
                parts = stripped.split(",", 9)
                if len(parts) >= 3:
                    start = parse_ass_time(parts[1])
                    end = parse_ass_time(parts[2])
                    if end > start:
                        events.append((start, end))

    elif suffix == ".srt":
        # Parse SRT timing lines
        time_pattern = re.compile(
            r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)"
        )
        for line in text.splitlines():
            match = time_pattern.match(line.strip())
            if match:
                start = parse_srt_time(match.group(1))
                end = parse_srt_time(match.group(2))
                if end > start:
                    events.append((start, end))
    else:
        print(f"Error: unsupported subtitle format '{suffix}' (use .ass or .srt)")
        sys.exit(1)

    return events


# ---------------------------------------------------------------------------
# Audio extraction and energy computation
# ---------------------------------------------------------------------------


def extract_audio_pcm(
    video_path: Path, audio_track: int = 0, sample_rate: int = 16000
) -> np.ndarray:
    """
    Extract mono PCM audio from video using ffmpeg.

    Returns:
        numpy array of float32 audio samples at the given sample rate
    """
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-map",
        f"0:a:{audio_track}",
        "-ac",
        "1",  # mono
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",  # signed 16-bit little-endian PCM
        "-acodec",
        "pcm_s16le",
        tmp_path,
    ]

    print(f"Extracting audio (track {audio_track})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr[-500:]}")
        sys.exit(1)

    # Load raw PCM
    raw = np.fromfile(tmp_path, dtype=np.int16)
    Path(tmp_path).unlink(missing_ok=True)

    # Convert to float32 normalized
    audio = raw.astype(np.float32) / 32768.0
    print(f"  Audio: {len(audio)} samples, {len(audio)/sample_rate:.1f}s duration")
    return audio


def compute_audio_energy(
    audio: np.ndarray, sample_rate: int, step_ms: int
) -> np.ndarray:
    """
    Compute RMS energy in windows of step_ms.

    Returns:
        1D array of energy values, one per step_ms window
    """
    samples_per_step = int(sample_rate * step_ms / 1000)
    n_steps = len(audio) // samples_per_step

    energy = np.zeros(n_steps, dtype=np.float32)
    for i in range(n_steps):
        chunk = audio[i * samples_per_step : (i + 1) * samples_per_step]
        energy[i] = np.sqrt(np.mean(chunk**2))

    return energy


# ---------------------------------------------------------------------------
# Subtitle activity signal
# ---------------------------------------------------------------------------


def build_subtitle_signal(
    events: list[tuple[float, float]], total_ms: float, step_ms: int
) -> np.ndarray:
    """
    Build binary subtitle activity signal.

    1 = at least one subtitle visible, 0 = no subtitle.
    """
    n_steps = int(total_ms / step_ms) + 1
    signal = np.zeros(n_steps, dtype=np.float32)

    for start_ms, end_ms in events:
        i_start = int(start_ms / step_ms)
        i_end = int(end_ms / step_ms)
        i_start = max(0, min(i_start, n_steps - 1))
        i_end = max(0, min(i_end, n_steps - 1))
        signal[i_start : i_end + 1] = 1.0

    return signal


# ---------------------------------------------------------------------------
# Cross-correlation offset detection
# ---------------------------------------------------------------------------


def find_optimal_offset(
    audio_energy: np.ndarray,
    sub_signal: np.ndarray,
    step_ms: int,
    window_ms: int,
    verbose: bool = False,
) -> tuple[int, float, list[tuple[int, float]]]:
    """
    Find the offset that maximizes correlation between audio energy
    and subtitle activity.

    Args:
        audio_energy: RMS energy per step
        sub_signal: Binary subtitle signal per step
        step_ms: Time resolution in ms
        window_ms: Search window in ms (each direction)
        verbose: Print per-offset scores

    Returns:
        (best_offset_ms, best_score, all_scores_list)
    """
    # Ensure same length
    min_len = min(len(audio_energy), len(sub_signal))
    audio_energy = audio_energy[:min_len]
    sub_signal = sub_signal[:min_len]

    # Normalize audio energy (zero-mean, unit variance)
    audio_norm = audio_energy - np.mean(audio_energy)
    std = np.std(audio_norm)
    if std > 0:
        audio_norm /= std

    max_shift = window_ms // step_ms
    scores: list[tuple[int, float]] = []

    for shift in range(-max_shift, max_shift + 1):
        offset_ms = shift * step_ms

        # Shift subtitle signal
        if shift > 0:
            # Shift right = subtitle starts later = we're testing if subs are early
            shifted = np.zeros_like(sub_signal)
            shifted[shift:] = sub_signal[:-shift] if shift < len(sub_signal) else 0
        elif shift < 0:
            # Shift left = subtitle starts earlier = we're testing if subs are late
            shifted = np.zeros_like(sub_signal)
            shifted[:shift] = sub_signal[-shift:]
        else:
            shifted = sub_signal.copy()

        # Correlation score = dot product
        score = float(np.dot(audio_norm, shifted))
        scores.append((offset_ms, score))

    # Find best
    best_idx = max(range(len(scores)), key=lambda i: scores[i][1])
    best_offset_ms, best_score = scores[best_idx]

    if verbose:
        print("\n  Offset (ms) | Score")
        print("  -----------+--------")
        for offset_ms, score in scores:
            marker = " <<<" if offset_ms == best_offset_ms else ""
            print(f"  {offset_ms:+6d}      | {score:10.2f}{marker}")

    return best_offset_ms, best_score, scores


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(
    best_offset_ms: int,
    best_score: float,
    scores: list[tuple[int, float]],
    n_events: int,
) -> None:
    """Print results summary."""
    print("\n" + "=" * 60)
    print("SUBTITLE OFFSET ANALYSIS RESULTS")
    print("=" * 60)
    print(f"  Subtitle events analyzed: {n_events}")
    print(f"  Best offset: {best_offset_ms:+d} ms")
    print(f"  Correlation score: {best_score:.2f}")

    if best_offset_ms < 0:
        print(f"\n  --> Subtitles appear to be {abs(best_offset_ms)}ms LATE")
        print(f"      Shift them earlier by {abs(best_offset_ms)}ms to fix")
    elif best_offset_ms > 0:
        print(f"\n  --> Subtitles appear to be {best_offset_ms}ms EARLY")
        print(f"      Shift them later by {best_offset_ms}ms to fix")
    else:
        print("\n  --> Subtitles appear correctly timed (no offset detected)")

    # Show nearby scores for confidence
    print("\n  Nearby offsets:")
    sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
    for offset_ms, score in sorted_scores[:5]:
        marker = " <-- best" if offset_ms == best_offset_ms else ""
        print(f"    {offset_ms:+5d}ms  score={score:.2f}{marker}")

    # Confidence check: is the peak sharp or flat?
    score_values = [s for _, s in scores]
    score_range = max(score_values) - min(score_values)
    if score_range > 0:
        # How much better is best vs average of top 5
        top5_avg = np.mean([s for _, s in sorted_scores[:5]])
        if best_score > 0 and top5_avg > 0:
            sharpness = best_score / top5_avg
            if sharpness > 1.3:
                print("\n  Confidence: HIGH (clear peak)")
            elif sharpness > 1.1:
                print("\n  Confidence: MEDIUM (visible peak)")
            else:
                print("\n  Confidence: LOW (flat - offset may not be reliable)")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect subtitle timing offset via audio cross-correlation"
    )
    parser.add_argument("video", type=Path, help="Video file with audio")
    parser.add_argument("subtitle", type=Path, help="Subtitle file (ASS or SRT)")
    parser.add_argument(
        "--window",
        type=int,
        default=500,
        help="Search window in ms each direction (default: 500)",
    )
    parser.add_argument(
        "--step", type=int, default=10, help="Step size in ms (default: 10)"
    )
    parser.add_argument(
        "--audio-track", type=int, default=0, help="Audio track index (default: 0)"
    )
    parser.add_argument("--verbose", action="store_true", help="Show all offset scores")

    args = parser.parse_args()

    if not args.video.exists():
        print(f"Error: video file not found: {args.video}")
        sys.exit(1)
    if not args.subtitle.exists():
        print(f"Error: subtitle file not found: {args.subtitle}")
        sys.exit(1)

    # 1. Load subtitle timing
    print(f"Loading subtitles: {args.subtitle.name}")
    events = load_subtitle_timing(args.subtitle)
    if not events:
        print("Error: no subtitle events found")
        sys.exit(1)
    print(f"  Found {len(events)} subtitle events")
    print(
        f"  Time range: {events[0][0]/1000:.1f}s - {events[-1][1]/1000:.1f}s"
    )

    # 2. Extract audio
    sample_rate = 16000
    audio = extract_audio_pcm(args.video, args.audio_track, sample_rate)
    total_audio_ms = len(audio) / sample_rate * 1000

    # 3. Compute audio energy
    print(f"Computing audio energy (step={args.step}ms)...")
    energy = compute_audio_energy(audio, sample_rate, args.step)

    # 4. Build subtitle activity signal
    sub_signal = build_subtitle_signal(events, total_audio_ms, args.step)
    sub_coverage = np.sum(sub_signal) / len(sub_signal) * 100
    print(f"  Subtitle coverage: {sub_coverage:.1f}% of total duration")

    # 5. Cross-correlate
    print(f"Cross-correlating (window=+/-{args.window}ms, step={args.step}ms)...")
    best_offset, best_score, all_scores = find_optimal_offset(
        energy, sub_signal, args.step, args.window, args.verbose
    )

    # 6. Report
    print_report(best_offset, best_score, all_scores, len(events))


if __name__ == "__main__":
    main()
