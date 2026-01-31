# vsg_core/models/media.py
from dataclasses import dataclass
from pathlib import Path

from .enums import TrackType


@dataclass(frozen=True)
class StreamProps:
    codec_id: str
    lang: str = 'und'
    name: str = ''

@dataclass(frozen=True)
class Track:
    source: str  # Was SourceRole, now a string like "Source 1"
    id: int      # mkvmerge track id (per container)
    type: TrackType
    props: StreamProps

@dataclass(frozen=True)
class Attachment:
    id: int
    file_name: str
    out_path: Path | None = None
