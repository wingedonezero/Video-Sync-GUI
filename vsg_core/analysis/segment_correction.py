# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
"""
Segmented audio correction - applies timing corrections from EDL to create corrected audio tracks.
Mirrors the decode approach used in audio_corr.py that successfully handles TrueHD.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
import tempfile

from vsg_core.io.runner import CommandRunner


def create_corrected_track(
    original_container_path: str,
    analysis_track_mapping: str,
    edl: List[Dict],
    temp_dir: Path,
    runner: CommandRunner,
    tool_paths: Dict[str, str],
    source_key: str
) -> Optional[Path]:
    """
    Create a corrected audio track by applying segment timing corrections.
    Uses the same in-memory decode approach as analysis.
    """
    segments_dir = temp_dir / f"segments_{source_key.replace(' ', '_')}"
    segments_dir.mkdir(exist_ok=True)

    runner._log_message(f"  Using container: {Path(original_container_path).name} with analysis mapping: {analysis_track_mapping}")

    # Step 1: Decode to memory like analysis does (this works on TrueHD)
    decode_cmd = [
        'ffmpeg', '-nostdin', '-v', 'error',
        '-i', str(original_container_path),
        '-map', analysis_track_mapping,
        '-resampler', 'soxr', '-ac', '2', '-ar', '48000',
        '-f', 'f32le', '-'  # Decode to memory like analysis
    ]

    pcm_bytes = runner.run(decode_cmd, tool_paths, is_binary=True)
    if not pcm_bytes or not isinstance(pcm_bytes, bytes):
        runner._log_message(f"[ERROR] Failed to decode audio to memory using analysis method")
        return None

    # Convert to numpy array for processing
    import numpy as np
    audio_data = np.frombuffer(pcm_bytes, dtype=np.float32)
    sample_rate = 48000

    runner._log_message(f"  Successfully decoded {len(audio_data)/sample_rate:.1f}s of audio to memory")

    # Step 2: Extract segments from memory and save as FLAC files
    segment_files = []
    for i, segment in enumerate(edl):
        start_time = segment['start_time']
        end_time = segment['end_time']

        # Calculate sample positions
        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)

        # Extract segment from memory
        if end_sample > len(audio_data):
            end_sample = len(audio_data)
        if start_sample >= len(audio_data):
            runner._log_message(f"[ERROR] Segment {i+1} start beyond audio length")
            return None

        segment_data = audio_data[start_sample:end_sample]

        # Save segment as FLAC
        segment_file = segments_dir / f"segment_{i}.flac"

        # Write segment to FLAC using ffmpeg
        segment_cmd = [
            'ffmpeg', '-y', '-v', 'error', '-nostdin',
            '-f', 'f32le', '-ar', '48000', '-ac', '2', '-i', '-',
            '-c:a', 'flac', str(segment_file)
        ]

        segment_bytes = segment_data.tobytes()
        if runner.run(segment_cmd, tool_paths, input_data=segment_bytes) and segment_file.exists():
            segment_files.append((segment_file, segment))
            runner._log_message(f"  Extracted segment {i+1}: {start_time:.1f}s-{end_time:.1f}s")
        else:
            runner._log_message(f"[ERROR] Failed to save segment {i+1}")
            return None

    # Step 3: Create concat list with silence insertion
    concat_list = temp_dir / f"segments_concat_{source_key.replace(' ', '_')}.txt"
    with open(concat_list, 'w', encoding='utf-8') as f:
        for i, (segment_file, segment_info) in enumerate(segment_files):
            # Insert silence before this segment (except the first)
            if i > 0:
                prev_delay = edl[i-1]['delay_ms']
                curr_delay = segment_info['delay_ms']
                silence_ms = curr_delay - prev_delay

                if silence_ms > 10:  # Only insert if significant
                    silence_file = segments_dir / f"silence_{i}.flac"
                    silence_duration = silence_ms / 1000.0

                    silence_cmd = [
                        'ffmpeg', '-y', '-v', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', f'anullsrc=rate=48000:sample_fmt=s16:channels=2',
                        '-t', str(silence_duration), '-c:a', 'flac', str(silence_file)
                    ]

                    if runner.run(silence_cmd, tool_paths) and silence_file.exists():
                        f.write(f"file '{silence_file.absolute()}'\n")
                        runner._log_message(f"  Inserted {silence_ms}ms silence before segment {i+1}")
                    else:
                        runner._log_message(f"[WARN] Failed to create silence for segment {i+1}")
                elif silence_ms < -10:  # Need to trim audio
                    runner._log_message(f"[WARN] Segment {i+1} needs {abs(silence_ms)}ms trimmed - not implemented")

            f.write(f"file '{segment_file.absolute()}'\n")

    # Step 4: Concatenate all segments with silence
    output_file = temp_dir / f"corrected_{source_key.replace(' ', '_')}.flac"
    concat_cmd = [
        'ffmpeg', '-y', '-v', 'error', '-nostdin',
        '-f', 'concat', '-safe', '0', '-i', str(concat_list),
        '-c:a', 'copy', str(output_file)
    ]

    if runner.run(concat_cmd, tool_paths) and output_file.exists():
        runner._log_message(f"  Created corrected track: {output_file.name}")
        # Cleanup large decoded file
        try:
            decoded_audio.unlink()
        except:
            pass
        return output_file
    else:
        runner._log_message(f"[ERROR] Failed to concatenate corrected track")
        return None


def extract_track_mapping_from_path(extracted_path: Path) -> Optional[str]:
    """
    Extract FFmpeg track mapping from extracted file path.

    Example: Source_2_track_12_1.thd -> "0:a:1"
    """
    filename_parts = str(extracted_path.stem).split('_')
    if len(filename_parts) >= 4:
        track_id = filename_parts[-1]  # The last number is the track ID
        return f"0:a:{track_id}"
    return None
