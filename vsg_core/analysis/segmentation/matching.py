# vsg_core/analysis/segmentation/matching.py
# -*- coding: utf-8 -*-
"""
Phase III: Segment matching and remapping logic.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np  # ADD THIS IMPORT

@dataclass
class Segment:
    """Audio segment with metadata."""
    start_s: float
    end_s: float
    delay_ms: int
    fingerprint: Optional[str] = None
    segment_type: str = "content"  # "content", "commercial", "silence"
    confidence: float = 1.0

@dataclass
class SegmentMatch:
    """Match between reference and target segments."""
    ref_segment: Segment
    target_segment: Optional[Segment]
    match_confidence: float
    action: str  # "use", "skip", "insert_silence"

class SegmentMatcher:
    """Match and remap audio segments."""

    def __init__(self, fingerprinter=None, log_func=None):
        self.fingerprinter = fingerprinter
        self.log = log_func or print
        self.min_confidence = 0.5

    def classify_segment(self, audio_chunk: np.ndarray, duration_s: float,
                        sample_rate: int) -> str:
        """Classify segment type based on audio characteristics."""
        # Calculate RMS energy
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float64)**2))

        # Silence detection
        max_val = np.abs(audio_chunk).max() if len(audio_chunk) > 0 else 1
        silence_threshold = max_val * 0.01

        if rms < silence_threshold:
            return "silence"

        # Commercial detection by duration
        commercial_durations = [15, 30, 60]
        for com_dur in commercial_durations:
            if abs(duration_s - com_dur) < 2.0:
                return "commercial"

        return "content"

    def match_segments(self, ref_segments: List[Segment],
                      target_segments: List[Segment]) -> List[SegmentMatch]:
        """
        Match reference segments to target segments.
        Uses fingerprints if available, falls back to temporal matching.
        """
        matches = []
        used_targets = set()

        for ref_seg in ref_segments:
            best_match = None
            best_confidence = 0.0
            best_match_idx = -1

            # Try fingerprint matching first
            if ref_seg.fingerprint and self.fingerprinter:
                for idx, target_seg in enumerate(target_segments):
                    if idx in used_targets or not target_seg.fingerprint:
                        continue

                    # Compare fingerprints
                    similarity = self.fingerprinter.compare_fingerprints(
                        ref_seg.fingerprint, target_seg.fingerprint
                    )

                    if similarity > best_confidence:
                        best_match = target_seg
                        best_confidence = similarity
                        best_match_idx = idx

                        if similarity >= 1.0:  # Perfect match
                            break

            # Fallback to temporal matching
            if best_confidence < 0.8:
                ref_mid = (ref_seg.start_s + ref_seg.end_s) / 2
                ref_duration = ref_seg.end_s - ref_seg.start_s

                for idx, target_seg in enumerate(target_segments):
                    if idx in used_targets:
                        continue

                    target_mid = (target_seg.start_s + target_seg.end_s) / 2
                    target_duration = target_seg.end_s - target_seg.start_s

                    # Calculate confidence based on position and duration
                    time_diff = abs(ref_mid - target_mid)
                    duration_diff = abs(ref_duration - target_duration)

                    if time_diff < 10.0:  # Within 10 seconds
                        time_confidence = 1.0 - (time_diff / 10.0)
                        duration_confidence = 1.0 - min(duration_diff / ref_duration, 1.0)
                        confidence = (time_confidence * 0.7 + duration_confidence * 0.3)

                        if confidence > best_confidence:
                            best_match = target_seg
                            best_confidence = confidence
                            best_match_idx = idx

            # Mark target as used
            if best_match_idx >= 0 and best_confidence > 0.3:
                used_targets.add(best_match_idx)

            # Determine action
            if best_match and best_confidence > self.min_confidence:
                action = "use"
            elif ref_seg.segment_type == "silence":
                action = "insert_silence"
            elif ref_seg.segment_type == "commercial":
                action = "skip"
            else:
                action = "skip"
                self.log(f"    - No match for segment {ref_seg.start_s:.2f}s - {ref_seg.end_s:.2f}s")

            matches.append(SegmentMatch(
                ref_segment=ref_seg,
                target_segment=best_match,
                match_confidence=best_confidence,
                action=action
            ))

        return matches

    def build_edl(self, matches: List[SegmentMatch], base_delay_ms: int) -> List[Segment]:
        """Build final Edit Decision List from matches."""
        edl = []

        for match in matches:
            if match.action == "use" and match.target_segment:
                # Add to EDL
                segment = match.target_segment
                edl.append(segment)

                self.log(f"    - Using segment: {segment.start_s:.2f}s - {segment.end_s:.2f}s "
                        f"@ {segment.delay_ms}ms (confidence: {match.match_confidence:.2f})")

            elif match.action == "skip":
                ref = match.ref_segment
                self.log(f"    - Skipping: {ref.start_s:.2f}s - {ref.end_s:.2f}s "
                        f"(type: {ref.segment_type})")

        # Set base delay for first segment
        if edl:
            edl[0].delay_ms = base_delay_ms
            self.log(f"  [Matching] Built EDL with {len(edl)} segments")

        return edl
