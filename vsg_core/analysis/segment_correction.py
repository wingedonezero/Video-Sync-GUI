# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
import ruptures as rpt
from scipy.signal import correlate
from collections import Counter
import gc

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info, run_audio_correlation

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
    Performs high-precision segment mapping and correction for a single audio track
    using in-memory processing with disk-based handoffs to conserve RAM.
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

    def _build_precise_edl(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, base_delay_ms: int) -> Optional[List[AudioSegment]]:
        """Performs a two-pass detailed scan to create an accurate Edit Decision List."""
        self.log("  [Corrector] Starting Pass 1: High-resolution brute-force scan...")

        ref_mono = ref_pcm[::2]
        analysis_mono = analysis_pcm[::2]

        duration_s = min(len(ref_mono), len(analysis_mono)) / self.SAMPLE_RATE

        window_s = 2.0
        step_s = 0.25
        window_samples = int(window_s * self.SAMPLE_RATE)
        step_samples = int(step_s * self.SAMPLE_RATE)

        if duration_s < window_s * 10:
            self.log("  [Corrector] Audio is too short for detailed segment analysis.")
            return None

        num_chunks = int((len(ref_mono) - window_samples) / step_samples)
        delay_signal = np.zeros(num_chunks)

        for i in range(num_chunks):
            start = i * step_samples
            end = start + window_samples

            ref_chunk = ref_mono[start:end]
            analysis_chunk = analysis_mono[start:end]

            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (analysis_chunk - np.mean(analysis_chunk)) / (np.std(analysis_chunk) + 1e-9)
            c = correlate(r, t, mode='full', method='fft')
            k = np.argmax(np.abs(c))
            lag_samples = float(k - (len(t) - 1))
            delay_signal[i] = int(round((lag_samples / self.SAMPLE_RATE) * 1000.0))

        self.log(f"  [Corrector] Pass 1 complete ({num_chunks} chunks analyzed). Starting Pass 2: Change-point detection...")

        algo = rpt.Binseg(model="l1").fit(delay_signal)
        penalty = np.log(num_chunks) * np.std(delay_signal)**2 * 0.1
        change_points_indices = algo.predict(pen=penalty)

        boundary_indices = sorted(list(set([0] + change_points_indices)))

        segments = []
        for i in range(len(boundary_indices) - 1):
            start_idx, end_idx = boundary_indices[i], boundary_indices[i+1]
            segment_delays = delay_signal[start_idx:end_idx]
            if len(segment_delays) == 0: continue

            stable_delay = Counter(round(d / 10) * 10 for d in segment_delays).most_common(1)[0][0]

            start_s = start_idx * step_s
            end_s = end_idx * step_s
            segments.append(AudioSegment(start_s=start_s, end_s=end_s, delay_ms=stable_delay))

        if segments:
            segments[0].delay_ms = base_delay_ms

        if len(segments) > 1:
            self.log(f"  [Corrector] Detailed mapping found {len(segments)} segments.")
            for i, seg in enumerate(segments):
                self.log(f"    - Segment {i+1}: {seg.start_s:.2f}s - {seg.end_s:.2f}s @ {seg.delay_ms}ms")
            return segments

        return None

    def _assemble_from_pcm_to_file(self, pcm_data: np.ndarray, edl: List[AudioSegment], temp_dir: Path, name_suffix: str) -> Optional[Path]:
        """Creates a corrected audio file from PCM data and an EDL."""
        segments_dir = temp_dir / f"segments_{name_suffix}"
        segments_dir.mkdir(exist_ok=True, parents=True)

        concat_files = []
        base_delay = edl[0].delay_ms
        last_end_sample = 0

        for i, segment in enumerate(edl):
            start_sample = int(segment.start_s * self.SAMPLE_RATE) * 2

            if start_sample > last_end_sample and pcm_data[last_end_sample:start_sample].size > 0:
                 gap_data = pcm_data[last_end_sample:start_sample]
                 gap_file = segments_dir / f"gap_{i}.flac"
                 cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', '48000', '-ac', '2', '-i', '-', '-c:a', 'flac', str(gap_file)]
                 if self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=gap_data.tobytes()) is not None:
                     concat_files.append(gap_file)

            silence_to_add_ms = segment.delay_ms - base_delay
            if silence_to_add_ms > 10:
                silence_file = segments_dir / f"silence_{silence_to_add_ms}ms.flac"
                if not silence_file.exists():
                    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'anullsrc=r={self.SAMPLE_RATE}:cl=stereo', '-t', str(silence_to_add_ms / 1000.0), '-c:a', 'flac', str(silence_file)]
                    if self.runner.run(cmd, self.tool_paths) is not None:
                        self.log(f"  [Corrector] Inserting {silence_to_add_ms}ms of silence.")
                if silence_file.exists():
                    concat_files.append(silence_file)

            end_sample = int(segment.end_s * self.SAMPLE_RATE) * 2
            if end_sample > len(pcm_data): end_sample = len(pcm_data)
            if start_sample >= end_sample: continue

            segment_data = pcm_data[start_sample:end_sample]
            segment_file = segments_dir / f"segment_{i}.flac"

            cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', str(self.SAMPLE_RATE), '-ac', '2', '-i', '-', '-c:a', 'flac', str(segment_file)]
            if self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=segment_data.tobytes()) is not None:
                concat_files.append(segment_file)
            else:
                self.log(f"[ERROR] Corrector failed to save segment {i+1}"); return None
            last_end_sample = end_sample

        if last_end_sample < len(pcm_data):
            final_segment_data = pcm_data[last_end_sample:]
            final_file = segments_dir / "segment_final.flac"
            cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 's32le', '-ar', '48000', '-ac', '2', '-i', '-', '-c:a', 'flac', str(final_file)]
            if self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=final_segment_data.tobytes()) is not None:
                concat_files.append(final_file)

        if not concat_files: return None

        concat_list_path = temp_dir / f"concat_list_{name_suffix}.txt"
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for file_path in concat_files: f.write(f"file '{file_path.as_posix()}'\n")

        output_file = temp_dir / f"{name_suffix}.flac"
        concat_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '0', '-i', str(concat_list_path), '-c:a', 'copy', str(output_file)]
        if self.runner.run(concat_cmd, self.tool_paths) is not None and output_file.exists():
            return output_file
        return None

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int) -> bool:
        """Verifies the corrected track against the original reference file."""
        self.log("  [Corrector] Performing QA check on corrected audio map...")
        qa_config = self.config.copy()
        qa_config.update({'scan_chunk_count': 8, 'min_accepted_chunks': 5, 'min_match_pct': 70.0})
        try:
            results = run_audio_correlation(
                ref_file=ref_file_path, target_file=corrected_path, config=qa_config,
                runner=self.runner, tool_paths=self.tool_paths, ref_lang=None, target_lang=None, role_tag="QA"
            )
            accepted = [r for r in results if r.get('accepted', False)]
            if len(accepted) < qa_config['min_accepted_chunks']:
                self.log(f"  [QA] FAILED: Not enough confident chunks to verify result ({len(accepted)}/{qa_config['min_accepted_chunks']}).")
                return False

            delays = [r['delay'] for r in accepted]
            median_delay = np.median(delays)

            if abs(median_delay - base_delay) > 25:
                self.log(f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms).")
                return False

            if np.std(delays) > 30:
                 self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {np.std(delays):.1f}ms).")
                 return False

            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, base_delay_ms: int, temp_dir: Path) -> Optional[Path]:
        """Main entry point that uses a disk-based handoff workflow to conserve memory."""
        self.log(f"  [Corrector] Starting correction for '{Path(target_audio_path).name}' using analysis from '{Path(analysis_audio_path).name}'")

        ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
        analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
        target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
        if ref_index is None or analysis_index is None or target_index is None: return None

        self.log("  [Corrector] Decoding analysis tracks to memory...")
        ref_pcm = self._decode_to_memory(ref_file_path, ref_index)
        analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index)
        if ref_pcm is None or analysis_pcm is None: return None
        self.log("  [Corrector] Analysis tracks decoded.")

        edl = self._build_precise_edl(ref_pcm, analysis_pcm, base_delay_ms)

        del ref_pcm
        gc.collect()

        if not edl:
            self.log("  [Corrector] No distinct segments found. Aborting correction.")
            return None

        self.log("  [Corrector] Assembling and verifying temporary track from analysis audio...")
        qa_track_path = self._assemble_from_pcm_to_file(analysis_pcm, edl, temp_dir, "qa_track")

        del analysis_pcm
        gc.collect()

        if not qa_track_path:
             self.log("[ERROR] Corrector failed during temporary track assembly for QA.")
             return None

        if not self._qa_check(corrected_path=str(qa_track_path), ref_file_path=ref_file_path, base_delay=base_delay_ms):
            self.log("[ERROR] Corrected track map failed QA check. Discarding result.")
            return None

        self.log("  [Corrector] Decoding target audio track to memory...")
        target_pcm = self._decode_to_memory(target_audio_path, target_index)
        if target_pcm is None: return None
        self.log("  [Corrector] Target audio decoded. Assembling final corrected track...")

        source_key = Path(target_audio_path).stem.split('_track_')[0]
        final_corrected_path = self._assemble_from_pcm_to_file(target_pcm, edl, temp_dir, f"corrected_{source_key}")

        del target_pcm
        gc.collect()

        if not final_corrected_path:
            self.log("[ERROR] Corrector failed during final track assembly.")
            return None

        return final_corrected_path
