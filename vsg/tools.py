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
find_required_tools = _monolith.find_required_tools
run_command = _monolith.run_command
get_stream_info = getattr(_monolith, "get_stream_info", None)
extract_tracks = getattr(_monolith, "extract_tracks", None)
extract_attachments = getattr(_monolith, "extract_attachments", None)
ffprobe_duration = getattr(_monolith, "ffprobe_duration", None)
