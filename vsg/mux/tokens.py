"""
vsg.mux.tokens — wrapper delegating to monolith to ensure parity.
"""
from __future__ import annotations
from importlib import import_module
_monolith = import_module("video_sync_gui")

def _tokens_for_track(*args, **kwargs):
    return _monolith._tokens_for_track(*args, **kwargs)

def build_mkvmerge_tokens(*args, **kwargs):
    return _monolith.build_mkvmerge_tokens(*args, **kwargs)
