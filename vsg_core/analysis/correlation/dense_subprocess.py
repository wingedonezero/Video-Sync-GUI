# vsg_core/analysis/correlation/dense_subprocess.py
"""
Subprocess worker for dense sliding-window audio correlation.

Isolates torch/HIP in a separate process. The ROCm runtime keeps a
busy-polling thread (``AsyncEventsLoop``) alive from the first HIP
context until process exit, so GPU correlation must not run inside the
long-lived GUI process. Follows the same pattern as
``vsg_core/subtitles/sync_mode_plugins/video_verified/sliding_subprocess.py``.

Communication protocol:
  - PCM input: two ``.npy`` files (mono float32) written by the parent
  - Config: JSON file with serialized AppSettings
  - Logs: printed to stdout (forwarded by parent)
  - Result: JSON prefixed with ``__VSG_CORRELATION_JSON__`` on stdout
  - Output: JSON file with per-method ChunkResult lists

The parent (``dense_launcher.py::run_dense_correlation_subprocess``)
launches this module with
``python -m vsg_core.analysis.correlation.dense_subprocess`` and parses
the marker line from stdout to collect the result payload.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

JSON_PREFIX = "__VSG_CORRELATION_JSON__ "


def _log(message: str) -> None:
    """Print a log line to stdout for the parent to forward."""
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run dense sliding-window correlation in a subprocess."
    )
    parser.add_argument(
        "--ref-pcm", required=True, help="Path to reference PCM .npy file"
    )
    parser.add_argument("--tgt-pcm", required=True, help="Path to target PCM .npy file")
    parser.add_argument(
        "--sample-rate", required=True, type=int, help="PCM sample rate in Hz"
    )
    parser.add_argument(
        "--config-json", required=True, help="Path to settings JSON file"
    )
    parser.add_argument(
        "--output-json", required=True, help="Path to write result JSON"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("single", "multi"),
        help="single = one method from settings, multi = all enabled methods",
    )
    parser.add_argument(
        "--source-separated",
        action="store_true",
        help="Resolve the source-separated correlation method from settings",
    )
    parser.add_argument(
        "--min-match", required=True, type=float, help="Acceptance threshold (0-100)"
    )
    parser.add_argument(
        "--start-pct", required=True, type=float, help="Scan range start (0-100)"
    )
    parser.add_argument(
        "--end-pct", required=True, type=float, help="Scan range end (0-100)"
    )
    args = parser.parse_args()

    output_path = Path(args.output_json)

    # Load settings
    try:
        from vsg_core.models.settings import AppSettings

        with open(args.config_json, encoding="utf-8") as f:
            config_dict = json.load(f)
        settings = AppSettings.model_validate(config_dict)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to load config: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Load PCM arrays fully (not mmap): the correlation methods hand
    # window slices to torch.from_numpy, which warns on (and mis-handles)
    # read-only mmap-backed arrays. RAM cost matches the old in-process path.
    try:
        import numpy as np

        ref_pcm = np.load(args.ref_pcm)
        tgt_pcm = np.load(args.tgt_pcm)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to load PCM: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Run correlation — all dense progress/summary logging goes to stdout
    try:
        from vsg_core.analysis.correlation.dense_launcher import chunk_result_to_dict
        from vsg_core.analysis.correlation.dense_runner import run_correlation_job

        job_result = run_correlation_job(
            ref_pcm,
            tgt_pcm,
            args.sample_rate,
            settings,
            use_source_separated=args.source_separated,
            multi_corr=(args.mode == "multi"),
            min_match=args.min_match,
            start_pct=args.start_pct,
            end_pct=args.end_pct,
            log=_log,
        )
    except Exception as exc:
        payload = {"success": False, "error": f"Correlation failed: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Write result JSON
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "sr": args.sample_rate,
            "mode": args.mode,
            "selected_method": job_result.selected_method,
            "results_by_method": {
                name: [chunk_result_to_dict(r) for r in results]
                for name, results in job_result.results_by_method.items()
            },
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


if __name__ == "__main__":
    sys.exit(main())
