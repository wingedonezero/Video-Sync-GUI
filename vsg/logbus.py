
"""Centralized logging + status/progress sinks (UI-agnostic)."""
from __future__ import annotations
import queue
from datetime import datetime
from typing import Callable, List, Optional

LOG_Q: "queue.Queue[str]" = queue.Queue()
STATUS_Q: "queue.Queue[str]" = queue.Queue()
PROGRESS_Q: "queue.Queue[float]" = queue.Queue()
_LOG_SINKS: List[Callable[[str], None]] = []
_STATUS_SINKS: List[Callable[[str], None]] = []
_PROGRESS_SINKS: List[Callable[[float], None]] = []

def add_sink(fn: Callable[[str], None]) -> None:
    if fn not in _LOG_SINKS:
        _LOG_SINKS.append(fn)

def remove_sink(fn: Callable[[str], None]) -> None:
    try:
        _LOG_SINKS.remove(fn)
    except ValueError:
        pass

def add_status_sink(fn: Callable[[str], None]) -> None:
    if fn not in _STATUS_SINKS:
        _STATUS_SINKS.append(fn)

def remove_status_sink(fn: Callable[[str], None]) -> None:
    try:
        _STATUS_SINKS.remove(fn)
    except ValueError:
        pass

def add_progress_sink(fn: Callable[[float], None]) -> None:
    if fn not in _PROGRESS_SINKS:
        _PROGRESS_SINKS.append(fn)

def remove_progress_sink(fn: Callable[[float], None]) -> None:
    try:
        _PROGRESS_SINKS.remove(fn)
    except ValueError:
        pass

def _emit(text: str) -> None:
    try:
        LOG_Q.put_nowait(text)
    except Exception:
        pass
    for s in list(_LOG_SINKS):
        try:
            s(text)
        except Exception:
            pass

def _fmt(*args) -> str:
    ts = datetime.now().strftime("[%H:%M:%S]")
    try:
        text = " ".join(str(a) for a in args)
    except Exception:
        text = " ".join(repr(a) for a in args)
    return f"{ts} {text}"

def _log(*args) -> None:
    """Accepts either (msg...) or (logger, msg...) for legacy calls."""
    if args and not isinstance(args[0], (str, int, float)):
        args = args[1:]
    _emit(_fmt(*args))

def set_status(text: str) -> None:
    try:
        STATUS_Q.put_nowait(str(text))
    except Exception:
        pass
    for s in list(_STATUS_SINKS):
        try:
            s(text)
        except Exception:
            pass

def set_progress(fraction: float) -> None:
    try:
        PROGRESS_Q.put_nowait(float(fraction))
    except Exception:
        pass
    for s in list(_PROGRESS_SINKS):
        try:
            s(float(fraction))
        except Exception:
            pass

def pump_logs() -> None:
    """No-op for Qt; logs are pushed to sinks as they come in."""
    pass
