# -*- coding: utf-8 -*-
from dataclasses import dataclass
from pathlib import Path
from .enums import TrackType, SourceRole

@dataclass(frozen=True)
class StreamProps:
    codec_id: str
    lang: str = 'und'
    name: str = ''

@dataclass(frozen=True)
class Track:
    source: SourceRole            # REF/SEC/TER
    id: int                       # mkvmerge track id (per container)
    type: TrackType               # video | audio | subtitles
    props: StreamProps

@dataclass(frozen=True)
class Attachment:
    id: int
    file_name: str
    out_path: Path | None = None
