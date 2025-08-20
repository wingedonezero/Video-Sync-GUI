"""Central logging queue and helpers (robust)."""
from __future__ import annotations
from datetime import datetime
import logging, queue
import dearpygui.dearpygui as dpg

LOG_Q: "queue.Queue[str]" = queue.Queue()

def _log(*args) -> None:
    try:
        msg = " ".join(str(a) for a in args)
        ts = datetime.now().strftime("%H:%M:%S")
        LOG_Q.put(f"[{ts}] {msg}")
    except Exception as e:
        try:
            LOG_Q.put(str(args))
        except Exception:
            pass
        logging.debug("log enqueue failed: %r", e)

def _autoscroll_pref() -> bool:
    try:
        from vsg import settings as _settings
        cfg = getattr(_settings, "CONFIG", {})
        if isinstance(cfg, dict):
            return bool(cfg.get("log_autoscroll", True))
    except Exception:
        pass
    return True

def pump_logs() -> None:
    autoscroll = _autoscroll_pref()
    has_child = dpg.does_item_exist("log_child")
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
                pass
    if rendered_any and autoscroll and dpg.does_item_exist("log_scroller"):
        try:
            max_scroll = dpg.get_y_scroll_max("log_scroller")
            dpg.set_y_scroll("log_scroller", max_scroll)
        except Exception:
            pass
