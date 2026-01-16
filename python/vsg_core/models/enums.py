# vsg_core/models/enums.py
# -*- coding: utf-8 -*-
from enum import Enum

class TrackType(Enum):
    VIDEO = 'video'
    AUDIO = 'audio'
    SUBTITLES = 'subtitles'

# SourceRole enum is now removed. Sources will be identified by string keys like "Source 1".

class AnalysisMode(Enum):
    AUDIO = 'Audio Correlation'
    VIDEO = 'VideoDiff'

class SnapMode(Enum):
    PREVIOUS = 'previous'
    NEAREST = 'nearest'
