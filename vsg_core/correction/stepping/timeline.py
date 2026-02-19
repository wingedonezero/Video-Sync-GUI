# vsg_core/correction/stepping/timeline.py
"""
Timeline conversion between reference (Source 1) and target (Source 2).

Convention (empirically verified):
  SCC delay of +Xms means Source 2 content is X ms EARLY relative to Source 1.
  To find where Source 1 content at ref_time appears in Source 2:
    src2_time = ref_time - delay_ms / 1000

This module centralises the arithmetic so no other code does ad-hoc
timeline conversions.
"""

from __future__ import annotations


def ref_to_src2(ref_time_s: float, delay_ms: float) -> float:
    """Convert reference timeline position to Source 2 position.

    Source 2's actual audio content that matches Source 1 at *ref_time_s*
    is located at ``ref_time_s - delay_ms / 1000`` in Source 2's file.
    """
    return ref_time_s - delay_ms / 1000.0


def src2_to_ref(src2_time_s: float, delay_ms: float) -> float:
    """Convert Source 2 timeline position to reference position."""
    return src2_time_s + delay_ms / 1000.0
