"""Chapter keyframe snap: chapters on a keyframe's exact frame time are kept."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from lxml import etree as ET

from vsg_core.chapters.keyframes import KeyframeTimes
from vsg_core.chapters.process import _snap_chapter_times_inplace
from vsg_core.models import AppSettings

if TYPE_CHECKING:
    from vsg_core.models.types import SnapModeStr

MS = 1_000_000


class _Runner:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _log_message(self, line: str) -> None:
        self.lines.append(line)


def _chapters(*starts: str) -> ET._Element:
    atoms = "".join(
        f"<ChapterAtom><ChapterTimeStart>{s}</ChapterTimeStart></ChapterAtom>"
        for s in starts
    )
    return ET.fromstring(f"<Chapters><EditionEntry>{atoms}</EditionEntry></Chapters>")


def _snap(root: ET._Element, keyframes: KeyframeTimes, mode: SnapModeStr) -> list[str]:
    settings = AppSettings(snap_mode=mode, snap_threshold_ms=125)
    runner = _Runner()
    _snap_chapter_times_inplace(root, keyframes, settings, runner, {}, "")  # type: ignore[arg-type]
    return [n.text for n in root.iter("ChapterTimeStart")]


# Elf 17: the disc's chapters are exact 24000/1001 frame times; the MKV
# stores those keyframes rounded half up to whole ms.
ELF_KEYFRAMES = KeyframeTimes(
    times_ns=[0, 437_000 * MS, 437_604 * MS, 801_759 * MS, 1_125_333 * MS],
    unit_ns=MS,
)


@pytest.mark.parametrize("mode", ["nearest", "previous"])
def test_exact_frame_times_of_keyframes_are_kept(mode: SnapModeStr) -> None:
    root = _chapters(
        "00:00:00.000000000",
        "00:07:17.603833333",
        "00:13:21.759291667",
        "00:18:45.332541667",
    )
    assert _snap(root, ELF_KEYFRAMES, mode) == [
        "00:00:00.000000000",
        "00:07:17.603833333",
        "00:13:21.759291667",
        "00:18:45.332541667",
    ]


def test_chapter_off_a_keyframe_still_snaps() -> None:
    root = _chapters("00:07:17.560000000")
    assert _snap(root, ELF_KEYFRAMES, "nearest") == ["00:07:17.604000000"]


def test_half_unit_rounds_up_like_the_stored_timestamp() -> None:
    # Frame 12 at 24000/1001 is 500.5 ms; mkvmerge stores it as 501.
    keyframes = KeyframeTimes(times_ns=[0, 501 * MS], unit_ns=MS)
    root = _chapters("00:00:00.500500000")
    assert _snap(root, keyframes, "previous") == ["00:00:00.500500000"]


def test_unknown_unit_needs_an_exact_match() -> None:
    keyframes = KeyframeTimes(times_ns=[0, 437_604 * MS], unit_ns=None)
    root = _chapters("00:07:17.603833333")
    assert _snap(root, keyframes, "nearest") == ["00:07:17.604000000"]
