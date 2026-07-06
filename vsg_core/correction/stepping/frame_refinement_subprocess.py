# vsg_core/correction/stepping/frame_refinement_subprocess.py
"""
Subprocess worker for frame-precision splice refinement.

Isolates torch/VapourSynth (and the HIP context they create) in a
separate process — the ROCm runtime keeps a busy-polling thread alive
from the first HIP context until process exit, so the refinement pass
must not run inside the long-lived GUI process. Follows the same
pattern as ``vsg_core/analysis/correlation/dense_subprocess.py``.

Communication protocol:
  - Splices: JSON file with the fields ``_refine_one`` reads
    (``boundary_result`` / ``snap_metadata`` stay in the parent)
  - Config: JSON file with serialized AppSettings
  - Logs: printed to stdout (forwarded by parent)
  - Result: JSON prefixed with ``__VSG_FRAMEREFINE_JSON__`` on stdout
  - Output: JSON file with per-splice ``src2_time_s`` +
    ``FrameRefinementResult`` fields

Import/open_clip failures inside the pass are RESULTS, not errors: the
in-process code stamps every splice point and returns normally, and
this worker serializes those stamps with exit code 0 — the parent
applies them exactly as the in-process path would have.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .types import FrameRefinementResult, SilenceZone, SplicePoint

JSON_PREFIX = "__VSG_FRAMEREFINE_JSON__ "


# ---------------------------------------------------------------------------
# Serialization helpers (shared with the parent-side launcher)
# ---------------------------------------------------------------------------


def splice_point_to_payload(index: int, sp: SplicePoint) -> dict[str, Any]:
    """Serialize the SplicePoint fields the refinement pass reads."""
    silence: dict[str, float | str] | None = None
    if sp.silence_zone is not None:
        silence = {
            "start_s": sp.silence_zone.start_s,
            "end_s": sp.silence_zone.end_s,
            "center_s": sp.silence_zone.center_s,
            "avg_db": sp.silence_zone.avg_db,
            "duration_ms": sp.silence_zone.duration_ms,
            "source": sp.silence_zone.source,
        }
    return {
        "index": index,
        "ref_time_s": sp.ref_time_s,
        "src2_time_s": sp.src2_time_s,
        "delay_before_ms": sp.delay_before_ms,
        "delay_after_ms": sp.delay_after_ms,
        "correction_ms": sp.correction_ms,
        "silence_zone": silence,
    }


def payload_to_splice_point(payload: dict[str, Any]) -> SplicePoint:
    """Rebuild a lightweight SplicePoint from the payload.

    ``boundary_result`` / ``snap_metadata`` are intentionally left empty:
    ``_refine_one`` never reads them, and the parent re-applies the
    refinement onto its own full splice points.
    """
    silence = None
    raw_zone = payload.get("silence_zone")
    if raw_zone is not None:
        silence = SilenceZone(
            start_s=float(raw_zone["start_s"]),
            end_s=float(raw_zone["end_s"]),
            center_s=float(raw_zone["center_s"]),
            avg_db=float(raw_zone["avg_db"]),
            duration_ms=float(raw_zone["duration_ms"]),
            source=str(raw_zone["source"]),
        )
    return SplicePoint(
        ref_time_s=float(payload["ref_time_s"]),
        src2_time_s=float(payload["src2_time_s"]),
        delay_before_ms=float(payload["delay_before_ms"]),
        delay_after_ms=float(payload["delay_after_ms"]),
        correction_ms=float(payload["correction_ms"]),
        silence_zone=silence,
    )


def frame_refinement_result_to_dict(fr: FrameRefinementResult) -> dict[str, Any]:
    """Serialize a FrameRefinementResult for the result JSON."""
    return {
        "mode": fr.mode,
        "reason": fr.reason,
        "before_anchor_offset_frames": fr.before_anchor_offset_frames,
        "after_anchor_offset_frames": fr.after_anchor_offset_frames,
        "before_anchor_score": fr.before_anchor_score,
        "after_anchor_score": fr.after_anchor_score,
        "audio_expected_jump_frames": fr.audio_expected_jump_frames,
        "measured_jump_frames": fr.measured_jump_frames,
        "jump_confirmed": fr.jump_confirmed,
        "last_before_frame": fr.last_before_frame,
        "first_after_frame": fr.first_after_frame,
        "audio_src2_time_s": fr.audio_src2_time_s,
        "video_src2_time_s": fr.video_src2_time_s,
        "frame_drift_ms": fr.frame_drift_ms,
        "target_fps": fr.target_fps,
    }


def frame_refinement_result_from_dict(data: dict[str, Any]) -> FrameRefinementResult:
    """Rebuild a FrameRefinementResult from the result JSON."""

    def _opt_int(value: Any) -> int | None:
        return None if value is None else int(value)

    def _opt_float(value: Any) -> float | None:
        return None if value is None else float(value)

    return FrameRefinementResult(
        mode=str(data["mode"]),
        reason=str(data["reason"]),
        before_anchor_offset_frames=_opt_int(data["before_anchor_offset_frames"]),
        after_anchor_offset_frames=_opt_int(data["after_anchor_offset_frames"]),
        before_anchor_score=float(data["before_anchor_score"]),
        after_anchor_score=float(data["after_anchor_score"]),
        audio_expected_jump_frames=_opt_int(data["audio_expected_jump_frames"]),
        measured_jump_frames=_opt_int(data["measured_jump_frames"]),
        jump_confirmed=bool(data["jump_confirmed"]),
        last_before_frame=_opt_int(data["last_before_frame"]),
        first_after_frame=_opt_int(data["first_after_frame"]),
        audio_src2_time_s=float(data["audio_src2_time_s"]),
        video_src2_time_s=_opt_float(data["video_src2_time_s"]),
        frame_drift_ms=float(data["frame_drift_ms"]),
        target_fps=_opt_float(data["target_fps"]),
    )


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    """Print a log line to stdout for the parent to forward."""
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frame-precision splice refinement in a subprocess."
    )
    parser.add_argument(
        "--src1-video", required=True, help="Path to Source 1 video file"
    )
    parser.add_argument(
        "--src2-video", required=True, help="Path to Source 2 video file"
    )
    parser.add_argument(
        "--fps", required=True, type=float, help="Target (src2) frames per second"
    )
    parser.add_argument(
        "--splices-json", required=True, help="Path to splice-points JSON file"
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
    args = parser.parse_args()

    output_path = Path(args.output_json)
    temp_dir = Path(args.temp_dir) if args.temp_dir else None

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

    # Load splice points
    try:
        with open(args.splices_json, encoding="utf-8") as f:
            raw_splices = json.load(f)
        splice_points = [payload_to_splice_point(p) for p in raw_splices]
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to load splices: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Run refinement — gate stamps (import failure, open_clip failure) come
    # back as normal results and are serialized like any other outcome.
    try:
        from .frame_refinement import _refine_in_process

        refined = _refine_in_process(
            splice_points,
            src1_video_path=args.src1_video,
            src2_video_path=args.src2_video,
            fps=args.fps,
            settings=settings,
            temp_dir=temp_dir,
            log=_log,
        )
    except Exception as exc:
        payload = {"success": False, "error": f"Refinement failed: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    # Write result JSON
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "splices": [
                {
                    "index": i,
                    "src2_time_s": sp.src2_time_s,
                    "frame_refinement": frame_refinement_result_to_dict(
                        # _refine_in_process attaches a result to every point
                        sp.frame_refinement  # type: ignore[arg-type]
                    ),
                }
                for i, sp in enumerate(refined)
            ]
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
