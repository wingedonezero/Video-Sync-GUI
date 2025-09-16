# vsg_core/analysis/segmentation/matching.py
# -*- coding: utf-8 -*-
"""
Phase III: Segment matching and remapping logic.
"""
from dataclasses import dataclass
from typing import List, Optional
import numpy as np

# This import is necessary for type hinting in the class
from .fingerprint import AudioFingerprinter


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

    def __init__(self, fingerprinter: AudioFingerprinter, log_func=None):
        self.fingerprinter = fingerprinter
        self.log = log_func or print
        self.min_confidence = 0.5

    def classify_segment(self, audio_chunk: np.ndarray, duration_s: float) -> str:
        """Classify segment type based on audio characteristics."""
        # Simple RMS energy for silence detection
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float64)**2))
        max_val = np.abs(audio_chunk).max() if len(audio_chunk) > 0 else 1
        silence_threshold = max_val * 0.01
        if rms < silence_threshold:
            return "silence"

        # Simple duration check for common commercial lengths
        commercial_durations = [15, 30, 60]
        for com_dur in commercial_durations:
            if abs(duration_s - com_dur) < 2.0:
                return "commercial"

        return "content"

    def match_segments(self, ref_segments: List[Segment], target_segments: List[Segment]) -> List[SegmentMatch]:
        """
        Match reference segments to target segments using fingerprints.
        This version uses a confidence score and ensures one-to-one matching.
        """
        matches = []
        used_target_indices = set()

        for ref_seg in ref_segments:
            best_match_segment = None
            best_confidence = 0.0
            best_match_idx = -1

            if not ref_seg.fingerprint or not self.fingerprinter:
                continue

            for i, target_seg in enumerate(target_segments):
                if i in used_target_indices or not target_seg.fingerprint:
                    continue

                # Use the robust similarity comparison
                similarity = self.fingerprinter.compare_fingerprints(
                    ref_seg.fingerprint, target_seg.fingerprint
                )

                if similarity > best_confidence:
                    best_confidence = similarity
                    best_match_segment = target_seg
                    best_match_idx = i

            # If we found a match that exceeds our minimum confidence, accept it.
            if best_match_idx != -1 and best_confidence >= self.min_confidence:
                used_target_indices.add(best_match_idx)
                action = "use"
            else:
                # If no confident match was found, decide what to do.
                best_match_segment = None # Ensure we don't carry over a low-confidence match
                if ref_seg.segment_type == "commercial":
                    action = "skip" # Commercial in reference that isn't in target
                else:
                    action = "insert_silence" # Content in reference that is missing from target

            matches.append(SegmentMatch(
                ref_segment=ref_seg,
                target_segment=best_match_segment,
                match_confidence=best_confidence,
                action=action
            ))

        return matches

    def build_edl(self, matches: List[SegmentMatch], base_delay_ms: int) -> List[Segment]:
        """Build final Edit Decision List from the intelligent matches."""
        edl = []
        for match in matches:
            if match.action == "use" and match.target_segment:
                # This is a confirmed match. Add the target segment to the playlist.
                segment = match.target_segment
                edl.append(segment)
                self.log(f"    - EDL: Using segment {segment.start_s:.2f}s - {segment.end_s:.2f}s (Confidence: {match.match_confidence:.2f})")

            elif match.action == "insert_silence":
                # The reference had content that the target was missing.
                # We need to create a "silence" segment to fill the gap.
                ref = match.ref_segment
                duration = ref.end_s - ref.start_s
                silence_segment = Segment(start_s=0, end_s=duration, delay_ms=0, segment_type="silence")
                edl.append(silence_segment)
                self.log(f"    - EDL: Inserting {duration:.2f}s of silence for missing reference content.")

            elif match.action == "skip":
                # The reference had a segment (like a commercial) that we want to discard.
                # We simply don't add it to the EDL.
                ref = match.ref_segment
                self.log(f"    - EDL: Skipping reference segment {ref.start_s:.2f}s - {ref.end_s:.2f}s (Type: {ref.segment_type})")

        if edl:
            # Set the base delay for the very first piece of audio content.
            edl[0].delay_ms = base_delay_ms
            self.log(f"  [Matching] Built complex EDL with {len(edl)} actions.")

        return edl
