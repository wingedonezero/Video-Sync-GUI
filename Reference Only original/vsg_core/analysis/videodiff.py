from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..io.runner import CommandRunner

if TYPE_CHECKING:
    from vsg_core.models import AppSettings


def run_videodiff(
    ref_file: str,
    target_file: str,
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict,
) -> tuple[int, float]:
    """
    Prefer an explicit settings path if it exists; otherwise allow PATH/tool_paths resolution.
    Do not hard-fail just because a literal path doesn't exist—let runner.resolve/PATH try it.
    """
    cfg_path = (settings.videodiff_path or "").strip()
    if cfg_path:
        # Use absolute/relative path if it exists; else treat it as a program name
        if Path(cfg_path).exists():
            exe = cfg_path
        else:
            # user provided a name; let runner/tool_paths resolve it
            exe = cfg_path
    else:
        # fall back to discovered tool or the bare name
        exe = tool_paths.get("videodiff") or "videodiff"

    out = runner.run([str(exe), str(ref_file), str(target_file)], tool_paths)
    if not out:
        raise RuntimeError("videodiff produced no output or failed to run.")

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last_line = ""
    for ln in reversed(lines):
        if "[Result]" in ln and ("ss:" in ln or "itsoffset:" in ln):
            last_line = ln
            break

    if not last_line:
        raise RuntimeError(
            "Could not find a valid '[Result]' line in videodiff output."
        )

    m = re.search(
        r"(itsoffset|ss)\s*:\s*(-?\d+(?:\.\d+)?)s.*?error:\s*([0-9.]+)",
        last_line,
        flags=re.IGNORECASE,
    )
    if not m:
        raise RuntimeError(f"Could not parse videodiff result line: '{last_line}'")

    kind, s_val, err_val = m.groups()
    seconds = float(s_val)
    delay_ms = int(round(seconds * 1000))
    if kind.lower() == "ss":
        delay_ms = -delay_ms

    error_value = float(err_val)
    runner._log_message(
        f"[VideoDiff] Result -> {kind.lower()} {seconds:.5f}s, error {error_value:.2f} => delay {delay_ms:+} ms"
    )
    return delay_ms, error_value
