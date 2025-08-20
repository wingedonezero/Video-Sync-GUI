"""
vsg.mux.tokens — FIXED WRAPPER
Use the implementations from the monolith to avoid extraction/indent issues,
while keeping the vsg import surface stable.
"""
from __future__ import annotations
from importlib import import_module
from vsg.logbus import _log

_monolith = import_module("video_sync_gui")

def _tokens_for_track(*args, **kwargs):
    return _monolith._tokens_for_track(*args, **kwargs)

def build_mkvmerge_tokens(*args, **kwargs):
    return _monolith.build_mkvmerge_tokens(*args, **kwargs)
