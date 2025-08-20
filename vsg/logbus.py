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
LOG_Q = _monolith.LOG_Q
_log = _monolith._log
pump_logs = _monolith.pump_logs
