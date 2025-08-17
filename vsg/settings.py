from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ChapterSettings:
    enabled: bool = True
    source: Optional[str] = None  # path or None to use ref
    snap_mode: str = "off"  # off|starts|starts_and_ends
    snap_tolerance_ms: int = 250
    rename_normalized: bool = False

@dataclass
class AppSettings:
    analysis_mode: str = "audio"  # audio|video
    log_merge_summary: bool = True
    chapters: ChapterSettings = field(default_factory=ChapterSettings)
