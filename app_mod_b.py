"""
Phase B entry: also patches analysis.videodiff and plan.build into the monolith.
"""
# Phase A monkeypatches
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings, apply_settings_to_ui, pull_ui_to_settings, sync_config_from_ui
from vsg.logbus import LOG_Q, _log, pump_logs
from vsg.tools import find_required_tools, run_command

# Phase B monkeypatches
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
from vsg.plan.build import build_plan, summarize_plan

import importlib
vsgui = importlib.import_module("video_sync_gui")

# Replace attributes in the monolith
vsgui.CONFIG = CONFIG
vsgui.SETTINGS_PATH = SETTINGS_PATH
vsgui.load_settings = load_settings
vsgui.save_settings = save_settings
vsgui.apply_settings_to_ui = apply_settings_to_ui
vsgui.pull_ui_to_settings = pull_ui_to_settings
vsgui.sync_config_from_ui = sync_config_from_ui

vsgui.LOG_Q = LOG_Q
vsgui._log = _log
vsgui.pump_logs = pump_logs

vsgui.find_required_tools = find_required_tools
vsgui.run_command = run_command

vsgui.run_videodiff = run_videodiff
vsgui.format_delay_ms = format_delay_ms

vsgui.build_plan = build_plan
vsgui.summarize_plan = summarize_plan

if __name__ == "__main__":
    vsgui.build_ui()
