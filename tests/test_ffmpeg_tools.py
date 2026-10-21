# tests/test_ffmpeg_tools.py
"""FFmpeg folder selection: PATH order, fallback, and version/where reporting.

Uses stub executables, so no real ffmpeg build is run.
"""

from __future__ import annotations

import os
import shutil
import stat
from typing import TYPE_CHECKING

import pytest

from vsg_core.system import ffmpeg_tools
from vsg_core.system.ffmpeg_tools import (
    apply_ffmpeg_dir,
    describe_ffmpeg_tools,
    missing_binaries,
    system_path,
    tool_version,
)

if TYPE_CHECKING:
    from pathlib import Path


def _stub(folder: Path, name: str, build: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"#!/bin/sh\necho '{name} version {build} Copyright (c) test'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def system_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH holding only a stub 'system' ffmpeg/ffprobe (plus sh for the stubs)."""
    sysdir = tmp_path / "system"
    _stub(sysdir, "ffmpeg", "7.1.5-system")
    _stub(sysdir, "ffprobe", "7.1.5-system")
    monkeypatch.setenv("PATH", os.pathsep.join([str(sysdir), "/usr/bin", "/bin"]))
    monkeypatch.setattr(ffmpeg_tools, "_state", ffmpeg_tools._PathState())
    return sysdir


def test_folder_goes_first_on_path(tmp_path: Path, system_bin: Path) -> None:
    tools = tmp_path / "Tools"
    _stub(tools, "ffmpeg", "n9.0.2-test")
    _stub(tools, "ffprobe", "n9.0.2-test")

    result = apply_ffmpeg_dir(str(tools))

    assert result.active_dir == str(tools.resolve()) and result.problem is None
    assert shutil.which("ffmpeg") == str(tools.resolve() / "ffmpeg")
    assert shutil.which("ffprobe") == str(tools.resolve() / "ffprobe")
    assert shutil.which("ffmpeg", path=system_path()) == str(system_bin / "ffmpeg")
    assert describe_ffmpeg_tools()[0].endswith("(n9.0.2-test)")


def test_empty_folder_setting_restores_the_system_tools(
    tmp_path: Path, system_bin: Path
) -> None:
    tools = tmp_path / "Tools"
    _stub(tools, "ffmpeg", "n9")
    _stub(tools, "ffprobe", "n9")
    apply_ffmpeg_dir(str(tools))
    apply_ffmpeg_dir(str(tools))  # re-applying doesn't stack entries

    assert os.environ["PATH"].split(os.pathsep).count(str(tools.resolve())) == 1
    result = apply_ffmpeg_dir("")

    assert result.active_dir is None and result.problem is None
    assert str(tools.resolve()) not in os.environ["PATH"].split(os.pathsep)
    assert shutil.which("ffmpeg") == str(system_bin / "ffmpeg")


def test_folder_missing_ffprobe_falls_back_to_system(
    tmp_path: Path, system_bin: Path
) -> None:
    tools = tmp_path / "Tools"
    _stub(tools, "ffmpeg", "n9")

    result = apply_ffmpeg_dir(str(tools))

    assert result.active_dir is None
    assert result.problem is not None and "ffprobe" in result.problem
    assert shutil.which("ffmpeg") == str(system_bin / "ffmpeg")
    assert missing_binaries(tools) == ["ffprobe"]


def test_non_executable_binary_counts_as_missing(tmp_path: Path) -> None:
    tools = tmp_path / "Tools"
    _stub(tools, "ffmpeg", "n9")
    _stub(tools, "ffprobe", "n9")
    (tools / "ffprobe").chmod(0o644)
    assert missing_binaries(tools) == ["ffprobe"]


def test_tool_version_reads_the_build_string(system_bin: Path) -> None:
    assert tool_version(str(system_bin / "ffmpeg")) == "7.1.5-system"
    assert tool_version(str(system_bin / "does-not-exist")) == "unknown version"
