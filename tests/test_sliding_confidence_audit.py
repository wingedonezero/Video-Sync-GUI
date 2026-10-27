# tests/test_sliding_confidence_audit.py
"""Timeline-integrity lines of the sliding-window confidence audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.io.runner import CommandRunner
from vsg_core.models.settings import AppSettings
from vsg_core.orchestrator.steps.context import Context
from vsg_core.postprocess.auditors.sliding_confidence import SlidingConfidenceAuditor

if TYPE_CHECKING:
    from pathlib import Path


def _audit(tmp_path: Path, **timeline: object) -> tuple[list[str], int]:
    ctx = Context(
        settings=AppSettings(),
        tool_paths={},
        log=lambda _m: None,
        progress=lambda _p: None,
        output_dir=str(tmp_path),
        temp_dir=tmp_path,
        and_merge=True,
    )
    details: dict = {
        "timeline_correction_applied": False,
        "timeline_src_ok": True,
        "timeline_tgt_ok": True,
        "num_positions": 9,
        "positions_pts_based": 9,
        "timeline_src_missing_slots": 0,
        "timeline_tgt_missing_slots": 0,
    }
    details.update(timeline)
    lines: list[str] = []
    auditor = SlidingConfidenceAuditor(ctx, CommandRunner(AppSettings(), lines.append))
    auditor._render_timeline("Source 3", details)
    return lines, len(auditor.issues)


def test_gap_that_needed_no_correction_is_info(tmp_path: Path) -> None:
    # Dungeon 14: Source 3's last frame stamped late; all 9 positions measured
    # from real timestamps, none corrected.
    lines, issues = _audit(
        tmp_path,
        timeline_src_ok=False,
        timeline_src_missing_slots=2,
        timeline_src_first_gap_s=1440.112,
    )
    assert issues == 0
    text = "\n".join(lines)
    assert "2 missing frame slot(s) at ~1440.112s" in text
    assert "UNVERIFIED" not in text and "unavailable" not in text


def test_unavailable_timestamps_still_warn(tmp_path: Path) -> None:
    lines, issues = _audit(tmp_path, positions_pts_based=6)
    assert issues == 1
    assert any("unavailable for 3/9" in line for line in lines)
