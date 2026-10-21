# vsg_core/system/ffmpeg_tools.py
"""Choose which ffmpeg/ffprobe binaries the app runs.

A chosen folder goes first on PATH rather than into tool_paths: about a dozen
call sites launch a bare "ffmpeg"/"ffprobe" themselves, and child processes
inherit PATH, so every launch in a job resolves to the same build.

Only the command-line tools change. PyAV and VapourSynth/ffms2 keep the system
FFmpeg libraries they were built against.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG_BINARIES = ("ffmpeg", "ffprobe")


@dataclass(slots=True)
class _PathState:
    # The folder this module last put on PATH, so a change can take it off again.
    applied_dir: str | None = None


_state = _PathState()


@dataclass(frozen=True, slots=True)
class FfmpegDirResult:
    """Outcome of apply_ffmpeg_dir."""

    active_dir: str | None  # folder now first on PATH; None = system tools
    problem: str | None  # why a chosen folder was not used


def missing_binaries(folder: Path) -> list[str]:
    """Names from FFMPEG_BINARIES that are not executable files in folder."""
    return [
        name
        for name in FFMPEG_BINARIES
        if not (folder / name).is_file() or not os.access(folder / name, os.X_OK)
    ]


def system_path() -> str:
    """PATH without the folder this module put on it: where the system tools are."""
    return os.pathsep.join(
        e
        for e in os.environ.get("PATH", "").split(os.pathsep)
        if e and e != _state.applied_dir
    )


def apply_ffmpeg_dir(ffmpeg_dir: str) -> FfmpegDirResult:
    """Put ffmpeg_dir first on PATH, or go back to the system tools when empty.

    The folder must hold both ffmpeg and ffprobe: a mixed pair would probe with
    one build and decode with another. If either is missing, the system tools
    are used and the reason is returned.
    """
    entries = system_path().split(os.pathsep) if system_path() else []
    _state.applied_dir = None

    result = FfmpegDirResult(active_dir=None, problem=None)
    if ffmpeg_dir.strip():
        folder = Path(ffmpeg_dir.strip()).expanduser().resolve()
        missing = missing_binaries(folder)
        if missing:
            result = FfmpegDirResult(
                active_dir=None,
                problem=(
                    f"FFmpeg folder {folder} has no executable "
                    f"{' or '.join(missing)}; using the system ffmpeg/ffprobe"
                ),
            )
        else:
            _state.applied_dir = str(folder)
            entries.insert(0, _state.applied_dir)
            result = FfmpegDirResult(active_dir=_state.applied_dir, problem=None)

    os.environ["PATH"] = os.pathsep.join(entries)
    return result


def tool_version(executable: str) -> str:
    """The build string from `<executable> -version`, e.g. "n9.0.2-29-g6dfaba896f"."""
    try:
        out = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown version"
    first = out.splitlines()[0] if out else ""
    # "ffmpeg version n9.0.2-29-g6dfaba896f-20261020 Copyright (c) ..."
    parts = first.split()
    if len(parts) >= 3 and parts[1] == "version":
        return parts[2]
    return first or "unknown version"


def describe_ffmpeg_tools() -> list[str]:
    """One line per binary: which file PATH resolves to and its build."""
    lines: list[str] = []
    for name in FFMPEG_BINARIES:
        path = shutil.which(name)
        if path is None:
            lines.append(f"{name}: not found")
        else:
            lines.append(f"{name}: {path} ({tool_version(path)})")
    return lines
