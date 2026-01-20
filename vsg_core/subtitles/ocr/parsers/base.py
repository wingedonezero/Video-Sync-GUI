# vsg_core/subtitles/ocr/parsers/base.py
# -*- coding: utf-8 -*-
"""
Base classes and dataclasses for subtitle image parsing.

Provides common interfaces and data structures used by all subtitle parsers
(VobSub, PGS, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class SubtitleImage:
    """
    Represents a single subtitle image extracted from an image-based format.

    Attributes:
        index: Sequential index of this subtitle (0-based)
        start_ms: Start time in milliseconds
        end_ms: End time in milliseconds (may be 0 if unknown)
        image: The subtitle bitmap as a numpy array (RGBA or grayscale)
        x: X coordinate of top-left corner (for positioning)
        y: Y coordinate of top-left corner (for positioning)
        width: Image width in pixels
        height: Image height in pixels
        frame_width: Width of the video frame (for calculating relative position)
        frame_height: Height of the video frame (for calculating relative position)
        is_forced: Whether this is a forced subtitle
        palette: Color palette if applicable (for indexed color images)
    """
    index: int
    start_ms: int
    end_ms: int
    image: np.ndarray
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    frame_width: int = 720  # Default DVD resolution
    frame_height: int = 480
    is_forced: bool = False
    palette: Optional[List[Tuple[int, int, int, int]]] = None

    def __post_init__(self):
        """Set width/height from image if not provided."""
        if self.image is not None and len(self.image.shape) >= 2:
            if self.height == 0:
                self.height = self.image.shape[0]
            if self.width == 0:
                self.width = self.image.shape[1]

    @property
    def start_time(self) -> str:
        """Return start time as HH:MM:SS.mmm string."""
        return self._ms_to_timestamp(self.start_ms)

    @property
    def end_time(self) -> str:
        """Return end time as HH:MM:SS.mmm string."""
        return self._ms_to_timestamp(self.end_ms)

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        return self.end_ms - self.start_ms

    @property
    def y_position_percent(self) -> float:
        """
        Return Y position as percentage of frame height.

        Used to determine if subtitle is at bottom, top, or middle.
        0% = top of frame, 100% = bottom of frame
        """
        if self.frame_height == 0:
            return 100.0  # Assume bottom if unknown
        # Use center of subtitle for position calculation
        center_y = self.y + (self.height / 2)
        return (center_y / self.frame_height) * 100

    @property
    def x_position_percent(self) -> float:
        """Return X position as percentage of frame width (center of subtitle)."""
        if self.frame_width == 0:
            return 50.0  # Assume centered if unknown
        center_x = self.x + (self.width / 2)
        return (center_x / self.frame_width) * 100

    def is_bottom_positioned(self, threshold_percent: float = 75.0) -> bool:
        """
        Check if subtitle is positioned at the bottom of the frame.

        Args:
            threshold_percent: Y position threshold (default 75% = bottom 25% of frame)

        Returns:
            True if subtitle center is below the threshold
        """
        return self.y_position_percent >= threshold_percent

    def is_top_positioned(self, threshold_percent: float = 25.0) -> bool:
        """
        Check if subtitle is positioned at the top of the frame.

        Args:
            threshold_percent: Y position threshold (default 25% = top 25% of frame)

        Returns:
            True if subtitle center is above the threshold
        """
        return self.y_position_percent <= threshold_percent

    @staticmethod
    def _ms_to_timestamp(ms: int) -> str:
        """Convert milliseconds to HH:MM:SS.mmm format."""
        if ms < 0:
            ms = 0
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        milliseconds = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


@dataclass
class ParseResult:
    """
    Result of parsing a subtitle file.

    Attributes:
        subtitles: List of extracted subtitle images
        format_info: Information about the source format
        errors: Any errors encountered during parsing
        warnings: Any warnings generated during parsing
    """
    subtitles: List[SubtitleImage] = field(default_factory=list)
    format_info: dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True if parsing succeeded (no errors and has subtitles)."""
        return len(self.errors) == 0 and len(self.subtitles) > 0

    @property
    def subtitle_count(self) -> int:
        """Return number of subtitles extracted."""
        return len(self.subtitles)


class SubtitleImageParser(ABC):
    """
    Abstract base class for subtitle image parsers.

    Subclasses must implement:
        - parse(): Extract subtitle images from a file
        - can_parse(): Check if a file can be parsed by this parser
    """

    @abstractmethod
    def parse(self, file_path: Path, work_dir: Optional[Path] = None) -> ParseResult:
        """
        Parse a subtitle file and extract images.

        Args:
            file_path: Path to the subtitle file (.idx for VobSub, .sup for PGS)
            work_dir: Optional working directory for temporary files

        Returns:
            ParseResult containing extracted subtitle images and metadata
        """
        pass

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """
        Check if this parser can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if this parser can parse the file
        """
        pass

    @staticmethod
    def detect_parser(file_path: Path) -> Optional['SubtitleImageParser']:
        """
        Detect the appropriate parser for a file based on extension.

        Args:
            file_path: Path to the subtitle file

        Returns:
            Appropriate parser instance, or None if no parser matches
        """
        from .vobsub import VobSubParser
        # Future: from .pgs import PGSParser

        suffix = file_path.suffix.lower()

        if suffix in ('.idx', '.sub'):
            return VobSubParser()
        # Future: elif suffix == '.sup':
        #     return PGSParser()

        return None
