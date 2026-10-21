# vsg_core/audio_processing/types.py
"""Value types for the audio finisher: what to produce (an edit plan over the
source's decoded samples) and what the source is (its exact PCM format)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Take:
    """Copy source samples ``[start, end)``; ``end=None`` means to the end."""

    start: int
    end: int | None = None


@dataclass(frozen=True, slots=True)
class Silence:
    """Insert ``samples`` digital-zero samples (per channel)."""

    samples: int


EditOp = Take | Silence


@dataclass(frozen=True, slots=True)
class EditPlan:
    """Ordered output timeline built from the source, plus an optional cap on
    the total output length (the end trim).

    Takes must be ascending and non-overlapping so the plan can be executed and
    verified in one streaming pass over the source.
    """

    ops: tuple[EditOp, ...]
    max_output_samples: int | None = None

    def __post_init__(self) -> None:
        if not self.ops:
            raise ValueError("edit plan has no operations")
        last_end = 0
        open_ended = False
        for op in self.ops:
            if isinstance(op, Silence):
                if op.samples <= 0:
                    raise ValueError(f"silence must be positive, got {op.samples}")
                continue
            if open_ended:
                raise ValueError("a take follows an open-ended take")
            if op.start < last_end:
                raise ValueError(
                    f"takes must be ascending and non-overlapping "
                    f"(start {op.start} < previous end {last_end})"
                )
            if op.end is None:
                open_ended = True
            elif op.end <= op.start:
                raise ValueError(f"empty or inverted take {op.start}..{op.end}")
            else:
                last_end = op.end
        if self.max_output_samples is not None and self.max_output_samples <= 0:
            raise ValueError("end trim leaves no audio")

    @property
    def silence_samples(self) -> int:
        return sum(op.samples for op in self.ops if isinstance(op, Silence))


@dataclass(frozen=True, slots=True)
class SourceFormat:
    """Exact PCM format of one source audio stream as the decoder produces it."""

    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str | None  # None = the stream does not name one
    bits: int  # declared bits per sample (16, 20, 24)

    @property
    def flac_sample_fmt(self) -> str:
        return "s16" if self.bits <= 16 else "s32"
