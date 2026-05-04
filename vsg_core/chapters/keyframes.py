import json

from ..io.runner import CommandRunner


def probe_keyframes_ns(
    ref_video_path: str, runner: CommandRunner, tool_paths: dict
) -> list[int]:
    args = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,flags",
        "-of",
        "json",
        str(ref_video_path),
    ]
    out = runner.run(args, tool_paths)
    if not out:
        runner._log_message("[WARN] ffprobe for keyframes produced no output.")
        return []
    try:
        data = json.loads(out)
        kfs_ns = [
            int(round(float(p["pts_time"]) * 1_000_000_000))
            for p in data.get("packets", [])
            if "pts_time" in p and "K" in p.get("flags", "")
        ]
        kfs_ns.sort()
        runner._log_message(f"[Chapters] Found {len(kfs_ns)} keyframes for snapping.")
        return kfs_ns
    except Exception as e:
        runner._log_message(f"[WARN] Could not parse ffprobe keyframe JSON: {e}")
        return []


def probe_duration_ns(
    ref_video_path: str, runner: CommandRunner, tool_paths: dict
) -> int | None:
    """
    Probe the container/format duration of ``ref_video_path`` in ns.

    Used by chapter normalization to clamp the LAST chapter's
    ``ChapterTimeEnd`` to the actual end of file (instead of the
    legacy ``start + 1s`` heuristic which can overshoot the file
    end). Returns ``None`` on probe failure so the caller can
    fall back to the heuristic.
    """
    args = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(ref_video_path),
    ]
    out = runner.run(args, tool_paths)
    if not out:
        runner._log_message("[WARN] ffprobe for duration produced no output.")
        return None
    try:
        data = json.loads(out)
        dur_str = data.get("format", {}).get("duration")
        if not dur_str:
            return None
        return int(round(float(dur_str) * 1_000_000_000))
    except Exception as e:
        runner._log_message(f"[WARN] Could not parse ffprobe duration JSON: {e}")
        return None
