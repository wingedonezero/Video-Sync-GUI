# vsg_core/audio_processing/finisher.py
"""Run one edit plan end to end: probe → scan the source → encode → verify."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .encoder import encode, is_native_layout, output_layout, probe_source_format
from .samples import DelayBake, trimmed_end_samples
from .verify import ExpectedOutput, OutputCheck, check_output, scan_expected

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from vsg_core.io.runner import CommandRunner

    from .types import EditPlan, SourceFormat


class FinishError(RuntimeError):
    """A finisher stage could not run at all (unreadable source, or a strict
    decode that hit a damaged or lossy frame). The caller keeps the original."""


TAG_DELAY_MS = "VSG_DELAY_MS"
TAG_SILENCE_ADDED = "VSG_SILENCE_SAMPLES_ADDED"
TAG_TRIMMED_START = "VSG_SAMPLES_TRIMMED_START"
TAG_TRIMMED_END = "VSG_SAMPLES_TRIMMED_END"
TAG_SOURCE_CODEC = "VSG_SOURCE_CODEC"


def delay_tags(
    delay_ms: float, bake: DelayBake, plan: EditPlan, source_codec: str
) -> Callable[[ExpectedOutput], dict[str, str]]:
    """Tags for a plain delay bake; the end count needs the scanned source length."""

    def build(expected: ExpectedOutput) -> dict[str, str]:
        return {
            TAG_DELAY_MS: f"{delay_ms:.6f}",
            TAG_SILENCE_ADDED: str(bake.silence_added),
            TAG_TRIMMED_START: str(bake.trimmed_start),
            TAG_TRIMMED_END: str(trimmed_end_samples(plan, expected.source_samples)),
            TAG_SOURCE_CODEC: source_codec,
        }

    return build


@dataclass(frozen=True, slots=True)
class FinishResult:
    fmt: SourceFormat
    expected: ExpectedOutput
    tags: dict[str, str]
    check: OutputCheck | None  # None when the encode itself failed
    out: Path

    @property
    def ok(self) -> bool:
        return self.check is not None and self.check.ok

    @property
    def native_layout(self) -> bool:
        return is_native_layout(output_layout(self.fmt), self.fmt.channels)


def finish(
    source: Path,
    stream_index: int,
    plan: EditPlan,
    out: Path,
    tags: Callable[[ExpectedOutput], dict[str, str]],
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> FinishResult:
    """Produce ``out`` from ``source`` per ``plan`` and verify it. On failure the
    partial output is removed; the caller keeps the original track. A failed
    verification is returned in the result; a stage that cannot run at all
    raises FinishError."""
    try:
        fmt = probe_source_format(source, stream_index, runner, tool_paths)
    except RuntimeError as e:
        raise FinishError(f"cannot read the source format: {e}") from e
    try:
        expected = scan_expected(source, stream_index, fmt, plan, runner, tool_paths)
    except RuntimeError as e:
        raise FinishError(f"source does not decode cleanly: {e}") from e
    tag_values = tags(expected)
    if expected.output_samples == 0:
        # The delay/trim removes the whole track: never hand over an empty file.
        reason = (
            f"the plan leaves no audio (source has {expected.source_samples} "
            f"samples per channel)"
        )
        return FinishResult(fmt, expected, tag_values, OutputCheck(0, [reason]), out)
    if not encode(source, stream_index, fmt, plan, tag_values, out, runner, tool_paths):
        out.unlink(missing_ok=True)
        return FinishResult(fmt, expected, tag_values, None, out)
    try:
        check = check_output(out, expected, fmt, runner, tool_paths)
    except RuntimeError as e:
        out.unlink(missing_ok=True)
        raise FinishError(f"the FLAC output does not decode cleanly: {e}") from e
    if not check.ok:
        out.unlink(missing_ok=True)
    return FinishResult(fmt, expected, tag_values, check, out)
