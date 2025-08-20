# Logging queue & helpers (Phase A — robust, accepts old/new _log signatures)
from __future__ import annotations
from datetime import datetime
import logging
import queue

import dearpygui.dearpygui as dpg

# Public queue used by the GUI
LOG_Q: "queue.Queue[str]" = queue.Queue()

def _log(*args) -> None:
    """Accepts (_msg) or (logger, _msg) for compatibility."""
    if len(args) == 1:
        msg = args[0]
    else:
        msg = args[1]
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        LOG_Q.put(line)
    except Exception:
        try:
            logging.debug("LOG_Q.put failed; line=%r", line)
        except Exception:
            pass

def _autoscroll_pref() -> bool:
    """Return autoscroll preference; defaults True if CONFIG not ready."""
    try:
        from vsg import settings as _settings  # lazy to avoid circulars
        cfg = getattr(_settings, "CONFIG", {})
        if isinstance(cfg, dict):
            return bool(cfg.get("log_autoscroll", True))
    except Exception:
        pass
    return True

def _dpg_exists(item_id: str) -> bool:
    try:
        return bool(dpg.does_item_exist(item_id))
    except Exception:
        return False

def pump_logs() -> None:
    """Drain LOG_Q and render into DPG widgets if present."""
    autoscroll = _autoscroll_pref()
    has_child = _dpg_exists("log_child")
    rendered_any = False

    while True:
        try:
            line = LOG_Q.get_nowait()
        except Exception:
            break

        if has_child:
            try:
                dpg.add_text(line, parent="log_child", wrap=0)
                rendered_any = True
            except Exception:
                pass

    if rendered_any and autoscroll and _dpg_exists("log_scroller"):
        try:
            max_scroll = dpg.get_y_scroll_max("log_scroller")
            dpg.set_y_scroll("log_scroller", max_scroll)
        except Exception:
            pass
