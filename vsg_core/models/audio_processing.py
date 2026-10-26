# vsg_core/models/audio_processing.py
"""Per-track outcome of the Audio Processing step, shared with the auditors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vsg_core.audio_processing.passthrough import PassthroughCut

AudioRouteStr = Literal["flac", "untouched", "corrected", "passthrough"]


@dataclass(frozen=True, slots=True)
class AudioProcessingResult:
    """What happened to one audio track before the mux.

    ``route``:
      - ``flac``: converted / re-encoded to FLAC with its delay baked in
        (mkvmerge gets 0); ``ok`` False means it fell back to untouched.
      - ``passthrough``: kept in its codec; the app cut whole units (samples
        for PCM / Opus) at the start and end, mkvmerge gets ``cut.sync_ms``.
        ``ok`` False means the cut was refused and it fell back to untouched.
      - ``untouched``: extracted file muxed as-is with mkvmerge ``--sync``.
      - ``corrected``: produced by stepping / PAL / linear correction.
    """

    label: str
    route: AudioRouteStr
    codec_id: str
    ok: bool
    detail: str
    delay_raw_ms: float | None = None
    mkvmerge_delay_ms: int | None = None  # what --sync would have used
    samples_trimmed_start: int = 0
    silence_samples_added: int = 0
    samples_trimmed_end: int = 0
    residual_ns: float = 0.0
    output_samples: int = 0
    sample_rate: int = 0
    channel_layout: str = ""
    native_layout: bool = True
    problems: tuple[str, ...] = ()
    cut: PassthroughCut | None = None  # passthrough route only
    # The original track kept beside a stepping-corrected one (not counted
    # among the plan's audio tracks).
    preserved_original: bool = False
