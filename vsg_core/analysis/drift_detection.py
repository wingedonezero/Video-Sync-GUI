# vsg_core/analysis/drift_detection.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from typing import List, Dict, Any

import numpy as np
from sklearn.cluster import DBSCAN

from ..io.runner import CommandRunner

def _get_video_framerate(video_path: str, runner: CommandRunner, tool_paths: dict) -> float:
    """Uses ffprobe to get the video's average frame rate."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    out = runner.run(cmd, tool_paths)
    if not out or '/' not in out:
        return 0.0
    try:
        num, den = map(float, out.strip().split('/'))
        return num / den if den != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0

def diagnose_audio_issue(
    video_path: str,
    chunks: List[Dict[str, Any]],
    config: Dict,
    runner: CommandRunner,
    tool_paths: dict
) -> (str, Dict):
    """
    Analyzes correlation chunks to diagnose the type of sync issue.

    Returns:
        A tuple of (diagnosis_string, details_dict).
        Example: ("PAL_DRIFT", {"rate": 40.8}), ("STEPPING", {}), ("UNIFORM", {})
    """
    accepted_chunks = [c for c in chunks if c.get('accepted', False)]
    if len(accepted_chunks) < 6:
        return "UNIFORM", {}

    # --- Test 1: Check for PAL Drift ---
    framerate = _get_video_framerate(video_path, runner, tool_paths)
    is_pal_framerate = abs(framerate - 25.0) < 0.1

    if is_pal_framerate:
        times = np.array([c['start'] for c in accepted_chunks])
        delays = np.array([c['delay'] for c in accepted_chunks])

        # Perform linear regression to find the slope (drift rate in ms/s)
        slope, _ = np.polyfit(times, delays, 1)

        # PAL drift is ~40.9ms per second. Check if the slope is close.
        if abs(slope - 40.9) < 5.0:
            runner._log_message(f"[PAL Drift Detected] Framerate is ~25fps and audio drift rate is {slope:.2f} ms/s.")
            return "PAL_DRIFT", {"rate": slope}

    # --- Test 2: Check for Stepping ---
    accepted_delays = [c['delay'] for c in accepted_chunks]
    epsilon_ms = config.get('detection_dbscan_epsilon_ms', 20.0)
    min_samples = config.get('detection_dbscan_min_samples', 2)

    delays_array = np.array(accepted_delays).reshape(-1, 1)
    db = DBSCAN(eps=epsilon_ms, min_samples=min_samples).fit(delays_array)
    unique_clusters = set(label for label in db.labels_ if label != -1)

    if len(unique_clusters) > 1:
        runner._log_message(f"[Stepping Detected] Found {len(unique_clusters)} distinct timing clusters.")
        return "STEPPING", {}

    # --- Default Case: Uniform Delay ---
    return "UNIFORM", {}
