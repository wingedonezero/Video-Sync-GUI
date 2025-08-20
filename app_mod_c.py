"""
Phase C entry: patches analysis.audio_xcorr, mux.*, and jobs.* into the monolith.
"""
# Phase A
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings, apply_settings_to_ui, pull_ui_to_settings, sync_config_from_ui
from vsg.logbus import LOG_Q, _log, pump_logs
from vsg.tools import find_required_tools, run_command

# Phase B
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
from vsg.plan.build import build_plan, summarize_plan

# Phase C
from vsg.analysis.audio_xcorr import (
    get_audio_stream_index, extract_audio_chunk, find_audio_delay,
    best_from_results, run_audio_correlation_workflow
)
from vsg.mux.tokens import _tokens_for_track, build_mkvmerge_tokens
from vsg.mux.run import write_mkvmerge_json_options, run_mkvmerge_with_json
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job

import importlib
vsgui = importlib.import_module("video_sync_gui")

# Settings + logging + tools
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

# Analysis
vsgui.run_videodiff = run_videodiff
vsgui.format_delay_ms = format_delay_ms
vsgui.get_audio_stream_index = get_audio_stream_index
vsgui.extract_audio_chunk = extract_audio_chunk
vsgui.find_audio_delay = find_audio_delay
vsgui.best_from_results = best_from_results
vsgui.run_audio_correlation_workflow = run_audio_correlation_workflow

# Plan + Mux
vsgui.build_plan = build_plan
vsgui.summarize_plan = summarize_plan
vsgui._tokens_for_track = _tokens_for_track
vsgui.build_mkvmerge_tokens = build_mkvmerge_tokens
vsgui.write_mkvmerge_json_options = write_mkvmerge_json_options
vsgui.run_mkvmerge_with_json = run_mkvmerge_with_json

# Jobs
vsgui.discover_jobs = discover_jobs
vsgui.merge_job = merge_job

if __name__ == "__main__":
    vsgui.build_ui()
