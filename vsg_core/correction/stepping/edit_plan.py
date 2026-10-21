# vsg_core/correction/stepping/edit_plan.py
"""Turn a stepping EDL into sample-exact audio edits.

The same edits drive the mono QA track and the final per-track encode (the
audio finisher), so the QA check tests exactly what ships.

Rules (the old assembler's, except at the start):
- The starting delay (first segment's delay + ``start_offset_ms``) is always
  applied to the nearest sample: digital silence if positive, a cut if
  negative. The old assembler skipped a positive start of 10 ms or less.
- At each later segment the delay change is applied: an increase of more than
  10 ms inserts that much silence, any decrease cuts that much from the
  segment's start, and an increase of 10 ms or less is ignored (cluster
  jitter, not a real step) and reported.
- Segment boundaries are the EDL's source times rounded to the nearest sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from vsg_core.audio_processing import Silence, Take, ms_to_ns, ns_to_samples

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from vsg_core.audio_processing import EditOp

    from .types import AudioSegment

# Delay increases up to this size between segments are not applied.
SMALL_STEP_MS = 10.0


@dataclass(frozen=True, slots=True)
class IgnoredStep:
    """A delay increase too small to apply (see SMALL_STEP_MS)."""

    at_s: float  # segment start in the source
    step_ms: float


@dataclass(frozen=True, slots=True)
class SteppingEdits:
    ops: tuple[EditOp, ...]
    start_delay_ms: float  # first segment's delay + start offset
    start_samples: int  # applied start: >0 silence added, <0 samples cut
    ignored_steps: tuple[IgnoredStep, ...]


def edl_to_edits(
    edl: Sequence[AudioSegment],
    rate: int,
    start_offset_ms: float,
    log: Callable[[str], None],
) -> SteppingEdits:
    """Edits over the source's samples at ``rate``. Raises ValueError when a
    cut is longer than the segment it belongs to."""
    if not edl:
        raise ValueError("empty EDL")
    ops: list[EditOp] = []
    ignored: list[IgnoredStep] = []

    start_delay_ms = edl[0].delay_raw + start_offset_ms
    start = ns_to_samples(ms_to_ns(start_delay_ms), rate)
    if start > 0:
        ops.append(Silence(start))
    log(
        f"    Start: delay {start_delay_ms:+.6f} ms -> "
        + (f"{start} samples of silence" if start >= 0 else f"cut {-start} samples")
    )

    for i, seg in enumerate(edl):
        cut = max(-start, 0) if i == 0 else 0
        if i > 0:
            step_ms = seg.delay_raw - edl[i - 1].delay_raw
            if step_ms > SMALL_STEP_MS:
                n = round(step_ms / 1000.0 * rate)
                ops.append(Silence(n))
                log(
                    f"    At {seg.start_s:.3f}s: insert {step_ms:.3f}ms "
                    f"({n} samples) silence"
                )
            elif step_ms < 0:
                cut = round(-step_ms / 1000.0 * rate)
                log(
                    f"    At {seg.start_s:.3f}s: remove {-step_ms:.3f}ms "
                    f"({cut} samples) audio"
                )
            elif step_ms > 0:
                ignored.append(IgnoredStep(seg.start_s, step_ms))
                log(
                    f"    At {seg.start_s:.3f}s: +{step_ms:.3f}ms step ignored "
                    f"(<= {SMALL_STEP_MS:g} ms)"
                )
        begin = round(seg.start_s * rate) + cut
        end = round(edl[i + 1].start_s * rate) if i + 1 < len(edl) else None
        if end is not None and end <= begin:
            raise ValueError(
                f"segment at {seg.start_s:.3f}s is shorter than the "
                f"{cut}-sample cut at its start"
            )
        ops.append(Take(begin, end))

    return SteppingEdits(tuple(ops), start_delay_ms, start, tuple(ignored))


def render_edits(pcm: np.ndarray, channels: int, ops: Sequence[EditOp]) -> np.ndarray:
    """Apply ``ops`` to interleaved ``pcm`` in memory (for the small QA track)."""
    frames = len(pcm) // channels
    pieces: list[np.ndarray] = []
    for op in ops:
        if isinstance(op, Silence):
            pieces.append(np.zeros(op.samples * channels, dtype=pcm.dtype))
            continue
        a = min(op.start, frames)
        b = frames if op.end is None else min(op.end, frames)
        pieces.append(pcm[a * channels : b * channels])
    return np.concatenate(pieces) if pieces else pcm[:0]
