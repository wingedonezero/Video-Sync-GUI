"""
This module is a *thin wrapper* around the existing monolith `video_sync_gui.py`.
It simply re-exports functions/objects 1:1 so behavior is identical.
In the next step, we'll *move* the implementations here and update imports in the GUI.

Do NOT edit logic here yet—this is a move-only scaffolding for safe modularization.
"""
from __future__ import annotations
# Import from the current monolith
import importlib
_monolith = importlib.import_module("video_sync_gui")
# These may not exist in some snapshots; getattr for safety.
get_audio_stream_index = getattr(_monolith, "get_audio_stream_index", None)
extract_audio_chunk = getattr(_monolith, "extract_audio_chunk", None)
find_audio_delay = getattr(_monolith, "find_audio_delay", None)
run_audio_correlation_workflow = getattr(_monolith, "run_audio_correlation_workflow", None)
best_from_results = getattr(_monolith, "best_from_results", None)
