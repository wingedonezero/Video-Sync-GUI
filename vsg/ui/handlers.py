from __future__ import annotations

import threading
import uuid

from vsg.jobs.merge_job import merge_job
from vsg.logbus import _log
from vsg.tools import find_required_tools
from vsg.ui.options import SETTINGS_DIRTY, _save_now

RUN_LOCK = threading.Lock()
JOB_RUNNING = False


def _set_buttons_enabled(dpg, enabled: bool) -> None:
    for tag in ("analyze_btn", "analyze_merge_btn"):
        try:
            (dpg.enable_item if enabled else dpg.disable_item)(tag)
        except Exception:
            pass


def _start_worker(dpg, mode: str) -> None:
    global JOB_RUNNING
    with RUN_LOCK:
        if JOB_RUNNING:
            _log("Run ignored: a job is already in progress.")
            return
        JOB_RUNNING = True
    try:
        if SETTINGS_DIRTY:
            _save_now()
    except Exception:
        pass
    _set_buttons_enabled(dpg, False)
    run_id = uuid.uuid4().hex[:8]
    _log(f"[run {run_id}] starting ({mode})")

    def worker():
        try:
            if not find_required_tools():
                _log(f"[run {run_id}] missing tools; aborting")
                return
            res = merge_job(mode=mode)
            _log(f"[run {run_id}] result: {res}")
        except Exception as e:
            _log(f"[run {run_id}] ERROR: {e}")
        finally:
            _set_buttons_enabled(dpg, True)
            global JOB_RUNNING
            with RUN_LOCK:
                JOB_RUNNING = False
            _log(f"[run {run_id}] done")

    threading.Thread(target=worker, daemon=True).start()


def on_click_analyze(sender, app_data, user_data):
    dpg = user_data.get("dpg")
    _start_worker(dpg, mode="analyze")


def on_click_analyze_merge(sender, app_data, user_data):
    dpg = user_data.get("dpg")
    _start_worker(dpg, mode="analyze_merge")


def wire_handlers(dpg) -> None:
    try:
        dpg.set_item_callback("analyze_btn", on_click_analyze, user_data={"dpg": dpg})
    except Exception:
        pass
    try:
        dpg.set_item_callback("analyze_merge_btn", on_click_analyze_merge, user_data={"dpg": dpg})
    except Exception:
        pass
