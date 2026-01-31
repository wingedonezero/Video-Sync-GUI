# vsg_core/subtitles/ocr/report.py
# -*- coding: utf-8 -*-
"""
OCR Report Generation

Generates detailed reports about OCR results:
    - Unknown words with context and suggestions
    - Low confidence lines flagged for review
    - Applied fixes summary
    - Overall accuracy metrics

Reports are saved as JSON for machine processing and can be
summarized for inclusion in the main job report.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import enchant
    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False


@dataclass
class UnknownWord:
    """
    Information about an unknown word found during OCR.

    Attributes:
        word: The unrecognized word
        context: Surrounding text (for manual review)
        timestamp: Subtitle timestamp where word appears
        confidence: OCR confidence for this word
        occurrences: Number of times this word appears
        suggestions: Dictionary suggestions for correction
    """
    word: str
    context: str = ""
    timestamp: str = ""
    confidence: float = 0.0
    occurrences: int = 1
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class LowConfidenceLine:
    """
    A subtitle line with low OCR confidence.

    Flagged for potential manual review.
    """
    text: str
    timestamp: str
    confidence: float
    subtitle_index: int
    potential_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class SubtitleOCRResult:
    """OCR result for a single subtitle."""
    index: int
    timestamp_start: str
    timestamp_end: str
    text: str
    confidence: float
    was_modified: bool = False
    fixes_applied: Dict[str, int] = field(default_factory=dict)
    unknown_words: List[str] = field(default_factory=list)
    position_x: int = 0
    position_y: int = 0
    is_positioned: bool = False  # True if not at default bottom

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class OCRReport:
    """
    Complete OCR report for a subtitle file.

    Contains all metrics, unknown words, and flagged issues.
    """
    # Metadata
    source_file: str = ""
    output_file: str = ""
    timestamp: str = ""
    language: str = "eng"
    duration_seconds: float = 0.0

    # Overall stats
    total_subtitles: int = 0
    successful_subtitles: int = 0
    failed_subtitles: int = 0
    average_confidence: float = 0.0
    min_confidence: float = 100.0
    max_confidence: float = 0.0

    # Per-subtitle results
    subtitles: List[SubtitleOCRResult] = field(default_factory=list)

    # Aggregated unknown words (deduplicated)
    unknown_words: List[UnknownWord] = field(default_factory=list)

    # Lines flagged for review
    low_confidence_lines: List[LowConfidenceLine] = field(default_factory=list)

    # Fix statistics
    total_fixes_applied: int = 0
    fixes_by_type: Dict[str, int] = field(default_factory=dict)

    # Position statistics
    positioned_subtitles: int = 0  # Non-bottom positioned
    top_positioned: int = 0
    middle_positioned: int = 0

    def add_subtitle_result(self, result: SubtitleOCRResult):
        """Add a subtitle result and update statistics."""
        self.subtitles.append(result)
        self.total_subtitles += 1

        if result.text.strip():
            self.successful_subtitles += 1
        else:
            self.failed_subtitles += 1

        # Update confidence stats
        if result.confidence > 0:
            self.min_confidence = min(self.min_confidence, result.confidence)
            self.max_confidence = max(self.max_confidence, result.confidence)

        # Update fixes
        for fix_type, count in result.fixes_applied.items():
            self.fixes_by_type[fix_type] = self.fixes_by_type.get(fix_type, 0) + count
            self.total_fixes_applied += count

        # Update position stats
        if result.is_positioned:
            self.positioned_subtitles += 1

    def add_unknown_word(
        self,
        word: str,
        context: str = "",
        timestamp: str = "",
        confidence: float = 0.0
    ):
        """Add or update an unknown word entry."""
        # Check if word already exists
        for existing in self.unknown_words:
            if existing.word == word:
                existing.occurrences += 1
                return

        # Add new entry
        entry = UnknownWord(
            word=word,
            context=context,
            timestamp=timestamp,
            confidence=confidence,
            suggestions=self._get_suggestions(word),
        )
        self.unknown_words.append(entry)

    def add_low_confidence_line(
        self,
        text: str,
        timestamp: str,
        confidence: float,
        subtitle_index: int,
        potential_issues: Optional[List[str]] = None
    ):
        """Flag a line for manual review."""
        self.low_confidence_lines.append(LowConfidenceLine(
            text=text,
            timestamp=timestamp,
            confidence=confidence,
            subtitle_index=subtitle_index,
            potential_issues=potential_issues or [],
        ))

    def finalize(self):
        """Calculate final statistics."""
        if self.successful_subtitles > 0:
            total_conf = sum(s.confidence for s in self.subtitles if s.confidence > 0)
            conf_count = sum(1 for s in self.subtitles if s.confidence > 0)
            if conf_count > 0:
                self.average_confidence = total_conf / conf_count

        # Sort unknown words by occurrence (most frequent first)
        self.unknown_words.sort(key=lambda w: -w.occurrences)

        # Sort low confidence lines by confidence (lowest first)
        self.low_confidence_lines.sort(key=lambda l: l.confidence)

    def _get_suggestions(self, word: str) -> List[str]:
        """Get dictionary suggestions for a word."""
        if not ENCHANT_AVAILABLE:
            return []
        try:
            d = enchant.Dict("en_US")
            return d.suggest(word)[:5]  # Top 5 suggestions
        except Exception:
            return []

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'metadata': {
                'source_file': self.source_file,
                'output_file': self.output_file,
                'timestamp': self.timestamp,
                'language': self.language,
                'duration_seconds': self.duration_seconds,
            },
            'statistics': {
                'total_subtitles': self.total_subtitles,
                'successful_subtitles': self.successful_subtitles,
                'failed_subtitles': self.failed_subtitles,
                'average_confidence': round(self.average_confidence, 2),
                'min_confidence': round(self.min_confidence, 2),
                'max_confidence': round(self.max_confidence, 2),
                'total_fixes_applied': self.total_fixes_applied,
                'positioned_subtitles': self.positioned_subtitles,
            },
            'fixes_by_type': self.fixes_by_type,
            'unknown_words': [w.to_dict() for w in self.unknown_words],
            'low_confidence_lines': [l.to_dict() for l in self.low_confidence_lines],
            'subtitles': [s.to_dict() for s in self.subtitles],
        }

    def to_summary(self) -> dict:
        """
        Generate a summary for inclusion in the main job report.

        Contains key metrics without full subtitle details.
        """
        return {
            'total_subtitles': self.total_subtitles,
            'successful': self.successful_subtitles,
            'failed': self.failed_subtitles,
            'average_confidence': round(self.average_confidence, 2),
            'total_fixes': self.total_fixes_applied,
            'unknown_word_count': len(self.unknown_words),
            'low_confidence_count': len(self.low_confidence_lines),
            'positioned_subtitles': self.positioned_subtitles,
            'top_unknown_words': [w.word for w in self.unknown_words[:10]],
        }

    def save(self, output_path: Path):
        """Save report to JSON file."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> 'OCRReport':
        """Load report from JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        report = cls()
        report.source_file = data.get('metadata', {}).get('source_file', '')
        report.output_file = data.get('metadata', {}).get('output_file', '')
        report.timestamp = data.get('metadata', {}).get('timestamp', '')
        report.language = data.get('metadata', {}).get('language', 'eng')

        stats = data.get('statistics', {})
        report.total_subtitles = stats.get('total_subtitles', 0)
        report.successful_subtitles = stats.get('successful_subtitles', 0)
        report.failed_subtitles = stats.get('failed_subtitles', 0)
        report.average_confidence = stats.get('average_confidence', 0.0)
        report.min_confidence = stats.get('min_confidence', 100.0)
        report.max_confidence = stats.get('max_confidence', 0.0)
        report.total_fixes_applied = stats.get('total_fixes_applied', 0)
        report.positioned_subtitles = stats.get('positioned_subtitles', 0)

        report.fixes_by_type = data.get('fixes_by_type', {})

        for w_data in data.get('unknown_words', []):
            report.unknown_words.append(UnknownWord(**w_data))

        for l_data in data.get('low_confidence_lines', []):
            report.low_confidence_lines.append(LowConfidenceLine(**l_data))

        for s_data in data.get('subtitles', []):
            report.subtitles.append(SubtitleOCRResult(**s_data))

        return report


def create_report(
    source_file: str,
    output_file: str,
    language: str = 'eng'
) -> OCRReport:
    """
    Create a new OCR report.

    Args:
        source_file: Path to source VobSub/PGS file
        output_file: Path to output ASS/SRT file
        language: OCR language code

    Returns:
        New OCRReport instance
    """
    return OCRReport(
        source_file=source_file,
        output_file=output_file,
        timestamp=datetime.now().isoformat(),
        language=language,
    )
