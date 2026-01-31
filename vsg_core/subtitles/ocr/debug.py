# vsg_core/subtitles/ocr/debug.py
"""
OCR Debug Output

Creates organized debug output for analyzing OCR issues:
- Preprocessed images saved by issue type
- Simple text files with timecodes and OCR output
- Easy to share and analyze specific problems

Folder structure:
    {report_name}_debug/
        summary.txt                 # Quick overview
        raw_ocr.txt                 # Complete raw OCR output for all subtitles
        all_subtitles/
            all_subtitles.txt       # All subtitles with OCR text
            sub_0001.png            # All preprocessed images for verification
            sub_0002.png
            ...
        unknown_words/
            unknown_words.txt       # Timecodes, text, unknown words
            sub_0001.png            # Images for subtitles with unknown words
            ...
        fixes_applied/
            fixes_applied.txt       # Timecodes, original, fixed text
            sub_0010.png
            ...
        low_confidence/
            low_confidence.txt      # Timecodes, text, confidence scores
            sub_0020.png
            ...
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class DebugSubtitle:
    """Debug info for a single subtitle."""

    index: int
    start_time: str  # "HH:MM:SS.mmm"
    end_time: str
    raw_text: str  # Text after post-processing
    confidence: float
    image: np.ndarray | None = None

    # Raw OCR output (before any fixes)
    raw_ocr_text: str | None = None

    # Issue tracking
    unknown_words: list[str] = field(default_factory=list)
    fixes_applied: dict[str, str] = field(
        default_factory=dict
    )  # fix_name -> description
    original_text: str | None = None  # Before fixes (same as raw_ocr_text when set)


class OCRDebugger:
    """
    Collects and outputs debug information for OCR analysis.

    Usage:
        debugger = OCRDebugger(logs_dir, "Source_2_track_1_3", enabled=True)

        # During OCR processing:
        debugger.add_subtitle(index, start, end, text, confidence, image)
        debugger.add_unknown_word(index, word)
        debugger.add_fix(index, fix_name, description, original_text)

        # After processing:
        debugger.save()
    """

    def __init__(
        self,
        logs_dir: Path,
        base_name: str,
        timestamp: str,
        enabled: bool = False,
        low_confidence_threshold: float = 60.0,
    ):
        """
        Initialize debugger.

        Args:
            logs_dir: Base directory for logs
            base_name: Base name for output (e.g., "Source_2_track_1_3")
            timestamp: Timestamp string (e.g., "20260120_115514")
            enabled: Whether debug output is enabled
            low_confidence_threshold: Threshold for flagging low confidence
        """
        self.logs_dir = Path(logs_dir)
        self.base_name = base_name
        self.timestamp = timestamp
        self.enabled = enabled
        self.low_confidence_threshold = low_confidence_threshold

        # Storage
        self.subtitles: dict[int, DebugSubtitle] = {}

        # Track which indices have issues
        self.unknown_word_indices: set[int] = set()
        self.fix_indices: set[int] = set()
        self.low_confidence_indices: set[int] = set()

    @property
    def debug_dir(self) -> Path:
        """Get the debug output directory path."""
        return self.logs_dir / f"{self.base_name}_ocr_debug_{self.timestamp}"

    def add_subtitle(
        self,
        index: int,
        start_time: str,
        end_time: str,
        text: str,
        confidence: float,
        image: np.ndarray | None = None,
        raw_ocr_text: str | None = None,
    ):
        """Add a subtitle for potential debug output.

        Args:
            index: Subtitle index
            start_time: Start timestamp
            end_time: End timestamp
            text: Text after post-processing
            confidence: OCR confidence score
            image: Preprocessed image (optional)
            raw_ocr_text: Raw OCR output before any fixes (optional)
        """
        if not self.enabled:
            return

        self.subtitles[index] = DebugSubtitle(
            index=index,
            start_time=start_time,
            end_time=end_time,
            raw_text=text,
            confidence=confidence,
            image=image.copy() if image is not None else None,
            raw_ocr_text=raw_ocr_text,
        )

        # Track low confidence
        if confidence < self.low_confidence_threshold:
            self.low_confidence_indices.add(index)

    def add_unknown_word(self, index: int, word: str):
        """Record an unknown word for a subtitle."""
        if not self.enabled:
            return

        if index in self.subtitles:
            self.subtitles[index].unknown_words.append(word)
            self.unknown_word_indices.add(index)

    def add_fix(
        self,
        index: int,
        fix_name: str,
        description: str,
        original_text: str | None = None,
    ):
        """Record a fix applied to a subtitle."""
        if not self.enabled:
            return

        if index in self.subtitles:
            self.subtitles[index].fixes_applied[fix_name] = description
            if original_text:
                self.subtitles[index].original_text = original_text
            self.fix_indices.add(index)

    def save(self):
        """Save all debug output to disk."""
        if not self.enabled:
            return

        if not self.subtitles:
            return

        # Create main debug directory
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        # Save summary
        self._save_summary()

        # Always save raw OCR output (this is the main debugging data)
        self._save_raw_ocr()

        # Always save all subtitles with images for verification
        self._save_all_subtitles()

        # Save each issue category
        if self.unknown_word_indices:
            self._save_unknown_words()

        if self.fix_indices:
            self._save_fixes()

        if self.low_confidence_indices:
            self._save_low_confidence()

    def _save_summary(self):
        """Save overall summary file."""
        summary_path = self.debug_dir / "summary.txt"

        lines = [
            "OCR Debug Summary",
            "=" * 50,
            f"Base name: {self.base_name}",
            f"Timestamp: {self.timestamp}",
            f"Total subtitles: {len(self.subtitles)}",
            "",
            "Files:",
            "  raw_ocr.txt - Complete raw OCR output (before any fixes)",
            "",
            "Issues found:",
            f"  Unknown words: {len(self.unknown_word_indices)} subtitles",
            f"  Fixes applied: {len(self.fix_indices)} subtitles",
            f"  Low confidence: {len(self.low_confidence_indices)} subtitles",
            "",
            "Folders:",
            f"  all_subtitles/ - {len(self.subtitles)} images (all subtitles for verification)",
        ]

        if self.unknown_word_indices:
            lines.append(f"  unknown_words/ - {len(self.unknown_word_indices)} images")
        if self.fix_indices:
            lines.append(f"  fixes_applied/ - {len(self.fix_indices)} images")
        if self.low_confidence_indices:
            lines.append(
                f"  low_confidence/ - {len(self.low_confidence_indices)} images"
            )

        summary_path.write_text("\n".join(lines), encoding="utf-8")

    def _save_raw_ocr(self):
        """Save complete raw OCR output for all subtitles.

        This file contains the unedited OCR text for every subtitle,
        useful for tuning dictionary rules and understanding OCR behavior.
        """
        raw_ocr_path = self.debug_dir / "raw_ocr.txt"

        lines = [
            "Raw OCR Output (Unedited)",
            "=" * 50,
            "",
            "This file contains the raw OCR output before any post-processing fixes.",
            "Use this to see exactly what the OCR engine produced and tune your",
            "dictionary rules accordingly.",
            "",
            "Format: [index] timecode | confidence% | raw text",
            "=" * 50,
            "",
        ]

        # Sort by index
        for idx in sorted(self.subtitles.keys()):
            sub = self.subtitles[idx]

            # Use raw_ocr_text if available, otherwise use original_text, otherwise raw_text
            raw_text = sub.raw_ocr_text or sub.original_text or sub.raw_text

            # Format: [0001] 00:01:23.456 | 85.2% | The raw OCR text here
            # Handle multiline by replacing newlines
            text_display = raw_text.replace("\n", "\\n").replace("\\N", "\\N")

            lines.append(
                f"[{sub.index:04d}] {sub.start_time} -> {sub.end_time} | "
                f"{sub.confidence:5.1f}% | {text_display}"
            )

        # Add a separator and detailed view
        lines.extend(
            [
                "",
                "",
                "=" * 50,
                "Detailed View (with line breaks preserved)",
                "=" * 50,
                "",
            ]
        )

        for idx in sorted(self.subtitles.keys()):
            sub = self.subtitles[idx]
            raw_text = sub.raw_ocr_text or sub.original_text or sub.raw_text
            final_text = sub.raw_text

            lines.extend(
                [
                    "-" * 50,
                    f"[{sub.index:04d}] {sub.start_time} -> {sub.end_time}",
                    f"Confidence: {sub.confidence:.1f}%",
                    "",
                    "Raw OCR:",
                    f"  {raw_text.replace(chr(10), chr(10) + '  ')}",
                ]
            )

            # Show final text if different
            if raw_text != final_text:
                lines.extend(
                    [
                        "",
                        "After fixes:",
                        f"  {final_text.replace(chr(10), chr(10) + '  ')}",
                    ]
                )

            lines.append("")

        raw_ocr_path.write_text("\n".join(lines), encoding="utf-8")

    def _save_all_subtitles(self):
        """Save all subtitle images for verification.

        This folder contains every subtitle image so you can manually verify
        the raw OCR output against the actual images.
        """
        folder = self.debug_dir / "all_subtitles"
        folder.mkdir(parents=True, exist_ok=True)

        lines = [
            "All Subtitles - Raw Verification",
            "=" * 50,
            "",
            "All subtitle images and their OCR output for manual verification.",
            "Compare the images against the raw_ocr.txt output to check accuracy.",
            "",
        ]

        for idx in sorted(self.subtitles.keys()):
            sub = self.subtitles[idx]

            # Use raw_ocr_text if available, otherwise original_text, otherwise raw_text
            raw_text = sub.raw_ocr_text or sub.original_text or sub.raw_text
            final_text = sub.raw_text

            lines.extend(
                [
                    "-" * 50,
                    f"Index: {sub.index}",
                    f"Time: {sub.start_time} -> {sub.end_time}",
                    f"Confidence: {sub.confidence:.1f}%",
                    f"Image: sub_{sub.index:04d}.png",
                    "",
                    "Raw OCR:",
                    f"  {raw_text.replace(chr(10), chr(10) + '  ')}",
                ]
            )

            # Show final text if different
            if raw_text != final_text:
                lines.extend(
                    [
                        "",
                        "After fixes:",
                        f"  {final_text.replace(chr(10), chr(10) + '  ')}",
                    ]
                )

            lines.append("")

            # Save image
            if sub.image is not None:
                self._save_image(sub.image, folder / f"sub_{sub.index:04d}.png")

        (folder / "all_subtitles.txt").write_text("\n".join(lines), encoding="utf-8")

    def _save_unknown_words(self):
        """Save unknown words debug output."""
        folder = self.debug_dir / "unknown_words"
        folder.mkdir(parents=True, exist_ok=True)

        lines = [
            "Unknown Words Debug",
            "=" * 50,
            "",
            "Subtitles containing words not in dictionary.",
            "Check if these are actual errors or valid words (names, romaji, etc.)",
            "",
        ]

        for idx in sorted(self.unknown_word_indices):
            sub = self.subtitles.get(idx)
            if not sub:
                continue

            lines.extend(
                [
                    "-" * 50,
                    f"Index: {sub.index}",
                    f"Time: {sub.start_time} -> {sub.end_time}",
                    f"Confidence: {sub.confidence:.1f}%",
                    f"Image: sub_{sub.index:04d}.png",
                    "",
                    "OCR Text:",
                    f"  {sub.raw_text.replace(chr(10), chr(10) + '  ')}",
                    "",
                    f"Unknown words: {', '.join(sub.unknown_words)}",
                    "",
                ]
            )

            # Save image
            if sub.image is not None:
                self._save_image(sub.image, folder / f"sub_{sub.index:04d}.png")

        (folder / "unknown_words.txt").write_text("\n".join(lines), encoding="utf-8")

    def _save_fixes(self):
        """Save fixes applied debug output."""
        folder = self.debug_dir / "fixes_applied"
        folder.mkdir(parents=True, exist_ok=True)

        lines = [
            "Fixes Applied Debug",
            "=" * 50,
            "",
            "Subtitles where post-processing fixes were applied.",
            "Review to see if fixes are correct or if OCR needs improvement.",
            "",
        ]

        for idx in sorted(self.fix_indices):
            sub = self.subtitles.get(idx)
            if not sub:
                continue

            lines.extend(
                [
                    "-" * 50,
                    f"Index: {sub.index}",
                    f"Time: {sub.start_time} -> {sub.end_time}",
                    f"Confidence: {sub.confidence:.1f}%",
                    f"Image: sub_{sub.index:04d}.png",
                    "",
                ]
            )

            if sub.original_text:
                lines.extend(
                    [
                        "Original OCR:",
                        f"  {sub.original_text.replace(chr(10), chr(10) + '  ')}",
                        "",
                    ]
                )

            lines.extend(
                [
                    "After fixes:",
                    f"  {sub.raw_text.replace(chr(10), chr(10) + '  ')}",
                    "",
                    "Fixes applied:",
                ]
            )

            for fix_name, description in sub.fixes_applied.items():
                lines.append(f"  - {fix_name}: {description}")

            lines.append("")

            # Save image
            if sub.image is not None:
                self._save_image(sub.image, folder / f"sub_{sub.index:04d}.png")

        (folder / "fixes_applied.txt").write_text("\n".join(lines), encoding="utf-8")

    def _save_low_confidence(self):
        """Save low confidence debug output."""
        folder = self.debug_dir / "low_confidence"
        folder.mkdir(parents=True, exist_ok=True)

        lines = [
            "Low Confidence Debug",
            "=" * 50,
            "",
            f"Subtitles with confidence below {self.low_confidence_threshold}%.",
            "These likely have OCR errors that need manual review.",
            "",
        ]

        # Sort by confidence (lowest first)
        sorted_indices = sorted(
            self.low_confidence_indices,
            key=lambda i: self.subtitles[i].confidence if i in self.subtitles else 100,
        )

        for idx in sorted_indices:
            sub = self.subtitles.get(idx)
            if not sub:
                continue

            lines.extend(
                [
                    "-" * 50,
                    f"Index: {sub.index}",
                    f"Time: {sub.start_time} -> {sub.end_time}",
                    f"Confidence: {sub.confidence:.1f}%",
                    f"Image: sub_{sub.index:04d}.png",
                    "",
                    "OCR Text:",
                    f"  {sub.raw_text.replace(chr(10), chr(10) + '  ')}",
                    "",
                ]
            )

            # Save image
            if sub.image is not None:
                self._save_image(sub.image, folder / f"sub_{sub.index:04d}.png")

        (folder / "low_confidence.txt").write_text("\n".join(lines), encoding="utf-8")

    def _save_image(self, image: np.ndarray, path: Path):
        """Save a numpy image array to disk."""
        try:
            if len(image.shape) == 2:
                # Grayscale
                img = Image.fromarray(image, mode="L")
            elif image.shape[2] == 4:
                # RGBA
                img = Image.fromarray(image, mode="RGBA")
            else:
                # RGB
                img = Image.fromarray(image, mode="RGB")
            img.save(path)
        except Exception:
            pass  # Don't fail debug on image save errors


def create_debugger(
    logs_dir: Path, base_name: str, timestamp: str, settings_dict: dict
) -> OCRDebugger:
    """
    Create a debugger from settings.

    Args:
        logs_dir: Logs directory
        base_name: Base name for output files
        timestamp: Timestamp string
        settings_dict: Application settings

    Returns:
        Configured OCRDebugger
    """
    return OCRDebugger(
        logs_dir=logs_dir,
        base_name=base_name,
        timestamp=timestamp,
        enabled=settings_dict.get("ocr_debug_output", False),
        low_confidence_threshold=settings_dict.get(
            "ocr_low_confidence_threshold", 60.0
        ),
    )
