"""Black-bar audit helpers and the rescale's trigger for it."""

from __future__ import annotations

from vsg_core.postprocess.auditors.subtitle_bars import (
    _bar_strips,
    _frames,
    _rate,
    _runs,
    _ts,
)
from vsg_core.subtitles.track_processor import _picture_area


def test_trigger_needs_a_whole_pixel_of_bars() -> None:
    # Elf 17: 4:3 crop onto a pillarboxed Blu-ray
    assert _picture_area({"offset_x": 240.0, "offset_y": 0.0}, 1920, 1080) == (
        240.0,
        0.0,
        1680.0,
        1080.0,
    )
    # Samurai Harem: 853x480 rounding gives a 0.13 px "bar" - nothing to check
    assert _picture_area({"offset_x": 0.0, "offset_y": 0.133}, 720, 480) is None
    # Same shape, or a rescale that never ran
    assert _picture_area({"offset_x": 0.0, "offset_y": 0.0}, 1920, 1080) is None
    assert _picture_area(None, 1920, 1080) is None


def test_bar_strips_follow_the_picture_axis() -> None:
    side = _bar_strips(240, 0, 1680, 1080, 1920, 1080)
    assert side.columns == ((0, 240), (1680, 1920)) and side.rows == ()
    letterbox = _bar_strips(0, 135, 1440, 945, 1440, 1080)
    assert letterbox.rows == ((0, 135), (945, 1080)) and letterbox.columns == ()


def test_frames_recut_a_stream_on_frame_boundaries() -> None:
    chunks = [b"abc", b"defg", b"hi", b"jk"]
    assert list(_frames(chunks, 4)) == [b"abcd", b"efgh"]  # trailing "ijk" dropped


def test_runs_group_consecutive_frames() -> None:
    assert _runs([3, 4, 5, 9, 11, 12]) == [(3, 5), (9, 9), (11, 12)]


def test_rate_and_timestamps() -> None:
    assert _rate({"r_frame_rate": "24000/1001"}) == "24000/1001"
    assert _rate({"r_frame_rate": "0/0", "avg_frame_rate": "25/1"}) == "25/1"
    assert _rate({}) is None
    assert _ts(62.48) == "1:02.48"
