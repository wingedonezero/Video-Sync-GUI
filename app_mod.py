"""
Phase A app entry: monkeypatch monolith to use moved modules.
Behavior should remain identical.
"""
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings, apply_settings_to_ui, pull_ui_to_settings, sync_config_from_ui
from vsg.logbus import LOG_Q, _log, pump_logs
from vsg.tools import find_required_tools, run_command

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

if __name__ == "__main__":
    vsgui.build_ui()
