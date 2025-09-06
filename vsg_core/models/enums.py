# -*- coding: utf-8 -*-
from enum import Enum

class TrackType(Enum):
    VIDEO = 'video'
    AUDIO = 'audio'
    SUBTITLES = 'subtitles'

class SourceRole(Enum):
    REF = 'REF'
    SEC = 'SEC'
    TER = 'TER'

class AnalysisMode(Enum):
    AUDIO = 'Audio Correlation'
    VIDEO = 'VideoDiff'

class SnapMode(Enum):
    PREVIOUS = 'previous'
    NEAREST = 'nearest'
