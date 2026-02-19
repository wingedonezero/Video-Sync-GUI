# vsg_core/correction/stepping/__init__.py
"""
Stepping correction package.

Decomposes stepped delay correction into focused modules:
- types: Dataclasses (AudioSegment, SplicePoint, SilenceZone, etc.)
- timeline: Reference ↔ Source 2 timeline conversion
- data_io: Dense analysis data serialization (JSON in temp folder)
- edl_builder: Build transition zones from dense cluster data
- boundary_refiner: Silence detection (RMS + VAD), video snap
- audio_assembly: FFmpeg segment extraction, drift correction, concat
- qa_check: Post-correction quality verification
- run: Entry point (run_stepping_correction, apply_plan_to_file)
"""

from __future__ import annotations

from .run import (
    apply_plan_to_file,
    run_stepping_correction,
)
from .types import AudioSegment

__all__ = [
    "AudioSegment",
    "apply_plan_to_file",
    "run_stepping_correction",
]
