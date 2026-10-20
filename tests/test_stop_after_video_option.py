"""The "stop all tracks when the video ends" option maps to mkvmerge's global
--stop-after-video-ends, emitted once, before any input file."""

from __future__ import annotations

from vsg_core.models.jobs import Delays, MergePlan
from vsg_core.models.settings import AppSettings
from vsg_core.mux.options_builder import MkvmergeOptionsBuilder


def _tokens(enabled: bool) -> list[str]:
    settings = AppSettings(trim_audio_to_video_duration=enabled)
    plan = MergePlan(items=[], delays=Delays())
    return MkvmergeOptionsBuilder().build(plan, settings)


def test_option_on_adds_global_flag_once() -> None:
    tokens = _tokens(True)
    assert tokens.count("--stop-after-video-ends") == 1
    # global option: must come before the first input file group
    if "(" in tokens:
        assert tokens.index("--stop-after-video-ends") < tokens.index("(")


def test_option_off_leaves_tokens_untouched() -> None:
    assert "--stop-after-video-ends" not in _tokens(False)
