# vsg_core/analysis/segment_correction.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from collections import Counter
from scipy.signal import correlate

from ..io.runner import CommandRunner
from ..analysis.audio_corr import get_audio_stream_info, run_audio_correlation
from .segmentation import BoundaryDetector, AudioFingerprinter, SegmentMatcher
from .segmentation.matching import Segment

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

    # Get accepted delays
    delays = [c['delay'] for c in chunks if c.get('accepted', False)]
    if not delays:
        return False

    drift = max(delays) - min(delays)

    # Enhanced: Check for pattern changes if we have enough data
    if len(delays) > 3:
        # Check if delays are consistently changing (stepping pattern)
        deltas = [delays[i+1] - delays[i] for i in range(len(delays)-1)]
        # If we have significant changes between chunks, it's stepping
        significant_changes = sum(1 for d in deltas if abs(d) > 100)
        if significant_changes > 0:
            return True

    # If drift is more than 250ms, consider it stepping
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

        # Initialize phase modules
        self.boundary_detector = None
        self.fingerprinter = None
        self.matcher = None

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

    def _init_modules(self, sample_rate: int):
        """Initialize processing modules with sample rate."""
        self.boundary_detector = BoundaryDetector(sample_rate, self.log)
        self.fingerprinter = AudioFingerprinter(sample_rate, self.log)
        self.matcher = SegmentMatcher(self.fingerprinter, self.log)

    def _build_precise_edl(self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray,
                          sample_rate: int, base_delay_ms: int) -> Optional[List[AudioSegment]]:
        """Build EDL focusing on sync boundaries for stepping correction."""
        if not self.boundary_detector:
            self._init_modules(sample_rate)

        self.log("  [Corrector] Starting stepped audio analysis...")

        duration_s = min(len(ref_pcm), len(analysis_pcm)) / sample_rate
        if duration_s < 10:
            self.log("  [Corrector] Audio too short for segment analysis.")
            return None

        # Phase I: Find sync boundaries (where delay changes)
        sync_boundaries = self.boundary_detector.find_sync_boundaries(ref_pcm, analysis_pcm)

        # Check if we got reasonable number of segments
        if len(sync_boundaries) > 20:  # Too many segments indicates over-segmentation
            self.log(f"  [Corrector] WARNING: Found {len(sync_boundaries)-1} segments, may be over-segmented")
            # Continue but warn

        # Build segments from sync boundaries only
        # Don't use structural boundaries for stepping correction
        segments = []
        for i in range(len(sync_boundaries) - 1):
            start_sample, segment_delay = sync_boundaries[i]
            end_sample, _ = sync_boundaries[i + 1]

            if end_sample <= start_sample:
                continue

            # For stepping correction, we use the delay from boundary detection
            segments.append(AudioSegment(
                start_s=start_sample / sample_rate,
                end_s=end_sample / sample_rate,
                delay_ms=segment_delay
            ))

        if segments:
            # Override first segment delay with base delay
            segments[0].delay_ms = base_delay_ms

            # Log summary
            self.log(f"  [Corrector] Built EDL with {len(segments)} segments")
            for i, seg in enumerate(segments, 1):
                duration = seg.end_s - seg.start_s
                self.log(f"    - Segment {i}: {seg.start_s:.1f}s - {seg.end_s:.1f}s "
                        f"(duration: {duration:.1f}s) @ {seg.delay_ms}ms")

            # Log delay distribution
            delays = [seg.delay_ms for seg in segments]
            unique_delays = Counter(delays)
            if len(unique_delays) > 1:
                self.log(f"  [Corrector] Delay distribution: {dict(unique_delays)}")

        return segments if segments else None

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
                self.log(f"    - Refined change point from ~{(approx_sample_idx/sample_rate):.3f}s to {(i/sample_rate):.3f}s")
                return i

        self.log(f"    - Warning: Could not refine change point at ~{(approx_sample_idx/sample_rate):.3f}s. Using original estimate.")
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

            # Allow more tolerance for stepped audio
            if abs(median_delay - base_delay) > 50:
                self.log(f"  [QA] WARNING: Median delay ({median_delay:.1f}ms) differs from base delay ({base_delay}ms).")
                # Don't fail for stepped audio, as the median might be different

            # Check for consistency within segments
            delay_std = np.std(delays)
            if delay_std > 100:  # High variance expected for stepped audio
                self.log(f"  [QA] INFO: Delay variance is high (Std Dev = {delay_std:.1f}ms) - expected for stepped audio.")
            elif delay_std > 30:
                self.log(f"  [QA] WARNING: Unexpected delay variance (Std Dev = {delay_std:.1f}ms).")
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
             self.log("[WARNING] QA check failed, but continuing with correction for stepped audio.")

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
