# Clean manual copy — jobs.merge_job
from __future__ import annotations
from typing import Any, Dict
import logging
from vsg.logbus import _log
from vsg.plan.build import build_plan, summarize_plan
from vsg.mux.tokens import build_mkvmerge_tokens
from vsg.mux.run import write_mkvmerge_json_options, run_mkvmerge_with_json
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
try:
    from vsg.analysis.audio_xcorr import run_audio_correlation_workflow
except Exception:
    run_audio_correlation_workflow = None

def merge_job(job: Dict[str, Any]) -> None:
    """
    Dummy merge_job implementation — replace with full logic from video_sync_gui.py.
    """
    _log(f"merge_job called with job: {job}")
    plan = build_plan(job)
    summarize_plan(plan)
    tokens = build_mkvmerge_tokens(plan)
    _log("Tokens: " + " ".join(tokens))
    opts_path = "opts.json"
    write_mkvmerge_json_options(plan, opts_path)
    run_mkvmerge_with_json(opts_path, plan.get("output_path", "out.mkv"))
