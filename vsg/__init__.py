# vsg package — wrappers that delegate to video_sync_gui (monolith) for behavior parity
from . import settings, logbus, tools
from .analysis import videodiff, audio_xcorr
from .plan import build as plan
from .mux import tokens, run as mux
from .jobs import discover, merge_job

__all__ = [
    "settings",
    "logbus",
    "tools",
    "analysis",
    "plan",
    "mux",
    "jobs",
    "discover",
    "merge_job",
]
