# Logging queue & helpers (moved)
from __future__ import annotations
from vsg.settings import CONFIG
from datetime import datetime
import logging, queue
import dearpygui.dearpygui as dpg
LOG_Q: "queue.Queue[str]" = queue.Queue()
from .settings import CONFIG

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
                autoscroll = bool(globals().get('CONFIG', {})).__class__ is bool and globals().get('CONFIG', {}).get('log_autoscroll', True) if isinstance(globals().get('CONFIG', {}), dict) else True
    if dpg.does_item_exist('log_child') and autoscroll:
                    try:
                        maxy = dpg.get_y_scroll_max('log_child')
                        dpg.set_y_scroll('log_child', maxy)
                    except Exception:
                        pass
    except queue.Empty:
        pass


