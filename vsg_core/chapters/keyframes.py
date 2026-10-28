import json
from dataclasses import dataclass

from ..io.runner import CommandRunner


@dataclass(frozen=True, slots=True)
class KeyframeTimes:
    """Keyframe times as the file stores them, plus the unit it stores them in.

    ``unit_ns`` is the stream's time base in ns (1,000,000 for an MKV with the
    default 1 ms timestamp scale), or None when the time base is not a whole
    number of ns.
    """

    times_ns: list[int]
    unit_ns: int | None


def probe_keyframes_ns(
    ref_video_path: str, runner: CommandRunner, tool_paths: dict
) -> KeyframeTimes | None:
    args = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts,flags:stream=time_base",
        "-of",
        "json",
        str(ref_video_path),
    ]
    out = runner.run(args, tool_paths)
    if not out:
        runner._log_message("[WARN] ffprobe for keyframes produced no output.")
        return None
    try:
        data = json.loads(out)
        num, den = (int(x) for x in data["streams"][0]["time_base"].split("/"))
        kfs_ns = sorted(
            (int(p["pts"]) * num * 1_000_000_000 + den // 2) // den
            for p in data.get("packets", [])
            if p.get("pts") is not None and "K" in p.get("flags", "")
        )
        unit_ns = (
            num * 1_000_000_000 // den if (num * 1_000_000_000) % den == 0 else None
        )
        runner._log_message(f"[Chapters] Found {len(kfs_ns)} keyframes for snapping.")
        return KeyframeTimes(times_ns=kfs_ns, unit_ns=unit_ns) if kfs_ns else None
    except Exception as e:
        runner._log_message(f"[WARN] Could not parse ffprobe keyframe JSON: {e}")
        return None


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
