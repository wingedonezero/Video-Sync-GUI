# vsg_core/correction/stepping.py
from __future__ import annotations

import copy
import gc
import json
import shutil
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.signal import correlate

from ..analysis.correlation import get_audio_stream_info, run_audio_correlation
from ..extraction.tracks import extract_tracks
from ..models.media import StreamProps, Track

if TYPE_CHECKING:
    from ..io.runner import CommandRunner
    from ..models.settings import AppSettings
    from ..orchestrator.steps.context import Context


class CorrectionVerdict(Enum):
    UNIFORM = auto()
    STEPPED = auto()
    FAILED = auto()


@dataclass(slots=True)
class CorrectionResult:
    verdict: CorrectionVerdict
    data: Any = None


@dataclass(slots=True, unsafe_hash=True)
class AudioSegment:
    """Represents an action point on the target timeline for the assembly function."""

    start_s: float
    end_s: float
    delay_ms: int
    delay_raw: float = (
        0.0  # Raw float delay for subtitle precision (avoids double rounding)
    )
    drift_rate_ms_s: float = 0.0


def generate_edl_from_correlation(
    chunks: list[dict],
    settings: AppSettings,
    runner: CommandRunner,
    diagnosis_details: dict | None = None,
) -> list[AudioSegment]:
    """
    Generate a simplified EDL from correlation chunks for subtitle adjustment.
    Used when stepping is detected but no audio correction is needed.

    Args:
        chunks: List of correlation chunk results with 'delay', 'accepted', and 'start' keys
        config: Configuration dictionary
        runner: CommandRunner for logging
        diagnosis_details: Optional diagnosis details with filtered cluster information

    Returns:
        List of AudioSegment objects representing delay regions
    """
    accepted = [c for c in chunks if c.get("accepted", False)]
    if not accepted:
        runner._log_message(
            "[EDL Generation] No accepted chunks available for EDL generation"
        )
        return []

    # Apply cluster filtering if diagnosis details are provided
    if diagnosis_details:
        correction_mode = diagnosis_details.get("correction_mode", "full")
        if correction_mode == "filtered":
            invalid_clusters = diagnosis_details.get("invalid_clusters", {})
            validation_results = diagnosis_details.get("validation_results", {})

            if invalid_clusters:
                # Build list of invalid time ranges
                invalid_time_ranges = []
                for label in invalid_clusters:
                    if label in validation_results:
                        time_range = validation_results[label].time_range
                        invalid_time_ranges.append(time_range)

                # Filter out chunks that fall within invalid clusters
                filtered_accepted = []
                filtered_count = 0
                for chunk in accepted:
                    chunk_time = chunk["start"]
                    in_invalid_cluster = any(
                        start <= chunk_time <= end for start, end in invalid_time_ranges
                    )
                    if not in_invalid_cluster:
                        filtered_accepted.append(chunk)
                    else:
                        filtered_count += 1

                runner._log_message(
                    f"[EDL Generation] Filtered {filtered_count} chunks from invalid clusters"
                )
                runner._log_message(
                    f"[EDL Generation] Using {len(filtered_accepted)} chunks from valid clusters only"
                )
                accepted = filtered_accepted

                if not accepted:
                    runner._log_message(
                        "[EDL Generation] No chunks remaining after filtering"
                    )
                    return []

    # Group consecutive chunks by delay (within tolerance)
    tolerance_ms = settings.segment_triage_std_dev_ms
    edl = []
    current_delay_ms = accepted[0]["delay"]
    current_delay_raw = accepted[0].get("raw_delay", float(current_delay_ms))
    edl.append(
        AudioSegment(
            start_s=0.0,
            end_s=0.0,
            delay_ms=current_delay_ms,
            delay_raw=current_delay_raw,
        )
    )

    runner._log_message(
        f"[EDL Generation] Starting with delay: {current_delay_ms}ms (raw: {current_delay_raw:.3f}ms)"
    )

    for chunk in accepted[1:]:
        delay_diff = abs(chunk["delay"] - current_delay_ms)
        if delay_diff > tolerance_ms:
            # Delay change detected - add new segment
            boundary_time_s = chunk["start"]  # Chunk start time in seconds
            current_delay_ms = chunk["delay"]
            current_delay_raw = chunk.get("raw_delay", float(current_delay_ms))
            edl.append(
                AudioSegment(
                    start_s=boundary_time_s,
                    end_s=boundary_time_s,
                    delay_ms=current_delay_ms,
                    delay_raw=current_delay_raw,
                    drift_rate_ms_s=0.0,  # No drift analysis for subtitle-only
                )
            )
            runner._log_message(
                f"[EDL Generation] Delay change at {boundary_time_s:.1f}s → {current_delay_ms}ms (raw: {current_delay_raw:.3f}ms)"
            )

    runner._log_message(f"[EDL Generation] Generated EDL with {len(edl)} segment(s)")
    return edl


def _get_audio_properties(
    file_path: str, stream_index: int, runner: CommandRunner, tool_paths: dict
) -> tuple[int, str, int]:
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
        stream_info = json.loads(out)["streams"][0]
        channels = int(stream_info.get("channels", 2))
        channel_layout = stream_info.get(
            "channel_layout",
            {1: "mono", 2: "stereo", 6: "5.1(side)", 8: "7.1"}.get(channels, "stereo"),
        )
        sample_rate = int(stream_info.get("sample_rate", 48000))
        return channels, channel_layout, sample_rate
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        raise RuntimeError(f"Failed to parse ffprobe audio properties: {e}")


class SteppingCorrector:
    def __init__(self, runner: CommandRunner, tool_paths: dict, settings: AppSettings):
        self.runner = runner
        self.tool_paths = tool_paths
        self.settings = settings
        self.log = runner._log_message
        self.audit_metadata = []  # Store audit metadata for quality checks

    def _get_codec_id(self, file_path: str) -> str:
        """Uses ffprobe to get the codec name for a given audio file."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        out = self.runner.run(cmd, self.tool_paths)
        return (out or "").strip().lower()

    def _decode_to_memory(
        self, file_path: str, stream_index: int, sample_rate: int, channels: int = 1
    ) -> np.ndarray | None:
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
        pcm_bytes = self.runner.run(cmd, self.tool_paths, is_binary=True)
        if pcm_bytes:
            # Ensure buffer size is a multiple of element size (4 bytes for int32)
            # This fixes issues with Opus and other codecs that may produce unaligned output
            element_size = np.dtype(np.int32).itemsize
            aligned_size = (len(pcm_bytes) // element_size) * element_size
            if aligned_size != len(pcm_bytes):
                trimmed_bytes = len(pcm_bytes) - aligned_size
                self.log(
                    f"[BUFFER ALIGNMENT] Trimmed {trimmed_bytes} bytes from {Path(file_path).name} (likely Opus/other codec)"
                )
                pcm_bytes = pcm_bytes[:aligned_size]
            # CRITICAL: Return a COPY, not a view over the buffer.
            # np.frombuffer() creates a view that can become invalid if the underlying
            # buffer is garbage collected. Using .copy() ensures we own the memory.
            return np.frombuffer(pcm_bytes, dtype=np.int32).copy()
        self.log(
            f"[ERROR] SteppingCorrector failed to decode audio stream {stream_index} from '{Path(file_path).name}'"
        )
        return None

    def _get_delay_for_chunk(
        self,
        ref_pcm: np.ndarray,
        analysis_pcm: np.ndarray,
        start_sample: int,
        num_samples: int,
        sample_rate: int,
        locality_samples: int,
    ) -> tuple | None:
        """
        Get delay for a chunk via correlation.

        Returns:
            tuple of (delay_ms: int, delay_raw: float) or None if detection failed
        """
        end_sample = start_sample + num_samples
        if end_sample > len(ref_pcm):
            return None
        ref_chunk = ref_pcm[start_sample:end_sample]

        search_center = start_sample
        search_start = max(0, search_center - locality_samples)
        search_end = min(
            len(analysis_pcm), search_center + num_samples + locality_samples
        )
        analysis_chunk = analysis_pcm[search_start:search_end]

        if len(ref_chunk) < 100 or len(analysis_chunk) < len(ref_chunk):
            return None
        ref_std, analysis_std = np.std(ref_chunk), np.std(analysis_chunk)
        # For int32 PCM audio, std < 100 indicates silence/near-silence
        # This prevents division by zero in correlation
        if ref_std < 100.0 or analysis_std < 100.0:
            return None

        r = (ref_chunk - np.mean(ref_chunk)) / (ref_std + 1e-9)
        t = (analysis_chunk - np.mean(analysis_chunk)) / (analysis_std + 1e-9)

        # Suppress numpy warnings about division by zero in correlation
        # We've already filtered out silent chunks above, but numpy's internal
        # correlation calculations may still produce warnings for edge cases
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "invalid value encountered in divide")
            c = correlate(r, t, mode="valid", method="fft")

        if len(c) == 0:
            return None
        abs_c = np.abs(c)
        k = np.argmax(abs_c)

        peak_val = abs_c[k]
        noise_floor = np.median(abs_c) + 1e-9
        confidence_ratio = peak_val / noise_floor

        min_confidence = self.settings.segment_min_confidence_ratio
        if confidence_ratio < min_confidence:
            return None

        lag_in_window = k
        absolute_lag_start = search_start + lag_in_window
        delay_samples = absolute_lag_start - start_sample
        delay_raw = (delay_samples / sample_rate) * 1000.0
        delay_ms = int(round(delay_raw))
        return (delay_ms, delay_raw)

    def _perform_coarse_scan(
        self, ref_pcm: np.ndarray, analysis_pcm: np.ndarray, sample_rate: int
    ) -> list[tuple[float, int, float]]:
        """
        Perform coarse scan to find delay zones.

        Returns:
            List of (timestamp_s, delay_ms, delay_raw) tuples
        """
        self.log(
            "  [SteppingCorrector] Stage 1: Performing coarse scan to find delay zones..."
        )
        chunk_duration_s = self.settings.segment_coarse_chunk_s
        step_duration_s = self.settings.segment_coarse_step_s
        locality_s = self.settings.segment_search_locality_s

        chunk_samples = int(chunk_duration_s * sample_rate)
        step_samples = int(step_duration_s * sample_rate)
        locality_samples = int(locality_s * sample_rate)
        coarse_map = []
        num_samples = min(len(ref_pcm), len(analysis_pcm))
        duration_s = len(ref_pcm) / float(sample_rate)

        # Use stepping-specific scan ranges (independent from main analysis settings)
        start_pct = self.settings.stepping_scan_start_percentage
        end_pct = self.settings.stepping_scan_end_percentage
        scan_start_s = duration_s * (start_pct / 100.0)
        scan_end_s = duration_s * (end_pct / 100.0)
        start_offset_samples = int(scan_start_s * sample_rate)
        scan_end_limit = min(int(scan_end_s * sample_rate), num_samples)
        scan_end_point = scan_end_limit - chunk_samples - step_samples

        for start_sample in range(start_offset_samples, scan_end_point, step_samples):
            result = self._get_delay_for_chunk(
                ref_pcm,
                analysis_pcm,
                start_sample,
                chunk_samples,
                sample_rate,
                locality_samples,
            )
            if result is not None:
                delay_ms, delay_raw = result
                timestamp_s = start_sample / sample_rate
                coarse_map.append((timestamp_s, delay_ms, delay_raw))
                self.log(
                    f"    - Coarse point at {timestamp_s:.1f}s: delay = {delay_ms}ms (raw: {delay_raw:.3f}ms)"
                )
        return coarse_map

    def _find_boundary_in_zone(
        self,
        ref_pcm: np.ndarray,
        analysis_pcm: np.ndarray,
        sample_rate: int,
        zone_start_s: float,
        zone_end_s: float,
        delay_before: int,
        delay_after: int,
        ref_file_path: str | None = None,
        analysis_file_path: str | None = None,
    ) -> float:
        """
        Finds the precise boundary where audio delay changes from delay_before to delay_after.

        Algorithm:
        1. Binary Search: Narrow down the zone by checking which delay each chunk matches
        2. Silence Snapping: Move boundary to silence zone in target audio to avoid cutting speech
        3. Video Snapping (optional): Align boundary with video keyframe/scene if within silence

        Timeline Conversions:
        - Reference timeline: Position in reference (Source 1) audio
        - Target timeline: Position in target (Source 2+) audio = reference_time + delay_offset
        - Silence detection happens in TARGET audio (where we'll cut)
        - Video detection happens in REFERENCE video (frame sync source)

        Returns: Final boundary position in reference timeline (seconds)
        """
        self.log(
            f"  [SteppingCorrector] Stage 2: Performing fine scan in zone {zone_start_s:.1f}s - {zone_end_s:.1f}s..."
        )
        zone_start_sample, zone_end_sample = (
            int(zone_start_s * sample_rate),
            int(zone_end_s * sample_rate),
        )

        # Configuration for iterative binary search
        fine_chunk_s = self.settings.segment_fine_chunk_s
        locality_s = self.settings.segment_search_locality_s
        iterations = self.settings.segment_fine_iterations

        chunk_samples = int(fine_chunk_s * sample_rate)
        locality_samples = int(locality_s * sample_rate)
        low, high = zone_start_sample, zone_end_sample

        # STAGE 1: Binary search to locate delay transition point
        # Each iteration checks the midpoint and narrows the search based on which delay it matches
        for _ in range(iterations):
            if high - low < chunk_samples:
                break
            mid = (low + high) // 2
            result = self._get_delay_for_chunk(
                ref_pcm, analysis_pcm, mid, chunk_samples, sample_rate, locality_samples
            )
            if result is not None:
                delay_ms, _ = result  # Only need rounded for boundary comparison
                # Move search window based on which delay this chunk matches
                if abs(delay_ms - delay_before) < abs(delay_ms - delay_after):
                    low = mid
                else:
                    high = mid
            else:
                low += chunk_samples

        # Binary search complete - 'high' is the boundary in reference timeline
        initial_boundary_s = high / sample_rate
        initial_boundary_target_s = initial_boundary_s + (delay_before / 1000.0)

        self.log("    - [Boundary Detection] Initial position:")
        self.log(f"        Reference: {initial_boundary_s:.3f}s")
        self.log(
            f"        Target:    {initial_boundary_target_s:.3f}s (ref + {delay_before}ms delay)"
        )

        # STAGE 2: Silence-aware boundary snapping
        # CRITICAL: We cut the TARGET audio, so silence detection must happen in target timeline.
        # Convert reference boundary to target timeline by adding the delay offset.
        snapped_boundary_target_s, boundary_metadata = self._snap_boundary_to_silence(
            analysis_pcm, sample_rate, initial_boundary_target_s, analysis_file_path
        )

        # Store metadata for audit (includes silence zone info, score, speech/transient flags)
        if boundary_metadata:
            boundary_metadata["target_time_s"] = snapped_boundary_target_s
            boundary_metadata["delay_change_ms"] = delay_after - delay_before
            self.audit_metadata.append(boundary_metadata)

        # Convert snapped boundary back to reference timeline for further processing
        final_boundary_s = snapped_boundary_target_s - (delay_before / 1000.0)

        if abs(snapped_boundary_target_s - initial_boundary_target_s) > 0.001:
            offset_s = snapped_boundary_target_s - initial_boundary_target_s
            self.log("    - [After Audio Snap] Adjusted position:")
            self.log(
                f"        Reference: {final_boundary_s:.3f}s (was {initial_boundary_s:.3f}s, moved {offset_s:+.3f}s)"
            )
            self.log(
                f"        Target:    {snapped_boundary_target_s:.3f}s (snapped to silence center)"
            )

        # STAGE 3: Video-aware boundary snapping (optional)
        # Video snap operates on REFERENCE timeline (we sync subtitles to reference video frames).
        # Must validate that video snap doesn't move outside the silence zone we found in target audio.
        if ref_file_path and boundary_metadata:
            video_snapped_boundary_s = self._snap_boundary_to_video_frame(
                ref_file_path, final_boundary_s
            )
            if abs(video_snapped_boundary_s - final_boundary_s) > 0.001:
                # Validate: Convert video-snapped boundary to target timeline and check silence zone
                video_snapped_target_s = video_snapped_boundary_s + (
                    delay_before / 1000.0
                )
                silence_start = boundary_metadata.get("zone_start", 0)
                silence_end = boundary_metadata.get("zone_end", 0)
                no_silence = boundary_metadata.get("no_silence_found", False)

                # Only validate if we had a real silence zone (otherwise no constraint)
                if not no_silence and (
                    video_snapped_target_s < silence_start
                    or video_snapped_target_s > silence_end
                ):
                    self.log(
                        f"    - [Video Snap] ⚠️  Keyframe at {video_snapped_boundary_s:.3f}s (target: {video_snapped_target_s:.3f}s) is outside silence zone"
                    )
                    self.log(
                        f"    - [Video Snap] Silence zone: [{silence_start:.3f}s - {silence_end:.3f}s]"
                    )
                    self.log(
                        "    - [Video Snap] Keeping audio-snapped boundary to maintain silence guarantee"
                    )
                    # Flag this in metadata for audit
                    boundary_metadata["video_snap_skipped"] = True
                    boundary_metadata["video_snap_reason"] = "outside_silence_zone"
                else:
                    # Video snap is valid - apply it
                    old_final = final_boundary_s
                    final_boundary_s = video_snapped_boundary_s
                    final_target_s = final_boundary_s + (delay_before / 1000.0)
                    self.log("    - [After Video Snap] Final adjusted position:")
                    self.log(
                        f"        Reference: {final_boundary_s:.3f}s (was {old_final:.3f}s, moved to keyframe)"
                    )
                    self.log(f"        Target:    {final_target_s:.3f}s")
                    boundary_metadata["video_snap_applied"] = True

        # Final summary
        final_target_s = final_boundary_s + (delay_before / 1000.0)
        delay_change = delay_after - delay_before
        self.log("    - [Final Boundary] Correction will be applied at:")
        self.log(f"        Reference: {final_boundary_s:.3f}s")
        self.log(f"        Target:    {final_target_s:.3f}s")
        self.log(
            f"        Action:    {'ADD' if delay_change > 0 else 'REMOVE'} {abs(delay_change)}ms"
        )

        return final_boundary_s

    def _find_silence_zones_ffmpeg(
        self,
        audio_file: str,
        start_s: float,
        end_s: float,
        threshold_db: float,
        min_duration_s: float,
    ) -> list[tuple[float, float, float]]:
        """
        Find silence zones using FFmpeg's silencedetect filter (frame-accurate).

        Args:
            audio_file: Path to audio file
            start_s: Start of search window in seconds
            end_s: End of search window in seconds
            threshold_db: Silence threshold in dB
            min_duration_s: Minimum silence duration in seconds

        Returns:
            List of tuples (start_s, end_s, avg_db) for each silence zone
        """
        import re

        duration_s = end_s - start_s
        if duration_s <= 0:
            return []

        # Run FFmpeg silencedetect filter
        cmd = [
            "ffmpeg",
            "-ss",
            str(start_s),
            "-t",
            str(duration_s),
            "-i",
            audio_file,
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_duration_s}",
            "-f",
            "null",
            "-",
        ]

        try:
            result = self.runner.run(cmd, self.tool_paths)
            if result is None:
                self.log(
                    "    - [FFmpeg silencedetect] Warning: Failed to run silencedetect"
                )
                return []

            # Parse stderr output for silence_start and silence_end
            # Format: [silencedetect @ ...] silence_start: 123.456
            #         [silencedetect @ ...] silence_end: 125.678 | silence_duration: 2.222
            silence_zones = []
            silence_start = None

            for line in result.splitlines():
                # Look for silence_start
                start_match = re.search(r"silence_start:\s*([\d.]+)", line)
                if start_match:
                    silence_start = (
                        float(start_match.group(1)) + start_s
                    )  # Adjust for -ss offset
                    continue

                # Look for silence_end
                end_match = re.search(r"silence_end:\s*([\d.]+)", line)
                if end_match and silence_start is not None:
                    silence_end = (
                        float(end_match.group(1)) + start_s
                    )  # Adjust for -ss offset

                    # Estimate average dB (FFmpeg doesn't provide this, use threshold as estimate)
                    avg_db = threshold_db - 5.0  # Assume it's quieter than threshold

                    silence_zones.append((silence_start, silence_end, avg_db))
                    silence_start = None

            self.log(
                f"    - [FFmpeg silencedetect] Found {len(silence_zones)} silence zone(s) with threshold {threshold_db}dB"
            )
            return silence_zones

        except Exception as e:
            self.log(f"    - [FFmpeg silencedetect] Error: {e}")
            return []

    def _find_silence_zones(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        start_s: float,
        end_s: float,
        threshold_db: float,
        min_duration_ms: float,
    ) -> list[tuple[float, float, float]]:
        """
        Find silence zones in audio within a time window using RMS-based detection.

        Args:
            pcm: Audio PCM data (mono, int32)
            sample_rate: Sample rate in Hz
            start_s: Start of search window in seconds
            end_s: End of search window in seconds
            threshold_db: Silence threshold in dB
            min_duration_ms: Minimum silence duration in milliseconds

        Returns:
            List of tuples (start_s, end_s, avg_db) for each silence zone
        """
        start_sample = max(0, int(start_s * sample_rate))
        end_sample = min(len(pcm), int(end_s * sample_rate))

        if end_sample <= start_sample:
            return []

        # Window size for RMS calculation (50ms windows)
        window_size = int(0.05 * sample_rate)
        window_size = max(window_size, 1)

        min_silence_samples = int((min_duration_ms / 1000.0) * sample_rate)

        silence_zones = []
        current_silence_start = None
        current_silence_db_values = []

        # Scan through the region in windows
        for sample_pos in range(start_sample, end_sample, window_size):
            window_end = min(sample_pos + window_size, end_sample)
            window = pcm[sample_pos:window_end]

            if len(window) == 0:
                continue

            # Calculate RMS amplitude
            rms = np.sqrt(np.mean(window.astype(np.float64) ** 2))

            # Convert to dB (with safeguard against log(0))
            if rms > 1e-10:
                db = 20 * np.log10(rms / 2147483648.0)  # int32 max = 2^31
            else:
                db = -96.0  # Very quiet

            is_silence = db < threshold_db

            if is_silence:
                if current_silence_start is None:
                    current_silence_start = sample_pos / sample_rate
                    current_silence_db_values = [db]
                else:
                    current_silence_db_values.append(db)
            elif current_silence_start is not None:
                # End of silence zone
                silence_end = sample_pos / sample_rate
                silence_duration_samples = (
                    silence_end - current_silence_start
                ) * sample_rate

                if silence_duration_samples >= min_silence_samples:
                    avg_db = np.mean(current_silence_db_values)
                    silence_zones.append((current_silence_start, silence_end, avg_db))

                current_silence_start = None
                current_silence_db_values = []

        # Check if we're still in a silence zone at the end
        if current_silence_start is not None:
            silence_end = end_sample / sample_rate
            silence_duration_samples = (
                silence_end - current_silence_start
            ) * sample_rate
            if silence_duration_samples >= min_silence_samples:
                avg_db = np.mean(current_silence_db_values)
                silence_zones.append((current_silence_start, silence_end, avg_db))

        return silence_zones

    def _detect_speech_regions_vad(
        self, pcm: np.ndarray, sample_rate: int, start_s: float, end_s: float
    ) -> list[tuple[float, float]]:
        """
        Detect speech regions using Voice Activity Detection (WebRTC VAD).
        Requires webrtcvad library: pip install webrtcvad-wheels

        Args:
            pcm: Audio PCM data (mono, int32)
            sample_rate: Sample rate in Hz
            start_s: Start of search window in seconds
            end_s: End of search window in seconds

        Returns:
            List of tuples (start_s, end_s) for each speech region
        """
        if not self.settings.stepping_vad_enabled:
            return []

        try:
            import webrtcvad
        except ImportError:
            self.log("    - [VAD] webrtcvad not installed, skipping speech detection")
            self.log("    - [VAD] Install with: pip install webrtcvad-wheels")
            return []

        aggressiveness = self.settings.stepping_vad_aggressiveness
        frame_duration_ms = self.settings.stepping_vad_frame_duration_ms

        # VAD only works with specific sample rates
        vad_sample_rate = 16000 if sample_rate >= 16000 else 8000

        # Convert to required format
        start_sample = max(0, int(start_s * sample_rate))
        end_sample = min(len(pcm), int(end_s * sample_rate))
        audio_segment = pcm[start_sample:end_sample]

        if len(audio_segment) == 0:
            return []

        # Resample if needed and convert to int16
        if sample_rate != vad_sample_rate:
            # Simple decimation for downsampling
            step = sample_rate // vad_sample_rate
            audio_segment = audio_segment[::step]

        # Convert int32 to int16 for VAD
        audio_int16 = (audio_segment / 65536).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        # Initialize VAD
        vad = webrtcvad.Vad(aggressiveness)

        # Process in frames
        frame_size = int(
            vad_sample_rate * frame_duration_ms / 1000
        )  # samples per frame
        frame_bytes = frame_size * 2  # 2 bytes per int16 sample

        speech_regions = []
        speech_start = None

        for i in range(0, len(audio_bytes) - frame_bytes, frame_bytes):
            frame = audio_bytes[i : i + frame_bytes]
            is_speech = vad.is_speech(frame, vad_sample_rate)

            frame_time_s = start_s + (
                i / 2 / vad_sample_rate
            )  # Convert byte position to time

            if is_speech and speech_start is None:
                speech_start = frame_time_s
            elif not is_speech and speech_start is not None:
                speech_regions.append((speech_start, frame_time_s))
                speech_start = None

        # Close final region if still open
        if speech_start is not None:
            speech_regions.append((speech_start, end_s))

        self.log(f"    - [VAD] Detected {len(speech_regions)} speech region(s)")
        return speech_regions

    def _detect_transients(
        self, pcm: np.ndarray, sample_rate: int, start_s: float, end_s: float
    ) -> list[float]:
        """
        Detect transients (sudden amplitude increases like musical beats/impacts).

        Args:
            pcm: Audio PCM data (mono, int32)
            sample_rate: Sample rate in Hz
            start_s: Start of search window in seconds
            end_s: End of search window in seconds

        Returns:
            List of timestamps where transients occur
        """
        if not self.settings.stepping_transient_detection_enabled:
            return []

        threshold_db = self.settings.stepping_transient_threshold

        start_sample = max(0, int(start_s * sample_rate))
        end_sample = min(len(pcm), int(end_s * sample_rate))

        if end_sample <= start_sample:
            return []

        # Window size for RMS calculation (10ms windows)
        window_size = int(0.01 * sample_rate)
        window_size = max(window_size, 1)

        transients = []
        prev_rms_db = None

        # Scan through the region in windows
        for sample_pos in range(start_sample, end_sample - window_size, window_size):
            window = pcm[sample_pos : sample_pos + window_size]

            if len(window) == 0:
                continue

            # Calculate RMS amplitude
            rms = np.sqrt(np.mean(window.astype(np.float64) ** 2))

            # Convert to dB
            if rms > 1e-10:
                rms_db = 20 * np.log10(rms / 2147483648.0)
            else:
                rms_db = -96.0

            # Detect sudden increase (transient)
            if prev_rms_db is not None:
                increase_db = rms_db - prev_rms_db
                if increase_db >= threshold_db:
                    transient_time_s = sample_pos / sample_rate
                    transients.append(transient_time_s)

            prev_rms_db = rms_db

        self.log(
            f"    - [Transient Detection] Found {len(transients)} transient(s) with threshold {threshold_db}dB"
        )
        return transients

    def _snap_boundary_to_silence(
        self,
        analysis_pcm: np.ndarray,
        sample_rate: int,
        boundary_s: float,
        analysis_file: str | None = None,
    ) -> tuple[float, dict | None]:
        """
        Attempt to snap a boundary to a nearby silence zone using advanced detection methods.

        Args:
            analysis_pcm: Target audio PCM data
            sample_rate: Sample rate in Hz
            boundary_s: Original boundary position in seconds
            analysis_file: Path to analysis audio file (required for FFmpeg silencedetect)

        Returns:
            Tuple of (new_boundary_position, audit_metadata_dict) or (original_boundary, None)
        """
        if not self.settings.stepping_snap_to_silence:
            return boundary_s, None

        self.log(
            f"    - [Smart Boundary] Analyzing target audio near {boundary_s:.3f}s..."
        )

        detection_method = self.settings.stepping_silence_detection_method
        search_window_s = self.settings.stepping_silence_search_window_s
        threshold_db = self.settings.stepping_silence_threshold_db
        min_duration_ms = self.settings.stepping_silence_min_duration_ms

        # Search for silence zones around the boundary
        search_start = max(0, boundary_s - search_window_s)
        search_end = boundary_s + search_window_s

        # Select detection method
        silence_zones = []

        if detection_method == "ffmpeg_silencedetect" and analysis_file:
            # Use FFmpeg's silencedetect for frame-accurate detection
            ffmpeg_threshold = self.settings.stepping_ffmpeg_silence_noise
            ffmpeg_duration = self.settings.stepping_ffmpeg_silence_duration
            silence_zones = self._find_silence_zones_ffmpeg(
                analysis_file,
                search_start,
                search_end,
                ffmpeg_threshold,
                ffmpeg_duration,
            )
        elif detection_method == "rms_basic":
            # Use traditional RMS-based detection
            silence_zones = self._find_silence_zones(
                analysis_pcm,
                sample_rate,
                search_start,
                search_end,
                threshold_db,
                min_duration_ms,
            )
        elif detection_method == "smart_fusion":
            # Use multi-signal fusion approach
            # Try FFmpeg first if available, fallback to RMS
            if analysis_file:
                ffmpeg_threshold = self.settings.stepping_ffmpeg_silence_noise
                ffmpeg_duration = self.settings.stepping_ffmpeg_silence_duration
                silence_zones = self._find_silence_zones_ffmpeg(
                    analysis_file,
                    search_start,
                    search_end,
                    ffmpeg_threshold,
                    ffmpeg_duration,
                )

            # Fallback to RMS if FFmpeg failed or no file provided
            if not silence_zones:
                silence_zones = self._find_silence_zones(
                    analysis_pcm,
                    sample_rate,
                    search_start,
                    search_end,
                    threshold_db,
                    min_duration_ms,
                )
        else:
            # Default to RMS
            silence_zones = self._find_silence_zones(
                analysis_pcm,
                sample_rate,
                search_start,
                search_end,
                threshold_db,
                min_duration_ms,
            )

        if not silence_zones:
            self.log(
                f"    - [Silence Snap] ⚠️  No silence zones found within ±{search_window_s}s window"
            )
            self.log(
                "    - [Silence Snap] Using raw boundary without silence guarantee"
            )
            # Return metadata to flag this in audit
            no_silence_metadata = {
                "zone_start": boundary_s,
                "zone_end": boundary_s,
                "snap_point": boundary_s,
                "avg_db": 0.0,
                "score": 0.0,
                "overlaps_speech": False,
                "near_transient": False,
                "duration": 0.0,
                "no_silence_found": True,  # Flag for audit
            }
            return boundary_s, no_silence_metadata

        # Get additional signals for smart fusion
        speech_regions = []
        transients = []

        if detection_method == "smart_fusion":
            # Detect speech regions to avoid
            if (
                self.settings.stepping_vad_enabled
                and self.settings.stepping_vad_avoid_speech
            ):
                speech_regions = self._detect_speech_regions_vad(
                    analysis_pcm, sample_rate, search_start, search_end
                )

            # Detect transients to avoid
            if self.settings.stepping_transient_detection_enabled:
                transients = self._detect_transients(
                    analysis_pcm, sample_rate, search_start, search_end
                )

        # Score each silence zone using multi-signal fusion
        best_candidate = None
        best_score = -float("inf")  # Higher score is better

        # Get scoring weights
        weight_silence = self.settings.stepping_fusion_weight_silence
        weight_no_speech = self.settings.stepping_fusion_weight_no_speech
        weight_duration = self.settings.stepping_fusion_weight_duration
        weight_no_transient = self.settings.stepping_fusion_weight_no_transient
        transient_avoid_window_ms = (
            self.settings.stepping_transient_avoid_window_ms / 1000.0
        )

        for zone_start, zone_end, avg_db in silence_zones:
            zone_center = (zone_start + zone_end) / 2.0
            zone_duration = zone_end - zone_start

            # Determine snap point: use center of zone for safety
            snap_point = zone_center

            # Calculate score based on multiple factors
            score = 0

            # 1. Silence depth (quieter is better)
            silence_depth_score = (
                max(0, (threshold_db - avg_db) / 10.0) * weight_silence
            )
            score += silence_depth_score

            # 2. Distance to original boundary (closer is better)
            distance = abs(snap_point - boundary_s)
            distance_score = max(0, (search_window_s - distance) / search_window_s) * 5
            score += distance_score

            # 3. Zone duration (longer silence is better for smooth cuts)
            duration_score = min(zone_duration / 1.0, 1.0) * weight_duration
            score += duration_score

            # 4. Speech avoidance (penalize zones with speech)
            overlaps_speech = False
            if speech_regions:
                for speech_start, speech_end in speech_regions:
                    if not (snap_point < speech_start or snap_point > speech_end):
                        overlaps_speech = True
                        break

            if not overlaps_speech:
                score += weight_no_speech
            else:
                score -= weight_no_speech * 2  # Heavy penalty for speech

            # 5. Transient avoidance (penalize zones near musical beats)
            near_transient = False
            if transients:
                for transient_time in transients:
                    if abs(snap_point - transient_time) < transient_avoid_window_ms:
                        near_transient = True
                        break

            if not near_transient:
                score += weight_no_transient
            else:
                score -= weight_no_transient  # Moderate penalty for transients

            # Track best candidate
            if score > best_score:
                best_score = score
                best_candidate = {
                    "zone_start": zone_start,
                    "zone_end": zone_end,
                    "snap_point": snap_point,
                    "avg_db": avg_db,
                    "score": score,
                    "overlaps_speech": overlaps_speech,
                    "near_transient": near_transient,
                    "duration": zone_duration,
                }

        if best_candidate:
            snap_point = best_candidate["snap_point"]
            zone_start = best_candidate["zone_start"]
            zone_end = best_candidate["zone_end"]
            avg_db = best_candidate["avg_db"]
            offset = snap_point - boundary_s

            # Log the decision
            self.log(
                f"    - [Smart Boundary] Found silence zone [{zone_start:.3f}s - {zone_end:.3f}s, {avg_db:.1f}dB]"
            )
            self.log(
                f"    - [Smart Boundary] Snapping: {boundary_s:.3f}s → {snap_point:.3f}s (offset: {offset:+.3f}s)"
            )
            self.log(
                f"    - [Smart Boundary] Score: {best_candidate['score']:.1f} | Speech: {'YES' if best_candidate['overlaps_speech'] else 'NO'} | Transient: {'YES' if best_candidate['near_transient'] else 'NO'}"
            )

            return snap_point, best_candidate

        return boundary_s, None

    def _get_video_frames(self, video_file: str, mode: str) -> list[float]:
        """
        Get video frame timestamps from reference video.

        Args:
            video_file: Path to video file
            mode: 'scenes', 'keyframes', or 'any_frame'

        Returns:
            List of timestamps in seconds
        """
        import json

        if mode == "scenes":
            # Scene detection via lavfi is fragile with special characters in paths
            # Use keyframes as a reliable alternative that works with all file paths
            # Keyframes often align with scene changes anyway (especially for encoded content)
            self.log(
                "    - [Video Snap] Using keyframes for scene-aligned snapping (robust for all file paths)"
            )
            return self._get_video_frames(video_file, "keyframes")

        elif mode == "keyframes":
            # Get I-frames (keyframes) using ffprobe
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time,flags",
                "-of",
                "json",
                video_file,
            ]

            try:
                result = self.runner.run(cmd, self.tool_paths)
                if result is None:
                    return []

                data = json.loads(result)
                keyframes = []

                for packet in data.get("packets", []):
                    if "K" in packet.get("flags", ""):  # K = keyframe
                        try:
                            keyframes.append(float(packet["pts_time"]))
                        except (KeyError, ValueError, TypeError):
                            continue

                self.log(f"    - [Video Snap] Found {len(keyframes)} keyframes")
                return sorted(keyframes)

            except Exception as e:
                self.log(f"    - [Video Snap] ERROR: Failed to get keyframes: {e}")
                return []

        elif mode == "any_frame":
            # Get all frame timestamps
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "json",
                video_file,
            ]

            try:
                result = self.runner.run(cmd, self.tool_paths)
                if result is None:
                    return []

                data = json.loads(result)
                frames = []

                for packet in data.get("packets", []):
                    try:
                        frames.append(float(packet["pts_time"]))
                    except (KeyError, ValueError, TypeError):
                        continue

                self.log(f"    - [Video Snap] Found {len(frames)} total frames")
                return sorted(frames)

            except Exception as e:
                self.log(f"    - [Video Snap] ERROR: Failed to get frames: {e}")
                return []

        return []

    def _snap_boundary_to_video_frame(
        self, video_file: str, boundary_s: float
    ) -> float:
        """
        Attempt to snap a boundary to a nearby video frame or scene.

        Args:
            video_file: Path to reference video file
            boundary_s: Original boundary position in seconds (reference timeline)

        Returns:
            New boundary position (or original if no suitable frame found)
        """
        if not self.settings.stepping_snap_to_video_frames:
            return boundary_s

        snap_mode = self.settings.stepping_video_snap_mode
        max_offset = self.settings.stepping_video_snap_max_offset_s

        self.log(
            f"    - [Video Snap] Analyzing reference video near {boundary_s:.3f}s..."
        )

        # Get video frame/scene positions
        video_positions = self._get_video_frames(video_file, snap_mode)

        if not video_positions:
            self.log(
                f"    - [Video Snap] No {snap_mode} detected, keeping audio-based boundary"
            )
            return boundary_s

        # Find nearest position
        nearest = min(video_positions, key=lambda x: abs(x - boundary_s))
        offset = nearest - boundary_s

        # Check if within acceptable range
        if abs(offset) <= max_offset:
            self.log(
                f"    - [Video Snap] Found {snap_mode[:-1]} at {nearest:.3f}s (moved {offset:+.3f}s to align with video)"
            )
            return nearest
        else:
            self.log(
                f"    - [Video Snap] Nearest {snap_mode[:-1]} at {nearest:.3f}s is too far (offset: {offset:+.3f}s > {max_offset:.1f}s)"
            )
            self.log("    - [Video Snap] Keeping audio-based boundary")
            return boundary_s

    def _extract_content_from_reference(
        self,
        ref_pcm: np.ndarray,
        analysis_pcm: np.ndarray,
        boundary_s_target: float,
        gap_duration_ms: float,
        sample_rate: int,
        current_delay_ms: float,
    ) -> tuple[np.ndarray | None, float, str]:
        """
        Attempts to extract matching content from reference audio to fill a gap.

        Args:
            boundary_s_target: Position on the TARGET timeline (where the gap will be inserted)
            current_delay_ms: The current delay BEFORE the jump (to convert to reference timeline)

        Returns:
            Tuple of (extracted_pcm, correlation_score, fill_type)
            fill_type: 'content' if good match found, 'silence' otherwise
        """
        fill_mode = self.settings.stepping_fill_mode
        correlation_threshold = self.settings.stepping_content_correlation_threshold
        search_window_s = self.settings.stepping_content_search_window_s

        # Force silence mode if configured
        if fill_mode == "silence":
            return None, 0.0, "silence"

        gap_samples = int((gap_duration_ms / 1000.0) * sample_rate)

        # CRITICAL FIX: Convert target timeline position to reference timeline position
        # The boundary_s_target is on the target (analysis) timeline, but we need to extract
        # from the reference timeline. The current delay tells us the offset.
        # Positive delay means target is EARLY, so reference position is EARLIER in time.
        boundary_s_ref = boundary_s_target - (current_delay_ms / 1000.0)

        # Safeguard: Ensure reference position doesn't go negative
        if boundary_s_ref < 0:
            self.log(
                f"      [Smart Fill] WARNING: Reference position would be negative ({boundary_s_ref:.3f}s), clamping to 0.0s"
            )
            boundary_s_ref = 0.0

        boundary_sample_ref = int(boundary_s_ref * sample_rate)

        self.log(
            f"      [Smart Fill] Target boundary: {boundary_s_target:.3f}s, Current delay: {current_delay_ms:+.0f}ms → Reference position: {boundary_s_ref:.3f}s"
        )

        # Define search window in reference audio around the reference position
        search_window_samples = int(search_window_s * sample_rate)
        search_start = max(0, boundary_sample_ref - search_window_samples)
        search_end = min(
            len(ref_pcm), boundary_sample_ref + search_window_samples + gap_samples
        )

        if search_end - search_start < gap_samples:
            self.log(
                "      [Smart Fill] Insufficient reference audio for content search."
            )
            return None, 0.0, "silence"

        # Try to find best matching content in reference
        # Extract from the REFERENCE timeline position
        if boundary_sample_ref + gap_samples <= len(ref_pcm):
            candidate_content = ref_pcm[
                boundary_sample_ref : boundary_sample_ref + gap_samples
            ]

            # Check if this is actual content (not silence)
            content_std = np.std(candidate_content)
            # For int32 PCM audio, std < 100 indicates silence/near-silence
            if content_std < 100.0:
                self.log(
                    "      [Smart Fill] Reference has silence at position → using silence fill"
                )
                return None, 0.0, "silence"

            # In 'content' mode, always use reference content if available
            if fill_mode == "content":
                self.log(
                    f"      [Smart Fill] Extracting {gap_duration_ms:.0f}ms from reference at {boundary_s_ref:.3f}s (forced mode)"
                )
                return candidate_content, 1.0, "content"

            # In 'auto' mode, correlate to verify it's a good match
            # Look for where this content might appear in the analysis audio
            if len(analysis_pcm) > gap_samples:
                # Normalize candidate for correlation
                candidate_norm = (candidate_content - np.mean(candidate_content)) / (
                    content_std + 1e-9
                )

                # Search in analysis audio near the boundary (on TARGET timeline)
                boundary_sample_target = int(boundary_s_target * sample_rate)
                analysis_search_start = max(
                    0, boundary_sample_target - search_window_samples
                )
                analysis_search_end = min(
                    len(analysis_pcm), boundary_sample_target + search_window_samples
                )
                analysis_search_region = analysis_pcm[
                    analysis_search_start:analysis_search_end
                ]

                if len(analysis_search_region) > gap_samples:
                    analysis_std = np.std(analysis_search_region)
                    # For int32 PCM audio, std > 100 indicates actual audio content
                    if analysis_std > 100.0:
                        analysis_norm = (
                            analysis_search_region - np.mean(analysis_search_region)
                        ) / (analysis_std + 1e-9)

                        # Correlate to find if this content exists in analysis
                        # Suppress numpy warnings about division - we've already checked std above
                        import warnings

                        with warnings.catch_warnings():
                            warnings.filterwarnings(
                                "ignore", "invalid value encountered in divide"
                            )
                            corr = correlate(
                                candidate_norm,
                                analysis_norm,
                                mode="valid",
                                method="fft",
                            )

                        if len(corr) > 0:
                            max_corr = np.max(np.abs(corr))
                            normalized_corr = max_corr / len(candidate_norm)

                            self.log(
                                f"      [Smart Fill] Content correlation: {normalized_corr:.3f} (threshold: {correlation_threshold:.3f})"
                            )

                            if normalized_corr < correlation_threshold:
                                # Low correlation - this content is NOT in analysis, so we should add it
                                self.log(
                                    "      [Smart Fill] Content appears to be missing from analysis → extracting from reference"
                                )
                                return candidate_content, normalized_corr, "content"
                            else:
                                # High correlation means content already exists in analysis
                                self.log(
                                    "      [Smart Fill] Content already exists in analysis → using silence"
                                )
                                return None, normalized_corr, "silence"

            # Default to using content if we can't determine otherwise
            if fill_mode == "auto":
                self.log(
                    f"      [Smart Fill] Using reference content at {boundary_s_ref:.3f}s (auto mode, unable to verify)"
                )
                return candidate_content, 0.5, "content"

        # If we get here, use silence
        return None, 0.0, "silence"

    def _analyze_internal_drift(
        self,
        edl: list[AudioSegment],
        ref_pcm: np.ndarray,
        analysis_pcm: np.ndarray,
        sample_rate: int,
        codec_name: str,
    ) -> list[AudioSegment]:
        self.log(
            f"  [SteppingCorrector] Stage 2.5: Analyzing segments for internal drift (Codec: {codec_name})..."
        )
        final_edl = []

        r_squared_threshold = self.settings.segment_drift_r2_threshold
        slope_threshold = self.settings.segment_drift_slope_threshold
        outlier_sensitivity = self.settings.segment_drift_outlier_sensitivity
        scan_buffer_pct = self.settings.segment_drift_scan_buffer_pct
        pcm_duration_s = len(analysis_pcm) / float(sample_rate)

        for i, current_segment in enumerate(edl):
            segment_start_s = current_segment.start_s
            segment_end_s = edl[i + 1].start_s if i + 1 < len(edl) else pcm_duration_s
            segment_duration_s = segment_end_s - segment_start_s

            # Skip segments under 1 second - too short for reliable audio correlation
            if segment_duration_s < 1.0:
                self.log(
                    f"    - Skipping segment from {segment_start_s:.2f}s to {segment_end_s:.2f}s: too short ({segment_duration_s:.2f}s)"
                )
                final_edl.append(current_segment)
                continue

            # Skip fine-scanning segments under 20 seconds - not worth the computational cost
            # These short segments are handled with the coarse delay estimate
            if segment_duration_s < 20.0:
                final_edl.append(current_segment)
                continue

            self.log(
                f"    - Scanning segment from {segment_start_s:.2f}s to {segment_end_s:.2f}s (Target Timeline)..."
            )

            # Internal drift scan parameters (rarely triggers - most files have stepping OR drift, not both)
            scan_chunk_s = (
                5.0  # Audio chunk size (seconds) for correlation at each scan point
            )
            num_scans = max(
                5, int(segment_duration_s / 20.0)
            )  # Min 5 scans, or ~1 per 20 seconds
            chunk_samples = int(scan_chunk_s * sample_rate)
            locality_samples = int(
                self.settings.segment_search_locality_s * sample_rate
            )

            # Edge buffer to avoid scanning near segment boundaries where stepping transitions occur
            offset = min(
                30.0, segment_duration_s * (scan_buffer_pct / 100.0)
            )  # Max 30s from each edge
            scan_window_start = segment_start_s + offset
            scan_window_end = segment_end_s - offset - scan_chunk_s

            if scan_window_end <= scan_window_start:
                final_edl.append(current_segment)
                continue

            scan_points_s_target = np.linspace(
                scan_window_start, scan_window_end, num=num_scans
            )

            times, delays = [], []
            for t_s_target in scan_points_s_target:
                base_delay_s = current_segment.delay_ms / 1000.0
                t_s_ref = t_s_target - base_delay_s
                start_sample_ref = int(t_s_ref * sample_rate)

                result = self._get_delay_for_chunk(
                    ref_pcm,
                    analysis_pcm,
                    start_sample_ref,
                    chunk_samples,
                    sample_rate,
                    locality_samples,
                )
                if result is not None:
                    delay_ms, _ = result  # Only need rounded for drift analysis
                    times.append(t_s_ref)
                    delays.append(delay_ms)

            if len(times) < 4:
                final_edl.append(current_segment)
                continue

            delays_arr = np.array(delays)
            median = np.median(delays_arr)
            std_dev = np.std(delays_arr)

            filtered_times, filtered_delays = [], []
            if std_dev > 0:
                for t, d in zip(times, delays):
                    if abs(d - median) < outlier_sensitivity * std_dev:
                        filtered_times.append(t)
                        filtered_delays.append(d)
            else:
                filtered_times, filtered_delays = times, delays

            if len(filtered_times) < 4:
                self.log(
                    "      [STABLE] Not enough consistent points after outlier rejection."
                )
                final_edl.append(current_segment)
                continue

            self.log(
                f"      - Kept {len(filtered_times)}/{len(times)} points for drift calculation after outlier rejection."
            )

            times_arr, delays_arr = np.array(filtered_times), np.array(filtered_delays)

            try:
                correlation_matrix = np.corrcoef(times_arr, delays_arr)
                if np.isnan(correlation_matrix).any():
                    r_squared = 0.0
                else:
                    r_squared = correlation_matrix[0, 1] ** 2

                if np.isnan(r_squared):
                    r_squared = 0.0

                slope, _ = np.polyfit(times_arr, delays_arr, 1)
            except (np.linalg.LinAlgError, ValueError):
                r_squared, slope = 0.0, 0.0

            if r_squared > r_squared_threshold and abs(slope) > slope_threshold:
                self.log(
                    f"      [DRIFT DETECTED] Found internal drift of {slope:+.2f} ms/s in segment (R²={r_squared:.2f})."
                )
                current_segment.drift_rate_ms_s = slope
            else:
                self.log(
                    f"      [STABLE] Segment is internally stable (slope={slope:+.2f} ms/s, R²={r_squared:.2f})."
                )

            final_edl.append(current_segment)

        return final_edl

    def _assemble_from_segments_via_ffmpeg(
        self,
        pcm_data: np.ndarray,
        edl: list[AudioSegment],
        channels: int,
        channel_layout: str,
        sample_rate: int,
        out_path: Path,
        log_prefix: str,
        ref_pcm: np.ndarray | None = None,
    ) -> bool:
        self.log(
            f"  [{log_prefix}] Assembling audio from {len(edl)} segment(s) via FFmpeg..."
        )

        assembly_dir = out_path.parent / f"assembly_{out_path.stem}"
        assembly_dir.mkdir(exist_ok=True)

        concat_list_path = assembly_dir / "concat_list.txt"
        segment_files = []
        base_delay_ms = edl[0].delay_ms
        current_base_delay = base_delay_ms

        try:
            pcm_duration_s = len(pcm_data) / float(sample_rate * channels)

            for i, segment in enumerate(edl):
                silence_to_add_ms = segment.delay_ms - current_base_delay
                if abs(silence_to_add_ms) > 10:
                    if silence_to_add_ms > 0:
                        # Try Smart Fill if reference audio is available
                        fill_content = None
                        fill_type = "silence"

                        if ref_pcm is not None:
                            fill_content, corr_score, fill_type = (
                                self._extract_content_from_reference(
                                    ref_pcm=ref_pcm,
                                    analysis_pcm=pcm_data,
                                    boundary_s_target=segment.start_s,
                                    gap_duration_ms=silence_to_add_ms,
                                    sample_rate=sample_rate,
                                    current_delay_ms=current_base_delay,
                                )
                            )

                        if fill_content is not None and fill_type == "content":
                            # Use extracted content from reference
                            self.log(
                                f"    - At {segment.start_s:.3f}s: Inserting {silence_to_add_ms}ms of CONTENT from reference (Smart Fill, correlation={corr_score:.3f})."
                            )
                            content_file = assembly_dir / f"content_{i:03d}.flac"

                            # Convert mono ref_pcm to match target channels if needed
                            if channels == 1:
                                content_to_encode = fill_content
                            else:
                                # Duplicate mono to all channels
                                content_mono = fill_content
                                content_interleaved = np.zeros(
                                    len(content_mono) * channels, dtype=np.int32
                                )
                                for ch in range(channels):
                                    content_interleaved[ch::channels] = content_mono
                                content_to_encode = content_interleaved

                            encode_cmd = [
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
                                str(content_file),
                            ]
                            if (
                                self.runner.run(
                                    encode_cmd,
                                    self.tool_paths,
                                    is_binary=True,
                                    input_data=content_to_encode.tobytes(),
                                )
                                is not None
                            ):
                                segment_files.append(f"file '{content_file.name}'")
                        else:
                            # Use silence (traditional approach)
                            self.log(
                                f"    - At {segment.start_s:.3f}s: Inserting {silence_to_add_ms}ms of silence."
                            )
                            silence_duration_s = silence_to_add_ms / 1000.0
                            silence_file = assembly_dir / f"silence_{i:03d}.flac"

                            silence_samples = (
                                int(silence_duration_s * sample_rate) * channels
                            )
                            silence_pcm = np.zeros(silence_samples, dtype=np.int32)

                            encode_cmd = [
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
                                str(silence_file),
                            ]
                            if (
                                self.runner.run(
                                    encode_cmd,
                                    self.tool_paths,
                                    is_binary=True,
                                    input_data=silence_pcm.tobytes(),
                                )
                                is not None
                            ):
                                segment_files.append(f"file '{silence_file.name}'")
                    else:
                        self.log(
                            f"    - At {segment.start_s:.3f}s: Removing {-silence_to_add_ms}ms of audio."
                        )

                current_base_delay = segment.delay_ms

                segment_start_s_on_target_timeline = segment.start_s
                segment_end_s_on_target_timeline = (
                    edl[i + 1].start_s if i + 1 < len(edl) else pcm_duration_s
                )

                if silence_to_add_ms < 0:
                    segment_start_s_on_target_timeline += (
                        abs(silence_to_add_ms) / 1000.0
                    )

                if (
                    segment_end_s_on_target_timeline
                    <= segment_start_s_on_target_timeline
                ):
                    continue

                start_sample = (
                    int(segment_start_s_on_target_timeline * sample_rate) * channels
                )
                end_sample = (
                    int(segment_end_s_on_target_timeline * sample_rate) * channels
                )

                end_sample = min(end_sample, len(pcm_data))

                chunk_to_process = pcm_data[start_sample:end_sample]

                if chunk_to_process.size == 0:
                    continue

                segment_file = assembly_dir / f"segment_{i:03d}.flac"

                encode_cmd = [
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
                    str(segment_file),
                ]
                if (
                    self.runner.run(
                        encode_cmd,
                        self.tool_paths,
                        is_binary=True,
                        input_data=chunk_to_process.tobytes(),
                    )
                    is None
                ):
                    raise RuntimeError(f"Failed to encode segment {i}")

                if abs(segment.drift_rate_ms_s) > 0.5:
                    self.log(
                        f"    - Applying drift correction ({segment.drift_rate_ms_s:+.2f} ms/s) to segment {i}."
                    )
                    tempo_ratio = 1000.0 / (1000.0 + segment.drift_rate_ms_s)
                    corrected_file = assembly_dir / f"segment_{i:03d}_corrected.flac"

                    resample_engine = self.settings.segment_resample_engine
                    filter_chain = ""

                    if resample_engine == "rubberband":
                        self.log(
                            "    - Using 'rubberband' engine for high-quality resampling."
                        )
                        rb_opts = [f"tempo={tempo_ratio}"]

                        if not self.settings.segment_rb_pitch_correct:
                            rb_opts.append(f"pitch={tempo_ratio}")

                        rb_opts.append(
                            f"transients={self.settings.segment_rb_transients}"
                        )

                        if self.settings.segment_rb_smoother:
                            rb_opts.append("smoother=on")

                        if self.settings.segment_rb_pitchq:
                            rb_opts.append("pitchq=on")

                        filter_chain = "rubberband=" + ":".join(rb_opts)

                    elif resample_engine == "atempo":
                        self.log("    - Using 'atempo' engine for fast resampling.")
                        filter_chain = f"atempo={tempo_ratio}"

                    else:  # Default to aresample
                        self.log(
                            "    - Using 'aresample' engine for high-quality resampling."
                        )
                        new_sample_rate = sample_rate * tempo_ratio
                        filter_chain = (
                            f"asetrate={new_sample_rate},aresample={sample_rate}"
                        )

                    resample_cmd = [
                        "ffmpeg",
                        "-y",
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        str(segment_file),
                        "-af",
                        filter_chain,
                        "-map_metadata",
                        "-1",
                        "-map_metadata:s:a",
                        "-1",
                        "-fflags",
                        "+bitexact",
                        str(corrected_file),
                    ]

                    if self.runner.run(resample_cmd, self.tool_paths) is None:
                        error_msg = f"Resampling with '{resample_engine}' failed for segment {i}."
                        if resample_engine == "rubberband":
                            error_msg += (
                                " (Ensure your FFmpeg build includes 'librubberband')."
                            )
                        raise RuntimeError(error_msg)

                    segment_file = corrected_file

                segment_files.append(f"file '{segment_file.name}'")

            if not segment_files:
                raise RuntimeError("No segments were generated for assembly.")

            concat_list_path.write_text("\n".join(segment_files), encoding="utf-8")

            final_assembly_cmd = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
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
            if self.runner.run(final_assembly_cmd, self.tool_paths) is None:
                raise RuntimeError("Final FFmpeg concat assembly failed.")

            return True

        except Exception as e:
            self.log(f"    [ERROR] FFmpeg assembly failed: {e}")
            return False
        finally:
            if assembly_dir.exists():
                shutil.rmtree(assembly_dir, ignore_errors=True)

    def _filter_coarse_map_by_clusters(
        self,
        coarse_map: list[tuple[float, int, float]],
        diagnosis_details: dict,
        sample_rate: int,
    ) -> list[tuple[float, int, float]]:
        """
        Filters coarse_map to remove entries that fall within invalid clusters.
        Applies fallback strategy for filtered regions.

        Returns filtered coarse_map.
        """
        correction_mode = diagnosis_details.get("correction_mode", "full")

        # If not in filtered mode, return original map
        if correction_mode != "filtered":
            return coarse_map

        diagnosis_details.get("valid_clusters", {})
        invalid_clusters = diagnosis_details.get("invalid_clusters", {})
        validation_results = diagnosis_details.get("validation_results", {})
        fallback_mode = diagnosis_details.get("fallback_mode", "nearest")

        if not invalid_clusters:
            # No filtering needed
            return coarse_map

        self.log(
            f"  [Filtered Stepping] Filtering coarse map: {len(invalid_clusters)} invalid cluster(s) detected"
        )
        self.log(f"  [Filtered Stepping] Fallback mode: {fallback_mode}")

        # Build a list of time ranges for invalid clusters
        invalid_time_ranges = []
        for label, members in invalid_clusters.items():
            if label in validation_results:
                time_range = validation_results[label].time_range
                invalid_time_ranges.append(time_range)
                self.log(
                    f"    - Invalid cluster {label + 1}: {time_range[0]:.1f}s - {time_range[1]:.1f}s will be filtered"
                )

        # Filter coarse_map entries
        filtered_map = []
        skipped_count = 0

        for entry in coarse_map:
            timestamp_s = entry[0]
            # Check if this timestamp falls within any invalid cluster
            in_invalid_cluster = any(
                start <= timestamp_s <= end for start, end in invalid_time_ranges
            )

            if not in_invalid_cluster:
                filtered_map.append(
                    entry
                )  # Keep full tuple (timestamp, delay_ms, delay_raw)
            else:
                skipped_count += 1

        self.log(
            f"  [Filtered Stepping] Filtered {skipped_count} coarse scan points from invalid clusters"
        )
        self.log(
            f"  [Filtered Stepping] Retained {len(filtered_map)} coarse scan points from valid clusters"
        )

        # Apply fallback strategy if needed
        if fallback_mode == "nearest" and skipped_count > 0:
            self.log(
                "  [Filtered Stepping] Note: Boundaries will only be detected between valid clusters"
            )
        elif fallback_mode == "skip":
            self.log(
                "  [Filtered Stepping] Skipped regions will maintain original timing (no correction)"
            )

        return filtered_map

    def _qa_check(
        self,
        corrected_path: str,
        ref_file_path: str,
        base_delay: int,
        diagnosis_details: dict | None = None,
    ) -> bool:
        self.log(
            "  [SteppingCorrector] Performing rigorous QA check on corrected audio map..."
        )

        # Check if we're using skip mode with filtered clusters
        skip_mode_active = False
        if diagnosis_details:
            correction_mode = diagnosis_details.get("correction_mode", "full")
            fallback_mode = diagnosis_details.get("fallback_mode", "nearest")
            invalid_clusters = diagnosis_details.get("invalid_clusters", {})

            if (
                correction_mode == "filtered"
                and fallback_mode == "skip"
                and invalid_clusters
            ):
                skip_mode_active = True
                self.log(
                    f"  [QA] Note: 'skip' fallback mode is active with {len(invalid_clusters)} filtered cluster(s)."
                )
                self.log(
                    "  [QA] Filtered regions retain original timing, so delay stability check will be relaxed."
                )

        # Create QA settings with overrides using dataclasses.replace()
        qa_threshold = self.settings.segmented_qa_threshold
        qa_scan_chunks = self.settings.segment_qa_chunk_count
        qa_min_chunks = self.settings.segment_qa_min_accepted_chunks

        # Build QA settings with overrides for QA-specific scan parameters
        qa_settings = replace(
            self.settings,
            scan_chunk_count=qa_scan_chunks,
            min_accepted_chunks=qa_min_chunks,
            min_match_pct=qa_threshold,
        )
        self.log(
            f"  [QA] Using minimum match confidence of {qa_threshold:.1f}% within main scan window."
        )

        try:
            # Use analysis_lang_source1 to select correct Source 1 track for QA comparison
            ref_lang = self.settings.analysis_lang_source1
            results = run_audio_correlation(
                ref_file=ref_file_path,
                target_file=corrected_path,
                settings=qa_settings,
                runner=self.runner,
                tool_paths=self.tool_paths,
                ref_lang=ref_lang,
                target_lang=None,
                role_tag="QA",
            )
            accepted = [r for r in results if r.accepted]

            min_accepted = qa_min_chunks
            if len(accepted) < min_accepted:
                self.log(
                    f"  [QA] FAILED: Not enough confident chunks ({len(accepted)}/{min_accepted})."
                )
                return False

            delays = [r.delay_ms for r in accepted]
            median_delay = np.median(delays)

            # For skip mode, use a more lenient median check since we expect different delays
            median_tolerance = 100 if skip_mode_active else 20

            if abs(median_delay - base_delay) > median_tolerance:
                self.log(
                    f"  [QA] FAILED: Median delay ({median_delay:.1f}ms) does not match base delay ({base_delay}ms)."
                )
                return False

            # For skip mode, relax or skip the std dev check
            std_dev = np.std(delays)
            if skip_mode_active:
                # Very lenient std dev check for skip mode (only fail if extremely unstable)
                if std_dev > 500:
                    self.log(
                        f"  [QA] FAILED: Delay is extremely unstable (Std Dev = {std_dev:.1f}ms)."
                    )
                    return False
                else:
                    self.log(
                        f"  [QA] Delay std dev = {std_dev:.1f}ms (acceptable for 'skip' mode with filtered regions)."
                    )
            # Normal strict std dev check
            elif std_dev > 15:
                self.log(
                    f"  [QA] FAILED: Delay is unstable (Std Dev = {std_dev:.1f}ms)."
                )
                return False

            self.log("  [QA] PASSED: Timing map is verified and correct.")
            return True
        except Exception as e:
            self.log(f"  [QA] FAILED with exception: {e}")
            return False

    def run(
        self,
        ref_file_path: str,
        analysis_audio_path: str,
        base_delay_ms: int,
        diagnosis_details: dict | None = None,
    ) -> CorrectionResult:
        ref_pcm = None
        analysis_pcm = None

        try:
            # Use analysis_lang_source1 from settings to select the right Source 1 track
            # Falls back to first track if no language set or no match found
            ref_lang = self.settings.analysis_lang_source1
            ref_index, _ = get_audio_stream_info(
                ref_file_path, ref_lang, self.runner, self.tool_paths
            )
            analysis_index, _ = get_audio_stream_info(
                analysis_audio_path, None, self.runner, self.tool_paths
            )
            if ref_index is None or analysis_index is None:
                return CorrectionResult(
                    CorrectionVerdict.FAILED,
                    {"error": "Could not find audio streams for analysis."},
                )
            _, _, sample_rate = _get_audio_properties(
                analysis_audio_path, analysis_index, self.runner, self.tool_paths
            )

            analysis_codec = self._get_codec_id(analysis_audio_path)

            ref_pcm = self._decode_to_memory(ref_file_path, ref_index, sample_rate)
            analysis_pcm = self._decode_to_memory(
                analysis_audio_path, analysis_index, sample_rate
            )
            if ref_pcm is None or analysis_pcm is None:
                return CorrectionResult(
                    CorrectionVerdict.FAILED,
                    {"error": "Failed to decode one or more audio tracks."},
                )

            coarse_map = self._perform_coarse_scan(ref_pcm, analysis_pcm, sample_rate)
            if not coarse_map:
                return CorrectionResult(
                    CorrectionVerdict.FAILED,
                    {"error": "Coarse scan did not find any reliable sync points."},
                )

            # Apply cluster filtering if diagnosis details are provided
            if diagnosis_details:
                coarse_map = self._filter_coarse_map_by_clusters(
                    coarse_map, diagnosis_details, sample_rate
                )
                if not coarse_map:
                    return CorrectionResult(
                        CorrectionVerdict.FAILED,
                        {
                            "error": "After filtering invalid clusters, no reliable sync points remain."
                        },
                    )

            edl: list[AudioSegment] = []
            anchor_delay_ms = coarse_map[0][1]
            anchor_delay_raw = coarse_map[0][2]
            edl.append(
                AudioSegment(
                    start_s=0.0,
                    end_s=0.0,
                    delay_ms=anchor_delay_ms,
                    delay_raw=anchor_delay_raw,
                )
            )

            triage_std_dev_ms = self.settings.segment_triage_std_dev_ms

            for i in range(len(coarse_map) - 1):
                zone_start_s, delay_before_ms, _delay_before_raw = coarse_map[i]
                zone_end_s, delay_after_ms, delay_after_raw = coarse_map[i + 1]
                if abs(delay_before_ms - delay_after_ms) < triage_std_dev_ms:
                    continue

                boundary_s_ref = self._find_boundary_in_zone(
                    ref_pcm,
                    analysis_pcm,
                    sample_rate,
                    zone_start_s,
                    zone_end_s,
                    delay_before_ms,
                    delay_after_ms,
                    ref_file_path,
                    analysis_audio_path,
                )
                boundary_s_target = boundary_s_ref + (delay_before_ms / 1000.0)
                edl.append(
                    AudioSegment(
                        start_s=boundary_s_target,
                        end_s=boundary_s_target,
                        delay_ms=delay_after_ms,
                        delay_raw=delay_after_raw,
                    )
                )

            edl = sorted(set(edl), key=lambda x: x.start_s)

            if len(edl) <= 1:
                refined_delay = edl[0].delay_ms if edl else base_delay_ms
                self.log(
                    "  [SteppingCorrector] No stepping detected. Audio delay is uniform throughout."
                )
                self.log(
                    f"  [SteppingCorrector] Refined delay measurement: {refined_delay}ms"
                )
                if abs(refined_delay - base_delay_ms) > 5:
                    self.log(
                        f"  [SteppingCorrector] Refined delay differs from initial estimate by {abs(refined_delay - base_delay_ms)}ms"
                    )
                    self.log(
                        f"  [SteppingCorrector] Recommending use of refined value: {refined_delay}ms"
                    )
                return CorrectionResult(
                    CorrectionVerdict.UNIFORM, {"delay": refined_delay}
                )

            edl = self._analyze_internal_drift(
                edl, ref_pcm, analysis_pcm, sample_rate, analysis_codec
            )

            self.log(
                "  [SteppingCorrector] Final Edit Decision List (EDL) for assembly created:"
            )
            for i, seg in enumerate(edl):
                self.log(
                    f"    - Action {i + 1}: At target time {seg.start_s:.3f}s, delay = {seg.delay_ms}ms (raw: {seg.delay_raw:.3f}ms), drift = {seg.drift_rate_ms_s:+.2f} ms/s"
                )

            # --- QA Check ---
            self.log("  [SteppingCorrector] Assembling temporary QA track...")
            qa_track_path = Path(analysis_audio_path).parent / "qa_track.flac"
            if not self._assemble_from_segments_via_ffmpeg(
                analysis_pcm,
                edl,
                1,
                "mono",
                sample_rate,
                qa_track_path,
                log_prefix="QA",
                ref_pcm=ref_pcm,
            ):
                return CorrectionResult(
                    CorrectionVerdict.FAILED,
                    {"error": "Failed during QA track assembly."},
                )

            if not self._qa_check(
                str(qa_track_path), ref_file_path, edl[0].delay_ms, diagnosis_details
            ):
                return CorrectionResult(
                    CorrectionVerdict.FAILED,
                    {"error": "Corrected track failed QA check."},
                )

            # If QA passes, the EDL is good. Return it with audit metadata.
            return CorrectionResult(
                CorrectionVerdict.STEPPED,
                {"edl": edl, "audit_metadata": self.audit_metadata},
            )

        except Exception as e:
            self.log(f"[FATAL] SteppingCorrector failed with exception: {e}")
            import traceback

            self.log(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return CorrectionResult(CorrectionVerdict.FAILED, {"error": str(e)})
        finally:
            if ref_pcm is not None:
                del ref_pcm
            if analysis_pcm is not None:
                del analysis_pcm
            gc.collect()

    def apply_plan_to_file(
        self,
        target_audio_path: str,
        edl: list[AudioSegment],
        temp_dir: Path,
        ref_file_path: str | None = None,
    ) -> Path | None:
        """Applies a pre-generated EDL to a given audio file."""
        target_pcm = None
        ref_pcm = None
        try:
            target_index, _ = get_audio_stream_info(
                target_audio_path, None, self.runner, self.tool_paths
            )
            if target_index is None:
                self.log(f"[ERROR] Could not find audio stream in {target_audio_path}")
                return None

            target_channels, target_layout, sample_rate = _get_audio_properties(
                target_audio_path, target_index, self.runner, self.tool_paths
            )

            # Decode reference audio for Smart Fill if provided
            if ref_file_path:
                self.log(
                    "  [SteppingCorrector] Decoding reference audio for Smart Fill capability..."
                )
                ref_lang = self.settings.analysis_lang_source1
                ref_index, _ = get_audio_stream_info(
                    ref_file_path, ref_lang, self.runner, self.tool_paths
                )
                if ref_index is not None:
                    ref_pcm = self._decode_to_memory(
                        ref_file_path, ref_index, sample_rate
                    )
                    if ref_pcm is None:
                        self.log(
                            "  [WARNING] Failed to decode reference audio, Smart Fill will be disabled"
                        )

            self.log(
                f"  [SteppingCorrector] Applying correction plan to '{Path(target_audio_path).name}'..."
            )
            self.log(f"    - Decoding final target audio track ({target_layout})...")
            target_pcm = self._decode_to_memory(
                target_audio_path, target_index, sample_rate, target_channels
            )
            if target_pcm is None:
                return None

            corrected_path = temp_dir / f"corrected_{Path(target_audio_path).stem}.flac"

            if not self._assemble_from_segments_via_ffmpeg(
                target_pcm,
                edl,
                target_channels,
                target_layout,
                sample_rate,
                corrected_path,
                log_prefix="Final",
                ref_pcm=ref_pcm,
            ):
                return None

            self.log(
                f"[SUCCESS] Stepping correction applied successfully for '{Path(target_audio_path).name}'"
            )
            return corrected_path

        except Exception as e:
            self.log(f"[FATAL] Assembly failed for {target_audio_path}: {e}")
            return None
        finally:
            if target_pcm is not None:
                del target_pcm
            if ref_pcm is not None:
                del ref_pcm
            gc.collect()


def run_stepping_correction(ctx: Context, runner: CommandRunner) -> Context:
    extracted_audio_map = {
        f"{item.track.source}_{item.track.id}": item
        for item in ctx.extracted_items
        if item.track.type == "audio"
    }

    corrector = SteppingCorrector(runner, ctx.tool_paths, ctx.settings)
    ref_file_path = ctx.sources.get("Source 1")

    for analysis_track_key, flag_info in ctx.segment_flags.items():
        source_key = analysis_track_key.split("_")[0]
        base_delay_ms = flag_info["base_delay"]
        subs_only = flag_info.get("subs_only", False)

        target_items = [
            item
            for item in ctx.extracted_items
            if item.track.source == source_key
            and item.track.type == "audio"
            and not item.is_preserved
        ]

        if not target_items and not subs_only:
            runner._log_message(
                f"[SteppingCorrection] Skipping {source_key}: No audio tracks found in layout to correct."
            )
            continue

        if subs_only:
            runner._log_message(
                f"[SteppingCorrection] Running full analysis for {source_key} (subs-only mode - no audio to apply)."
            )

        analysis_item = extracted_audio_map.get(analysis_track_key)
        if not analysis_item:
            runner._log_message(
                f"[SteppingCorrection] Analysis track {analysis_track_key} not in layout. Extracting internally..."
            )
            source_container_path = ctx.sources.get(source_key)
            track_id = int(analysis_track_key.split("_")[1])
            try:
                internal_extract = extract_tracks(
                    source_container_path,
                    ctx.temp_dir,
                    runner,
                    ctx.tool_paths,
                    role=f"{source_key}_internal",
                    specific_tracks=[track_id],
                )
                if not internal_extract:
                    raise RuntimeError("Internal extraction failed.")
                analysis_track_path = internal_extract[0]["path"]
            except Exception as e:
                runner._log_message(
                    f"[ERROR] Failed to internally extract analysis track {analysis_track_key}: {e}"
                )
                continue
        else:
            analysis_track_path = str(analysis_item.extracted_path)

        # Run analysis once to get the correction plan (EDL)
        # Pass diagnosis details for filtered stepping support
        diagnosis_details = {
            "valid_clusters": flag_info.get("valid_clusters", {}),
            "invalid_clusters": flag_info.get("invalid_clusters", {}),
            "validation_results": flag_info.get("validation_results", {}),
            "correction_mode": flag_info.get("correction_mode", "full"),
            "fallback_mode": flag_info.get("fallback_mode", "nearest"),
        }

        result: CorrectionResult = corrector.run(
            ref_file_path=ref_file_path,
            analysis_audio_path=analysis_track_path,
            base_delay_ms=base_delay_ms,
            diagnosis_details=diagnosis_details
            if flag_info.get("correction_mode")
            else None,
        )

        if result.verdict == CorrectionVerdict.UNIFORM:
            new_delay = result.data["delay"]
            runner._log_message(
                f"[SteppingCorrection] No stepping found. Refined uniform delay is {new_delay} ms."
            )
            runner._log_message(
                "[SteppingCorrection] The globally-shifted delay from the main analysis will be used."
            )

        elif result.verdict == CorrectionVerdict.STEPPED:
            edl = result.data["edl"]
            audit_metadata = result.data.get("audit_metadata", [])

            # Store EDL in context for subtitle adjustment
            ctx.stepping_edls[source_key] = edl

            # Store audit metadata in segment_flags for final audit
            if analysis_track_key in ctx.segment_flags:
                ctx.segment_flags[analysis_track_key]["audit_metadata"] = audit_metadata

            if subs_only:
                # Subs-only mode: EDL stored for subtitle use, no audio to apply
                runner._log_message(
                    f"[SteppingCorrection] Analysis successful (subs-only). Verified EDL with {len(edl)} segment(s) stored for subtitle adjustment:"
                )
                for i, seg in enumerate(edl):
                    runner._log_message(
                        f"  - Segment {i + 1}: @{seg.start_s:.1f}s → delay={seg.delay_ms:+d}ms (raw: {seg.delay_raw:.3f}ms)"
                    )
            else:
                # Normal mode: Apply correction to audio tracks
                runner._log_message(
                    f"[SteppingCorrection] Analysis successful. Applying correction plan to {len(target_items)} audio track(s) from {source_key}."
                )

            for target_item in target_items:
                corrected_path = corrector.apply_plan_to_file(
                    str(target_item.extracted_path),
                    edl,
                    ctx.temp_dir,
                    ref_file_path=ref_file_path,
                )

                if corrected_path:
                    # Preserve the original track
                    preserved_item = copy.deepcopy(target_item)
                    preserved_item.is_preserved = True
                    preserved_item.is_default = False
                    original_props = preserved_item.track.props

                    # Build preserved track name from settings
                    preserved_label = corrector.settings.stepping_preserved_track_label
                    if preserved_label:
                        preserved_name = (
                            f"{original_props.name} ({preserved_label})"
                            if original_props.name
                            else preserved_label
                        )
                    else:
                        preserved_name = (
                            original_props.name if original_props.name else None
                        )

                    preserved_item.track = Track(
                        source=preserved_item.track.source,
                        id=preserved_item.track.id,
                        type=preserved_item.track.type,
                        props=StreamProps(
                            codec_id=original_props.codec_id,
                            lang=original_props.lang,
                            name=preserved_name,
                        ),
                    )

                    # Update the main track to point to corrected FLAC
                    target_item.extracted_path = corrected_path
                    target_item.is_corrected = True
                    target_item.container_delay_ms = (
                        0  # FIXED: New FLAC has no container delay
                    )

                    # Build corrected track name from settings
                    corrected_label = corrector.settings.stepping_corrected_track_label
                    if corrected_label:
                        corrected_name = (
                            f"{original_props.name} ({corrected_label})"
                            if original_props.name
                            else corrected_label
                        )
                    else:
                        corrected_name = (
                            original_props.name if original_props.name else None
                        )

                    target_item.track = Track(
                        source=target_item.track.source,
                        id=target_item.track.id,
                        type=target_item.track.type,
                        props=StreamProps(
                            codec_id="FLAC",
                            lang=original_props.lang,
                            name=corrected_name,
                        ),
                    )
                    target_item.apply_track_name = True
                    ctx.extracted_items.append(preserved_item)
                else:
                    runner._log_message(
                        f"[ERROR] Failed to apply correction plan to {target_item.extracted_path.name}. Keeping original."
                    )

        elif result.verdict == CorrectionVerdict.FAILED:
            error_message = result.data.get("error", "Unknown error")
            raise RuntimeError(
                f"Stepping correction for {source_key} failed: {error_message}"
            )

    return ctx
