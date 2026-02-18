# vsg_core/subtitles/sync_mode_plugins/video_verified/neural_subprocess.py
"""
Subprocess worker for neural feature matching.

Isolates the ISC model + GPU allocation in a separate process to avoid
memory conflicts with the main app. Follows the same pattern as
vsg_core/subtitles/ocr/unified_subprocess.py.

Communication protocol:
  - Config: JSON file with settings + video paths
  - Logs: printed to stdout (forwarded by parent)
  - Result: JSON prefixed with __VSG_NEURAL_JSON__ on stdout
  - Output: JSON file with detailed results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


JSON_PREFIX = "__VSG_NEURAL_JSON__ "


class _SubprocessRunner:
    """Minimal runner that prints log messages to stdout for parent to capture."""

    def _log_message(self, message: str) -> None:
        print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run neural feature matching in a subprocess."
    )
    parser.add_argument(
        "--source-video", required=True, help="Path to source video file"
    )
    parser.add_argument(
        "--target-video", required=True, help="Path to target video file"
    )
    parser.add_argument(
        "--total-delay-ms", required=True, type=float, help="Total delay with global shift"
    )
    parser.add_argument(
        "--global-shift-ms", required=True, type=float, help="Global shift component"
    )
    parser.add_argument(
        "--config-json", required=True, help="Path to settings JSON file"
    )
    parser.add_argument(
        "--output-json", required=True, help="Path to write result JSON"
    )
    parser.add_argument(
        "--temp-dir", required=False, help="Temp directory for ffms2 index"
    )
    parser.add_argument(
        "--video-duration-ms", required=False, type=float, default=0,
        help="Video duration in ms (0 = auto-detect)"
    )
    parser.add_argument(
        "--debug-output-dir", required=False,
        help="Directory for debug reports (omit to disable)"
    )
    args = parser.parse_args()

    config_path = Path(args.config_json)
    output_path = Path(args.output_json)
    temp_dir = Path(args.temp_dir) if args.temp_dir else None
    debug_output_dir = Path(args.debug_output_dir) if args.debug_output_dir else None
    video_duration_ms = args.video_duration_ms if args.video_duration_ms > 0 else None

    # Load settings
    try:
        from vsg_core.models.settings import AppSettings

        with open(config_path, encoding="utf-8") as f:
            config_dict = json.load(f)
        settings = AppSettings.model_validate(config_dict)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to load config: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    runner = _SubprocessRunner()

    # Run neural matching
    try:
        from .neural_matcher import calculate_neural_verified_offset

        final_offset_ms, details = calculate_neural_verified_offset(
            source_video=args.source_video,
            target_video=args.target_video,
            total_delay_ms=args.total_delay_ms,
            global_shift_ms=args.global_shift_ms,
            settings=settings,
            runner=runner,
            temp_dir=temp_dir,
            video_duration_ms=video_duration_ms,
            debug_output_dir=debug_output_dir,
        )
    except Exception as exc:
        payload = {"success": False, "error": f"Neural matching failed: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Write result JSON
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "final_offset_ms": final_offset_ms,
            "details": _make_serializable(details),
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to write result: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    payload = {"success": True, "json_path": str(output_path)}
    print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
    return 0


def _make_serializable(obj):
    """Convert numpy/torch types to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, float):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bool):
        return obj
    if obj is None:
        return obj
    # numpy types
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return str(obj)


if __name__ == "__main__":
    sys.exit(main())
