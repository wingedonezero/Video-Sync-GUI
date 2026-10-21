# vsg_core/audio_processing/__init__.py
"""Sample-exact audio finishing: bake delays and trims into a verified FLAC.

An *edit plan* (takes of the decoded source + digital-silence inserts + an
optional end cap) is executed in one streaming ffmpeg pass into FLAC, then
proven against the source sample for sample. Used for every audio track the
app converts or corrects, so mkvmerge receives them with no delay at all.
"""

from .finisher import FinishResult, delay_tags, finish
from .samples import (
    DelayBake,
    bake_delay,
    end_cap_samples,
    expected_output_samples,
    ms_to_ns,
    ns_to_samples,
    plan_for_delay,
    trimmed_end_samples,
)
from .types import EditOp, EditPlan, Silence, SourceFormat, Take

__all__ = [
    "DelayBake",
    "EditOp",
    "EditPlan",
    "FinishResult",
    "Silence",
    "SourceFormat",
    "Take",
    "bake_delay",
    "delay_tags",
    "end_cap_samples",
    "expected_output_samples",
    "finish",
    "ms_to_ns",
    "ns_to_samples",
    "plan_for_delay",
    "trimmed_end_samples",
]
