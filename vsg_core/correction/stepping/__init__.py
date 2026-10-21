# vsg_core/correction/stepping/__init__.py
"""
Stepping correction package.

Decomposes stepped delay correction into focused modules:
- types: Dataclasses (AudioSegment, SplicePoint, SilenceZone, etc.)
- timeline: Reference ↔ Source 2 timeline conversion
- data_io: Dense analysis data serialization (JSON in temp folder)
- edl_builder: Build transition zones from dense cluster data
- boundary_refiner: Silence detection (RMS + VAD), video snap
- edit_plan: EDL -> sample-exact edits (shared by QA and the audio finisher)
- audio_assembly: Track probe/decode for analysis, mono QA track
- qa_check: Post-correction quality verification
- run: Entry point (run_stepping_correction, swap_in_corrected_track)
"""

from __future__ import annotations

from .run import (
    run_stepping_correction,
    swap_in_corrected_track,
)
from .types import AudioSegment

__all__ = [
    "AudioSegment",
    "run_stepping_correction",
    "swap_in_corrected_track",
]
