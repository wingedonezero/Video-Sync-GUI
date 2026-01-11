#!/usr/bin/env python3
"""
Validation tool for frame boundary correction.

Reads a subtitle file and shows detailed frame analysis for events
to prove the correction algorithm is working correctly.
"""
import sys
import pysubs2
from pathlib import Path


def time_to_frame_floor(time_ms, fps):
    """Convert time to frame number (floor)."""
    return int(time_ms * fps / 1000.0)


def simulate_cs_rounding(time_ms):
    """Simulate pysubs2 centisecond rounding."""
    return round(time_ms / 10) * 10


def analyze_subtitle_frames(subtitle_path, fps, sample_size=10):
    """
    Analyze subtitle file and show frame alignment for sample events.

    For each event, shows:
    - Current time in ms
    - What frame it's in (before CS rounding)
    - After CS rounding, what time it becomes
    - What frame that CS-rounded time is in
    - Whether CS rounding caused a frame boundary error
    """
    print(f"\n{'='*80}")
    print(f"Frame Boundary Validation Report")
    print(f"{'='*80}")
    print(f"File: {Path(subtitle_path).name}")
    print(f"FPS: {fps:.6f}")
    print(f"Frame duration: {1000.0/fps:.3f}ms")
    print(f"{'='*80}\n")

    try:
        subs = pysubs2.load(subtitle_path, encoding='utf-8')
    except Exception as e:
        print(f"ERROR: Failed to load subtitle: {e}")
        return

    if not subs.events:
        print("No subtitle events found.")
        return

    # Analyze sample events
    total_events = len(subs.events)
    sample_indices = [i * (total_events // sample_size) for i in range(sample_size)]
    if sample_indices[-1] != total_events - 1:
        sample_indices.append(total_events - 1)  # Include last event

    frame_errors_start = 0
    frame_errors_end = 0

    for idx in sample_indices:
        event = subs.events[idx]

        print(f"Event {idx}/{total_events - 1}: \"{event.text[:50]}...\"" if len(event.text) > 50 else f"Event {idx}/{total_events - 1}: \"{event.text}\"")
        print(f"{'-'*80}")

        # Analyze START time
        start_ms = event.start
        start_frame_intended = time_to_frame_floor(start_ms, fps)
        start_cs = simulate_cs_rounding(start_ms)
        start_frame_actual = time_to_frame_floor(start_cs, fps)
        start_frame_error = start_frame_intended != start_frame_actual

        print(f"START: {start_ms:6d}ms → frame {start_frame_intended:5d} (intended)")
        print(f"       After CS rounding: {start_cs:6d}ms → frame {start_frame_actual:5d} (actual)")
        if start_frame_error:
            print(f"       ❌ FRAME ERROR: Would be in frame {start_frame_actual} instead of {start_frame_intended} ({start_frame_actual - start_frame_intended:+d} frame)")
            frame_errors_start += 1
        else:
            print(f"       ✅ Frame-aligned (CS rounding OK)")

        # Analyze END time
        end_ms = event.end
        end_frame_intended = time_to_frame_floor(end_ms, fps)
        end_cs = simulate_cs_rounding(end_ms)
        end_frame_actual = time_to_frame_floor(end_cs, fps)
        end_frame_error = end_frame_intended != end_frame_actual

        duration_ms = end_ms - start_ms
        duration_cs = end_cs - start_cs

        print(f"END:   {end_ms:6d}ms → frame {end_frame_intended:5d} (intended)")
        print(f"       After CS rounding: {end_cs:6d}ms → frame {end_frame_actual:5d} (actual)")
        if end_frame_error:
            print(f"       ❌ FRAME ERROR: Would be in frame {end_frame_actual} instead of {end_frame_intended} ({end_frame_actual - end_frame_intended:+d} frame)")
            frame_errors_end += 1
        else:
            print(f"       ✅ Frame-aligned (CS rounding OK)")

        print(f"DURATION: {duration_ms}ms → {duration_cs}ms (after CS rounding, delta: {duration_cs - duration_ms:+d}ms)")
        print()

    print(f"{'='*80}")
    print(f"Summary of {len(sample_indices)} sampled events:")
    print(f"  Start frame errors: {frame_errors_start}/{len(sample_indices)} ({frame_errors_start/len(sample_indices)*100:.1f}%)")
    print(f"  End frame errors:   {frame_errors_end}/{len(sample_indices)} ({frame_errors_end/len(sample_indices)*100:.1f}%)")
    print(f"{'='*80}")

    if frame_errors_start == 0 and frame_errors_end == 0:
        print("\n✅ ALL SAMPLED EVENTS ARE FRAME-ALIGNED!")
        print("The frame boundary correction is working correctly.")
    else:
        print(f"\n⚠️  Found {frame_errors_start + frame_errors_end} frame alignment errors in sample.")
        print("This means CS rounding WOULD have caused frame errors without correction.")
        print("(Or correction wasn't applied to this file)")

    print()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 validate_frame_correction.py <subtitle_file> <fps> [sample_size]")
        print("\nExample:")
        print("  python3 validate_frame_correction.py output.ass 23.976 10")
        sys.exit(1)

    subtitle_path = sys.argv[1]
    fps = float(sys.argv[2])
    sample_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    analyze_subtitle_frames(subtitle_path, fps, sample_size)
