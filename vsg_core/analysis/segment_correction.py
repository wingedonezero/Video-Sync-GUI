# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from scipy.signal import correlate
from collections import Counter

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info

@dataclass
class AudioSegment:
    """Represents a continuous segment of audio with a stable delay."""
    start_s: float
    end_s: float
    delay_ms: int

def detect_stepping(chunks: List[Dict[str, Any]], config: dict) -> bool:
    """
    Performs a simple check on coarse chunk data to see if stepping is present.
    Returns True if a significant drift or jump is detected.
    """
    if len(chunks) < 2:
        return False
    delays = [c['delay'] for c in chunks]
    drift = max(delays) - min(delays)
    return drift > 250

class AudioCorrector:
    """
    Performs high-precision segment mapping and correction for a single audio track.
    """
    SAMPLE_RATE = 48000

    def __init__(self, runner: CommandRunner, tool_paths: dict, config: dict):
        self.runner = runner
        self.tool_paths = tool_paths
        self.config = config
        self.log = runner._log_message

    def _decode_to_memory(self, file_path: str, stream_index: int) -> Optional[np.ndarray]:
        """Decodes a specific audio stream to a raw 32-bit stereo PCM numpy array."""
        cmd = [
            'ffmpeg', '-nostdin', '-v', 'error',
            '-i', str(file_path),
            '-map', f'0:a:{stream_index}',
            '-ac', '2', '-ar', str(self.SAMPLE_RATE),
            '-f', 's32le', '-'
        ]
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes:
            return np.frombuffer(pcm_bytes, dtype=np.int32)
        self.log(f"[ERROR] Corrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'")
        return None

    def _build_precise_edl(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray) -> Optional[List[AudioSegment]]:
        """Performs a detailed scan of the full audio to create an accurate Edit Decision List."""
        self.log("  [Corrector] Performing detailed scan of full audio to find segment boundaries...")

        # Ensure we are working with mono for correlation
        ref_mono = ref_pcm[::2]
        analysis_mono = analysis_pcm[::2]

        duration_s = min(len(ref_mono), len(analysis_mono)) / self.SAMPLE_RATE
        chunk_duration_s = 5  # Use small 5-second chunks for high precision
        if duration_s < chunk_duration_s * 4: # Need at least a few chunks
            self.log("  [Corrector] Audio is too short for detailed segment analysis.")
            return None

        chunk_count = int(duration_s / chunk_duration_s)
        chunk_samples = chunk_duration_s * self.SAMPLE_RATE

        results = []
        for i in range(chunk_count):
            start_sample = i * chunk_samples
            end_sample = start_sample + chunk_samples
            if end_sample > len(ref_mono) or end_sample > len(analysis_mono):
                break

            ref_chunk = ref_mono[start_sample:end_sample]
            analysis_chunk = analysis_mono[start_sample:end_sample]

            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (analysis_chunk - np.mean(analysis_chunk)) / (np.std(analysis_chunk) + 1e-9)
            c = correlate(r, t, mode='full', method='fft')
            k = np.argmax(np.abs(c))
            lag_samples = float(k - (len(t) - 1))
            delay_ms = int(round((lag_samples / self.SAMPLE_RATE) * 1000.0))

            results.append({'start': i * chunk_duration_s, 'delay': delay_ms})

        if not results:
            return None

        # Group consecutive chunks with similar delays into stable segments
        segments = []
        current_segment_chunks = [results[0]]
        for chunk in results[1:]:
            # Group by rounding to nearest 50ms to handle jitter
            current_median_delay = np.median([c['delay'] for c in current_segment_chunks])
            if abs(chunk['delay'] - current_median_delay) < 100: # Generous tolerance for jitter
                current_segment_chunks.append(chunk)
            else:
                # Finalize the previous segment
                delay_mode = Counter(round(c['delay'] / 10) * 10 for c in current_segment_chunks).most_common(1)[0][0]
                segments.append(AudioSegment(
                    start_s=current_segment_chunks[0]['start'],
                    end_s=current_segment_chunks[-1]['start'] + chunk_duration_s,
                    delay_ms=delay_mode
                ))
                # Start a new segment
                current_segment_chunks = [chunk]

        # Add the final segment
        if current_segment_chunks:
            delay_mode = Counter(round(c['delay'] / 10) * 10 for c in current_segment_chunks).most_common(1)[0][0]
            segments.append(AudioSegment(
                start_s=current_segment_chunks[0]['start'],
                end_s=current_segment_chunks[-1]['start'] + chunk_duration_s,
                delay_ms=delay_mode
            ))

        if len(segments) > 1:
            self.log(f"  [Corrector] Detailed mapping found {len(segments)} segments.")
            for i, seg in enumerate(segments):
                self.log(f"    - Segment {i+1}: {seg.start_s:.1f}s - {seg.end_s:.1f}s @ {seg.delay_ms}ms")
            return segments

        return None

    def _assemble_track(self, target_pcm: np.ndarray, edl: List[AudioSegment], temp_dir: Path, source_key: str) -> Optional[Path]:
        """Creates the corrected audio track from PCM data and an EDL."""
        segments_dir = temp_dir / f"segments_{source_key.replace(' ', '_')}"
        segments_dir.mkdir(exist_ok=True)

        segment_files = []
        for i, segment in enumerate(edl):
            start_sample = int(segment.start_s * self.SAMPLE_RATE) * 2
            end_sample = int(segment.end_s * self.SAMPLE_RATE) * 2
            if end_sample > len(target_pcm): end_sample = len(target_pcm)
            if start_sample >= end_sample: continue

            segment_data = target_pcm[start_sample:end_sample]
            segment_file = segments_dir / f"segment_{i}.flac"

            cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', '48000', '-ac', '2', '-i', '-', '-c:a', 'flac', str(segment_file)]
            if self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=segment_data.tobytes()) is not None:
                segment_files.append(segment_file)
            else:
                self.log(f"[ERROR] Corrector failed to save segment {i+1}")
                return None

        concat_list_path = temp_dir / f"segments_concat_{source_key.replace(' ', '_')}.txt"
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            base_delay = edl[0].delay_ms
            for i, segment in enumerate(edl):
                silence_to_add_ms = segment.delay_ms - base_delay
                if silence_to_add_ms > 10:
                    silence_file = segments_dir / f"silence_{silence_to_add_ms}ms.flac"
                    if not silence_file.exists():
                        cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo', '-t', str(silence_to_add_ms / 1000.0), '-c:a', 'flac', str(silence_file)]
                        self.runner.run(cmd, self.tool_paths)
                    if silence_file.exists():
                        self.log(f"  [Corrector] Inserting {silence_to_add_ms}ms of silence.")
                        f.write(f"file '{silence_file.as_posix()}'\n")
                f.write(f"file '{segment_files[i].as_posix()}'\n")

        output_file = temp_dir / f"corrected_{source_key.replace(' ', '_')}.flac"
        concat_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '0', '-i', str(concat_list_path), '-c:a', 'copy', str(output_file)]
        if self.runner.run(concat_cmd, self.tool_paths) is not None and output_file.exists():
            return output_file
        return None

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, temp_dir: Path) -> Optional[Path]:
        """Main entry point to create a corrected audio track."""
        self.log(f"  [Corrector] Starting correction for '{Path(target_audio_path).name}' using analysis from '{Path(analysis_audio_path).name}'")

        ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
        analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
        target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
        if ref_index is None or analysis_index is None or target_index is None:
            self.log("[ERROR] Corrector could not find audio streams for detailed analysis.")
            return None

        self.log("  [Corrector] Decoding audio tracks to memory for detailed analysis...")
        ref_pcm = self._decode_to_memory(ref_file_path, ref_index)
        analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index)
        target_pcm = self._decode_to_memory(target_audio_path, target_index)
        if ref_pcm is None or analysis_pcm is None or target_pcm is None:
            self.log("[ERROR] Corrector failed to decode one or more audio tracks.")
            return None
        self.log("  [Corrector] All audio tracks decoded.")

        edl_segments = self._build_precise_edl(ref_pcm, analysis_pcm)
        if not edl_segments:
            self.log("  [Corrector] No distinct segments found in detailed analysis. Aborting correction.")
            return None

        source_key = Path(target_audio_path).stem.split('_track_')[0]
        corrected_path = self._assemble_track(target_pcm, edl_segments, temp_dir, source_key)
        if not corrected_path:
            self.log("[ERROR] Corrector failed during track assembly.")
            return None

        return corrected_path
