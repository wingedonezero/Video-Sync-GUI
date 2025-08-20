# Logging queue & helpers (Phase A — clean, defensive implementation)
from __future__ import annotations
from datetime import datetime
import logging
import queue
import typing

import dearpygui.dearpygui as dpg

# Global log queue
LOG_Q: "queue.Queue[str]" = queue.Queue()

def _log(msg: str) -> None:
    """
    Enqueue a log line with a timestamp. GUI drains this with pump_logs().
    """
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        LOG_Q.put(f"[{ts}] {msg}")
    except Exception as e:
        # Last-resort fallback to avoid crashing the app on logging
        try:
            LOG_Q.put(str(msg))
        except Exception:
            pass
        logging.debug("log enqueue failed: %r", e)

def _get_autoscroll_default_true() -> bool:
    """
    Read autoscroll preference from settings if available.
    Falls back to True if CONFIG isn't ready yet.
    """
    try:
        # Lazy import to avoid circulars during early startup
        from vsg import settings as _settings  # type: ignore
        cfg = getattr(_settings, "CONFIG", {})
        if isinstance(cfg, dict):
            return bool(cfg.get("log_autoscroll", True))
    except Exception:
        pass
    return True

def pump_logs() -> None:
    """
    Drain LOG_Q and render into the DearPyGui log region.
    Safe to call even before CONFIG exists.
    """
    autoscroll = _get_autoscroll_default_true()

    # If the widgets don't exist yet, just drain/queue silently.
    has_child = False
    try:
        has_child = dpg.does_item_exist("log_child")
    except Exception:
        has_child = False

    # Drain and render
    rendered_any = False
    while not LOG_Q.empty():
        try:
            line = LOG_Q.get_nowait()
        except Exception:
            break
        if has_child:
            try:
                dpg.add_text(line, parent="log_child", wrap=0)
                rendered_any = True
            except Exception:
                # If UI not ready, swallow (we've removed from queue)
                pass

    # Best-effort autoscroll
    if rendered_any and autoscroll:
        try:
            if dpg.does_item_exist("log_scroller"):
                # Try to push to bottom
                try:
                    max_scroll = dpg.get_y_scroll_max("log_scroller")
                    dpg.set_y_scroll("log_scroller", max_scroll)
                except Exception:
                    # Older DPG versions may have different API; ignore
                    pass
        except Exception:
            pass
