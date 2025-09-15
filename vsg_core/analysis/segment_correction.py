# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
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

def _get_audio_properties(file_path: str, stream_index: int, runner: CommandRunner, tool_paths: dict) -> Tuple[int, str, int]:
    """Runs ffprobe to get channel count, layout, and sample rate."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', f'a:{stream_index}',
        '-show_entries', 'stream=channels,channel_layout,sample_rate',
        '-of', 'json', str(file_path)
    ]
    out = runner.run(cmd, tool_paths)
    if not out:
        raise RuntimeError(f"Could not probe audio properties for {file_path}")
    try:
        stream_info = json.loads(out)['streams'][0]
        channels = int(stream_info.get('channels', 2))
        channel_layout = stream_info.get('channel_layout', {1: 'mono', 2: 'stereo', 6: '5.1(side)', 8: '7.1'}.get(channels, 'stereo'))
        sample_rate = int(stream_info.get('sample_rate', 48000))
        return channels, channel_layout, sample_rate
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        raise RuntimeError(f"Failed to parse ffprobe audio properties: {e}")

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
    using in-memory, sample-accurate assembly.
    """
    def __init__(self, runner: CommandRunner, tool_paths: dict, config: dict):
        self.runner = runner
        self.tool_paths = tool_paths
        self.config = config
        self.log = runner._log_message

    def _decode_to_memory(self, file_path: str, stream_index: int, sample_rate: int, channels: int, force_mono: bool = False) -> Optional[np.ndarray]:
        """Decodes a specific audio stream to a raw 32-bit PCM numpy array."""
        cmd = [
            'ffmpeg', '-nostdin', '-v', 'error',
            '-i', str(file_path),
            '-map', f'0:a:{stream_index}'
        ]
        if force_mono:
            cmd.extend(['-ac', '1'])
        else:
            cmd.extend(['-ac', str(channels)])

        cmd.extend(['-ar', str(sample_rate), '-f', 's32le', '-'])

        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes:
            return np.frombuffer(pcm_bytes, dtype=np.int32)
        self.log(f"[ERROR] Corrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'")
        return None

    def _build_precise_edl(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int, base_delay_ms: int) -> Optional[List[AudioSegment]]:
        """Performs a two-pass coarse and fine scan to create a sample-accurate Edit Decision List."""
        self.log("  [Corrector] Starting Pass 1 (Coarse): High-resolution brute-force scan...")
        duration_s = min(len(ref_pcm), len(analysis_pcm)) / sample_rate
        window_s, step_s = 2.0, 0.25
        window_samples, step_samples = int(window_s * sample_rate), int(step_s * sample_rate)

        if duration_s < window_s * 10:
            self.log("  [Corrector] Audio is too short for detailed segment analysis.")
            return None

        num_chunks = int((len(ref_pcm) - window_samples) / step_samples)
        delay_signal = np.zeros(num_chunks)

        for i in range(num_chunks):
            start = i * step_samples
            end = start + window_samples
            ref_chunk, analysis_chunk = ref_pcm[start:end], analysis_pcm[start:end]
            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (analysis_chunk - np.mean(analysis_chunk)) / (np.std(analysis_chunk) + 1e-9)
            c = correlate(r, t, mode='full', method='fft')
            k = np.argmax(np.abs(c))
            lag_samples = float(k - (len(t) - 1))
            delay_signal[i] = int(round((lag_samples / sample_rate) * 1000.0))

        self.log(f"  [Corrector] Pass 1 complete. Finding approximate change points...")
        algo = rpt.Binseg(model="l1").fit(delay_signal)
        penalty = np.log(num_chunks) * np.std(delay_signal)**2 * 0.1
        approx_change_indices = algo.predict(pen=penalty)

        self.log("  [Corrector] Starting Pass 2 (Fine): Refining change points to be sample-accurate...")
        refined_change_indices = [0]
        for approx_idx in approx_change_indices:
            if approx_idx == 0 or approx_idx >= num_chunks: continue
            refined_idx = self._refine_change_point(ref_pcm, analysis_pcm, approx_idx, step_samples, sample_rate)
            refined_change_indices.append(refined_idx)

        # --- FIX: Add the total length of the audio as the final boundary point ---
        total_samples = len(ref_pcm)
        refined_change_indices.append(total_samples)

        boundary_indices = sorted(list(set(refined_change_indices)))
        segments = []

        for i in range(len(boundary_indices) - 1):
            start_idx, end_idx = boundary_indices[i], boundary_indices[i+1]
            if start_idx >= end_idx: continue # Skip zero-length segments

            coarse_start_chunk = start_idx // step_samples
            coarse_end_chunk = end_idx // step_samples
            segment_delays = delay_signal[coarse_start_chunk:coarse_end_chunk]
            if len(segment_delays) == 0:
                 # If segment is too small, use delay from chunk just before it
                 stable_delay = delay_signal[max(0, coarse_start_chunk - 1)]
            else:
                stable_delay = Counter(round(d / 10) * 10 for d in segment_delays).most_common(1)[0][0]

            segments.append(AudioSegment(start_s=(start_idx / sample_rate), end_s=(end_idx / sample_rate), delay_ms=stable_delay))

        if segments:
            segments[0].delay_ms = base_delay_ms
            self.log(f"  [Corrector] Detailed mapping found {len(segments)} segments.")
            for i, seg in enumerate(segments):
                self.log(f"    - Segment {i+1}: {seg.start_s:.4f}s - {seg.end_s:.4f}s @ {seg.delay_ms}ms")
            return segments
        return None

    def _refine_change_point(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, approx_chunk_idx: int, step_samples: int, sample_rate: int) -> int:
        """Performs a surgical, sample-by-sample scan to find the exact change point."""
        approx_sample_idx = approx_chunk_idx * step_samples
        search_window_ms = 500
        search_radius = int((search_window_ms / 1000) * sample_rate)

        start_scan = max(0, approx_sample_idx - search_radius)
        end_scan = min(len(ref_pcm), approx_sample_idx + search_radius)

        corr_window_ms = 20
        corr_radius = int((corr_window_ms / 1000) * sample_rate)

        pre_chunk = analysis_pcm[start_scan - corr_radius : start_scan]
        ref_chunk = ref_pcm[start_scan - corr_radius : start_scan]
        r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
        t = (pre_chunk - np.mean(pre_chunk)) / (np.std(pre_chunk) + 1e-9)
        c = correlate(r, t, 'full', 'fft')
        baseline_lag = np.argmax(np.abs(c)) - (len(t) - 1)

        for i in range(start_scan, end_scan - corr_radius):
            post_chunk = analysis_pcm[i : i + corr_radius]
            ref_chunk = ref_pcm[i : i + corr_radius]
            r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
            t = (post_chunk - np.mean(post_chunk)) / (np.std(post_chunk) + 1e-9)
            c = correlate(r, t, 'full', 'fft')
            current_lag = np.argmax(np.abs(c)) - (len(t) - 1)

            if abs(current_lag - baseline_lag) > 5:
                self.log(f"    - Refined point from ~{(approx_sample_idx/sample_rate):.3f}s to {(i/sample_rate):.3f}s")
                return i

        self.log(f"    - Warning: Could not refine point at ~{(approx_sample_idx/sample_rate):.3f}s. Using original estimate.")
        return approx_sample_idx

    def _assemble_from_pcm_in_memory(self, pcm_data: np.ndarray, edl: List[AudioSegment], channels: int, sample_rate: int) -> np.ndarray:
        """Creates a corrected PCM data stream in a new NumPy array for sample-perfect assembly."""
        base_delay = edl[0].delay_ms
        total_silence_ms = sum(max(0, seg.delay_ms - base_delay) for seg in edl)
        total_silence_samples = int(total_silence_ms / 1000 * sample_rate) * channels

        final_sample_count = pcm_data.shape[0] + total_silence_samples
        new_pcm = np.zeros(final_sample_count, dtype=np.int32)

        current_pos_in_new = 0
        last_pos_in_old = 0

        for segment in edl:
            start_sample = int(segment.start_s * sample_rate) * channels
            end_sample = int(segment.end_s * sample_rate) * channels

            if start_sample > last_pos_in_old:
                gap_chunk = pcm_data[last_pos_in_old:start_sample]
                new_pcm[current_pos_in_new : current_pos_in_new + len(gap_chunk)] = gap_chunk
                current_pos_in_new += len(gap_chunk)

            silence_to_add_ms = segment.delay_ms - base_delay
            if silence_to_add_ms > 10:
                silence_samples = int(silence_to_add_ms / 1000 * sample_rate) * channels
                current_pos_in_new += silence_samples

            segment_chunk = pcm_data[start_sample:end_sample]
            new_pcm[current_pos_in_new : current_pos_in_new + len(segment_chunk)] = segment_chunk
            current_pos_in_new += len(segment_chunk)
            last_pos_in_old = end_sample

        if last_pos_in_old < len(pcm_data):
            final_chunk = pcm_data[last_pos_in_old:]
            new_pcm[current_pos_in_new : current_pos_in_new + len(final_chunk)] = final_chunk

        return new_pcm

    def _encode_pcm_to_file(self, pcm_data: np.ndarray, out_path: Path, channels: int, channel_layout: str, sample_rate: int) -> bool:
        """Encodes a raw PCM NumPy array to a FLAC file via ffmpeg stdin."""
        cmd = [
            'ffmpeg', '-y', '-v', 'error', '-nostdin',
            '-f', 's32le', '-ar', str(sample_rate), '-ac', str(channels), '-channel_layout', channel_layout,
            '-i', '-',
            '-c:a', 'flac', str(out_path)
        ]
        return self.runner.run(cmd, self.tool_paths, is_binary=True, input_data=pcm_data.tobytes()) is not None

    def _qa_check(self, corrected_path: str, ref_file_path: str, base_delay: int) -> bool:
        """Verifies the corrected track against the original reference file with high density."""
        self.log("  [Corrector] Performing rigorous QA check on corrected audio map...")
        qa_config = self.config.copy()
        qa_config.update({'scan_chunk_count': 30, 'min_accepted_chunks': 28, 'min_match_pct': 70.0})
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

            if abs(median_delay - base_delay) > 20:
                self.log(f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms).")
                return False

            if np.std(delays) > 10:
                self.log(f"  [QA] FAILED: Delay is unstable (Std Dev = {np.std(delays):.1f}ms).")
                return False

            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(self, ref_file_path: str, analysis_audio_path: str, target_audio_path: str, base_delay_ms: int, temp_dir: Path) -> Optional[Path]:
        """Main entry point for the correction workflow."""
        self.log(f"  [Corrector] Starting correction for '{Path(target_audio_path).name}' using analysis from '{Path(analysis_audio_path).name}'")

        try:
            ref_index, _ = get_audio_stream_info(ref_file_path, None, self.runner, self.tool_paths)
            analysis_index, _ = get_audio_stream_info(analysis_audio_path, None, self.runner, self.tool_paths)
            target_index, _ = get_audio_stream_info(target_audio_path, None, self.runner, self.tool_paths)
            if ref_index is None or analysis_index is None or target_index is None: return None

            target_channels, target_layout, target_sr = _get_audio_properties(target_audio_path, target_index, self.runner, self.tool_paths)
            self.log(f"  [Corrector] Target audio properties: {target_channels} channels, layout '{target_layout}', {target_sr} Hz")
        except (RuntimeError, ValueError) as e:
            self.log(f"[ERROR] Pre-correction setup failed: {e}"); return None

        self.log("  [Corrector] Decoding analysis tracks to memory (mono)...")
        ref_pcm = self._decode_to_memory(ref_file_path, ref_index, target_sr, 1, force_mono=True)
        analysis_pcm = self._decode_to_memory(analysis_audio_path, analysis_index, target_sr, 1, force_mono=True)
        if ref_pcm is None or analysis_pcm is None: return None
        self.log("  [Corrector] Analysis tracks decoded.")

        edl = self._build_precise_edl(ref_pcm, analysis_pcm, target_sr, base_delay_ms)
        if not edl:
            self.log("  [Corrector] No distinct segments found. Aborting correction."); return None

        self.log("  [Corrector] Assembling and verifying temporary QA track...")
        qa_pcm = self._assemble_from_pcm_in_memory(analysis_pcm, edl, 1, target_sr)
        qa_track_path = temp_dir / "qa_track.flac"
        if not self._encode_pcm_to_file(qa_pcm, qa_track_path, 1, 'mono', target_sr):
             self.log("[ERROR] Corrector failed during temporary track assembly for QA."); return None
        del qa_pcm

        if not self._qa_check(str(qa_track_path), ref_file_path, base_delay_ms):
             self.log("[ERROR] Corrected track map failed QA check. Discarding result."); return None

        del ref_pcm, analysis_pcm; gc.collect()

        self.log(f"  [Corrector] Decoding target audio track to memory ({target_layout})...")
        target_pcm = self._decode_to_memory(target_audio_path, target_index, target_sr, target_channels, force_mono=False)
        if target_pcm is None: return None
        self.log("  [Corrector] Target audio decoded. Assembling final corrected track in memory...")

        final_pcm = self._assemble_from_pcm_in_memory(target_pcm, edl, target_channels, target_sr)
        del target_pcm; gc.collect()

        source_key = Path(target_audio_path).stem.split('_track_')[0]
        final_corrected_path = temp_dir / f"corrected_{source_key}.flac"

        if not self._encode_pcm_to_file(final_pcm, final_corrected_path, target_channels, target_layout, target_sr):
            self.log("[ERROR] Corrector failed during final track assembly."); return None

        del final_pcm; gc.collect()

        return final_corrected_path
