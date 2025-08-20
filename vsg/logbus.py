# Logging queue & helpers (moved)
from __future__ import annotations
from datetime import datetime
import logging, queue
LOG_Q: "queue.Queue[str]" = queue.Queue()

def _log(logger, message: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {message}'
    try:
        logger.info(line)
    except Exception:
        pass
    LOG_Q.put(line)


def pump_logs():
    try:
        while True:
            ln = LOG_Q.get_nowait()
            if dpg.does_item_exist('log_scroller'):
                dpg.add_text(ln, parent='log_scroller')
                if dpg.does_item_exist('log_child') and CONFIG.get('log_autoscroll', True):
                    try:
                        maxy = dpg.get_y_scroll_max('log_child')
                        dpg.set_y_scroll('log_child', maxy)
                    except Exception:
                        pass
    except queue.Empty:
        pass


