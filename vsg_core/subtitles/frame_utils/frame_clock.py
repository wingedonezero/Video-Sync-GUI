# vsg_core/subtitles/frame_utils/frame_clock.py
"""
Exact CFR frame grid.

A subtitle timestamp is either on a frame or it is not — and to decide that
without fuzzing we need to know *exactly* where the frames are. Container muxers
store CFR video-frame presentation times rounded to the millisecond:

    frame_ms(n) = round(n * 1000 / fps) = round(n * 1000 * den / num)

computed with EXACT integer arithmetic (round-half-up). Doing it in float —
``int(n * (1000 / fps) + 0.5)`` — is wrong by 1ms at every frame whose exact
time lands on a half-millisecond (e.g. frame 12 of 24000/1001 is 500.5ms: the
float form yields 500, the container stores 501). That 1ms error at ~4% of
frames is exactly what the old surgical-rounding tolerance band-aid was masking.

``FrameClock`` is only valid for true CFR-from-0 sources (progressive
Blu-ray / UHD / encodes). MPEG-2 DVD and VFR content have no such grid — callers
detect that and pass ``None`` instead, falling back to plain rounding.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameClock:
    """Exact millisecond frame grid for a CFR-from-0 stream at ``num/den`` fps."""

    num: int  # fps numerator   (e.g. 24000)
    den: int  # fps denominator (e.g. 1001)

    def frame_ms(self, n: int) -> int:
        """Exact presentation time (ms) of frame ``n`` (round-half-up).

        Integer arithmetic only — this is the real container grid, not an
        approximation of it.
        """
        return (2 * n * 1000 * self.den + self.num) // (2 * self.num)

    def frame_of(self, time_ms: float) -> int:
        """Index of the first real frame at or after ``time_ms``.

        This is the frame a timestamp renders against: a player shows a subtitle
        on a frame whose presentation time is >= the start, and an exclusive end
        clears on this same "first frame at or after" boundary.
        """
        # Integer estimate, then walk to the exact boundary (1-2 steps). The grid
        # is monotonic, so this always converges.
        n = int(time_ms * self.num / (1000 * self.den))
        while n > 0 and self.frame_ms(n) >= time_ms:
            n -= 1
        while self.frame_ms(n) < time_ms:
            n += 1
        return n

    def is_on_frame(self, time_ms: float) -> bool:
        """True iff ``time_ms`` sits exactly on a real frame (integer-ms match).

        PGS/OCR timestamps inherited from frame-locked bitmaps satisfy this;
        mid-frame VobSub values and native centisecond ASS values do not.
        """
        return self.frame_ms(self.frame_of(time_ms)) == round(time_ms)

    @property
    def frame_duration_ms(self) -> float:
        """Nominal frame period — for logging/reporting only, never grid math."""
        return 1000.0 * self.den / self.num


@dataclass(frozen=True, slots=True)
class FrameShift:
    """A pure whole-frame shift on an exact grid.

    A subtitle that sits exactly on frame ``k`` is moved to
    ``clock.frame_ms(k + frames)`` — landing exactly on the target frame with
    zero float slop. Values that are not on a frame (mid-frame VobSub, native
    ASS, or anything carrying a sub-frame component) are not snapped; they take
    the flat millisecond delay instead.

    The caller constructs a ``FrameShift`` only when the move is genuinely a
    whole-frame offset on a shared CFR-from-0 grid (frame-matched source, no
    sub-frame global shift, same PTS origin). Otherwise it passes ``None`` and
    every event takes the flat delay, exactly as before.
    """

    clock: FrameClock
    frames: int

    def shifted_ms(self, time_ms: float, flat_delay_ms: float) -> float:
        """Exact-snap ``time_ms`` when it is on a frame, else apply the flat delay."""
        if self.clock.is_on_frame(time_ms):
            k = self.clock.frame_of(time_ms)
            return float(self.clock.frame_ms(k + self.frames))
        return time_ms + flat_delay_ms
