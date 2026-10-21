# vsg_core/audio_processing/samples.py
"""Exact sample arithmetic for baking a delay into the audio itself.

Everything is integer nanoseconds and integer samples: a delay becomes the
nearest whole sample (ties away from zero, like C ``llround``), so the audio
lands within half a sample of the measured delay and the leftover is known
exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import EditPlan, Silence, Take

NS_PER_S = 1_000_000_000


def ms_to_ns(ms: float) -> int:
    """Delay in ms (as analysis reports it, e.g. -10.834789) to integer ns."""
    return round(ms * 1_000_000)


def ns_to_samples(ns: int, rate: int) -> int:
    """Nearest whole sample to ``ns`` at ``rate``; ties round away from zero."""
    q, r = divmod(abs(ns) * rate, NS_PER_S)
    if 2 * r >= NS_PER_S:
        q += 1
    return q if ns >= 0 else -q


@dataclass(frozen=True, slots=True)
class DelayBake:
    """How a delay is realised in samples."""

    delay_ns: int
    rate: int
    samples: int  # signed: >0 silence added at the start, <0 samples cut

    @property
    def silence_added(self) -> int:
        return max(self.samples, 0)

    @property
    def trimmed_start(self) -> int:
        return max(-self.samples, 0)

    @property
    def residual_ns(self) -> float:
        """Realised minus requested delay, in ns (|value| <= half a sample)."""
        return self.samples * NS_PER_S / self.rate - self.delay_ns


def bake_delay(delay_ns: int, rate: int) -> DelayBake:
    return DelayBake(
        delay_ns=delay_ns, rate=rate, samples=ns_to_samples(delay_ns, rate)
    )


def end_cap_samples(video_end_ns: int, rate: int) -> int:
    """Output samples that fit before the video end (nearest whole sample)."""
    if video_end_ns <= 0:
        raise ValueError(f"video end must be positive, got {video_end_ns} ns")
    return ns_to_samples(video_end_ns, rate)


def plan_for_delay(bake: DelayBake, max_output_samples: int | None = None) -> EditPlan:
    """Edit plan for a plain track: silence or a start cut, then everything else."""
    if bake.samples > 0:
        ops: tuple[Silence | Take, ...] = (Silence(bake.samples), Take(0))
    else:
        ops = (Take(bake.trimmed_start),)
    return EditPlan(ops=ops, max_output_samples=max_output_samples)


def expected_output_samples(plan: EditPlan, source_samples: int) -> int:
    """Length of the planned output for a source of ``source_samples``."""
    total = 0
    for op in plan.ops:
        if isinstance(op, Silence):
            total += op.samples
        else:
            end = source_samples if op.end is None else min(op.end, source_samples)
            total += max(end - op.start, 0)
    if plan.max_output_samples is not None:
        total = min(total, plan.max_output_samples)
    return total


def trimmed_end_samples(plan: EditPlan, source_samples: int) -> int:
    """Samples the end cap removes beyond what the plan itself keeps."""
    uncapped = expected_output_samples(
        EditPlan(ops=plan.ops, max_output_samples=None), source_samples
    )
    return uncapped - expected_output_samples(plan, source_samples)
