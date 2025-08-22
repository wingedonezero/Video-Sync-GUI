"""Centralized logging queue and helpers (UI-agnostic)."""
from __future__ import annotations
import queue
from datetime import datetime
from typing import Callable, List

LOG_Q: "queue.Queue[str]" = queue.Queue()
_SINKS: List[Callable[[str], None]] = []

def add_sink(fn: Callable[[str], None]) -> None:
    """Register a sink callback which receives each log line."""
    if fn not in _SINKS:
        _SINKS.append(fn)

def remove_sink(fn: Callable[[str], None]) -> None:
    try:
        _SINKS.remove(fn)
    except ValueError:
        pass

def _emit(line: str) -> None:
    LOG_Q.put(line)
    for s in list(_SINKS):
        try:
            s(line)
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
    _emit(_fmt(*args))

def pump_logs() -> None:
    """No-op for Qt; logs are pushed to sinks as they come in."""
    pass
