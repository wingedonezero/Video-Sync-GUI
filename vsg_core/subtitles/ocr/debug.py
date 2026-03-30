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


@dataclass(slots=True)
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

        # VLM region data (annotated images, region info)
        self.annotated_images: dict[int, np.ndarray] = {}
        self.region_data: dict[int, list[dict]] = {}  # index -> [{line_id, bbox, text}]

        # Pixel verification results
        # status: "clean" | "empty" | "paddle_empty" | "outside" | "bleed"
        self.verification_results: dict[int, dict] = {}  # index -> {status, details}
        self.verification_counts: dict[str, int] = {
            "clean": 0,
            "empty": 0,
            "paddle_empty": 0,
            "outside": 0,
            "bleed": 0,
        }

        # Region grouping results
        self.grouping_data: dict[int, list[dict]] = {}
        self.grouping_counts: dict[str, int] = {"bot": 0, "top": 0, "pos": 0}

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

    def add_annotated_image(self, index: int, image: np.ndarray) -> None:
        """Store an annotated image (with region boxes drawn) for debug output."""
        if not self.enabled:
            return
        self.annotated_images[index] = image

    def add_region_data(
        self,
        index: int,
        regions: list[dict],
    ) -> None:
        """Store line detection data for a subtitle.

        Args:
            index: Subtitle index
            regions: List of dicts with line_id, bbox, text
        """
        if not self.enabled:
            return
        self.region_data[index] = regions

    def add_verification_result(
        self,
        index: int,
        status: str,
        details: dict | None = None,
    ) -> None:
        """Store pixel verification result for a subtitle.

        Args:
            index: Subtitle index
            status: One of "clean", "empty", "paddle_empty", "outside", "bleed"
            details: Optional dict with extra info (e.g., outside_pixels, max_pixel)
        """
        if not self.enabled:
            return
        self.verification_results[index] = {
            "status": status,
            **(details or {}),
        }
        if status in self.verification_counts:
            self.verification_counts[status] += 1

    def add_grouping_data(
        self,
        index: int,
        regions: list[dict],
    ) -> None:
        """Store region grouping results for a subtitle.

        Args:
            index: Subtitle index
            regions: List of dicts with zone, line_count, line_ids,
                     bbox, confidence, reasons
        """
        if not self.enabled:
            return
        self.grouping_data[index] = regions
        for reg in regions:
            zone = reg.get("zone", "pos")
            if zone in self.grouping_counts:
                self.grouping_counts[zone] += 1

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

        # Save annotated images (backend line bboxes drawn on raw image)
        if self.annotated_images:
            self._save_annotated_images()

        # Save pixel verification results
        if self.verification_results:
            self._save_verification()

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
        if self.annotated_images:
            lines.append(
                f"  annotated/ - {len(self.annotated_images)} images (line bboxes)"
            )
        if self.verification_results:
            vc = self.verification_counts
            lines.append(f"  verification/ - pixel verification results")
            for status in ("clean", "empty", "paddle_empty", "outside", "bleed"):
                if vc.get(status, 0) > 0:
                    lines.append(f"    {status}: {vc[status]}")
            # Count issues (non-clean, non-empty)
            issues = sum(vc.get(s, 0) for s in ("paddle_empty", "outside", "bleed"))
            if issues:
                lines.append(f"    paddle_empty/ - {vc.get('paddle_empty', 0)} images")
                lines.append(f"    outside/ - {vc.get('outside', 0)} images")
                lines.append(f"    bleed/ - {vc.get('bleed', 0)} images")

        if self.grouping_data:
            gc = self.grouping_counts
            g_total = sum(gc.values())
            lines.append("")
            lines.append("Region grouping:")
            lines.append(f"  Total regions: {g_total}")
            for zone in ("bot", "top", "pos"):
                if gc.get(zone, 0) > 0:
                    lines.append(f"    {zone}: {gc[zone]}")
            multi = sum(
                1
                for gd_list in self.grouping_data.values()
                for gd in gd_list
                if gd.get("line_count", 0) >= 2
            )
            if multi:
                lines.append(f"  Multi-line regions (2+): {multi}")

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

    def _save_annotated_images(self):
        """Save annotated images with region boxes drawn."""
        folder = self.debug_dir / "annotated"
        folder.mkdir(parents=True, exist_ok=True)

        for idx in sorted(self.annotated_images.keys()):
            img = self.annotated_images[idx]
            self._save_image(img, folder / f"sub_{idx:04d}.png")

    def _save_verification(self):
        """Save pixel verification results organized by status category."""
        base = self.debug_dir / "verification"
        base.mkdir(parents=True, exist_ok=True)

        vc = self.verification_counts
        total = sum(vc.values())

        def pct(n: int) -> str:
            return f"{n / max(total, 1) * 100:.2f}%"

        # Summary file
        summary_lines = [
            "Pixel Verification Summary",
            "=" * 50,
            "",
            f"Total subtitles verified: {total}",
            "",
            f"  {'Status':<15} {'Count':>6}  {'%':>8}",
            f"  {'-' * 15} {'-' * 6}  {'-' * 8}",
        ]
        for status in ("clean", "empty", "paddle_empty", "outside", "bleed"):
            c = vc.get(status, 0)
            summary_lines.append(f"  {status:<15} {c:>6}  {pct(c):>8}")

        summary_lines.extend(
            [
                "",
                "Status definitions:",
                "  clean        — paddle lines cover all visible pixels",
                "  empty        — no pixels at all (blank sub / timing marker)",
                "  paddle_empty — paddle returned nothing but pixels exist",
                "  outside      — pixels found outside all paddle bboxes",
                "  bleed        — outside pixels touch a paddle bbox edge (character overflow)",
            ]
        )
        (base / "verification_summary.txt").write_text(
            "\n".join(summary_lines), encoding="utf-8"
        )

        # Save issue categories with images
        for status in ("paddle_empty", "outside", "bleed"):
            indices = [
                idx
                for idx, vr in self.verification_results.items()
                if vr["status"] == status
            ]
            if not indices:
                continue

            folder = base / status
            folder.mkdir(parents=True, exist_ok=True)

            detail_lines = [
                f"Verification: {status}",
                "=" * 50,
                f"Count: {len(indices)}",
                "",
            ]

            for idx in sorted(indices):
                sub = self.subtitles.get(idx)
                vr = self.verification_results[idx]

                detail_lines.append("-" * 50)
                detail_lines.append(f"Index: {idx}")
                if sub:
                    detail_lines.append(f"Time: {sub.start_time} -> {sub.end_time}")
                    detail_lines.append(f"Text: {sub.raw_text}")

                # Show verification details
                for k, v in vr.items():
                    if k != "status":
                        detail_lines.append(f"  {k}: {v}")
                detail_lines.append("")

                # Save raw image
                if sub and sub.image is not None:
                    self._save_image(sub.image, folder / f"sub_{idx:04d}.png")
                # Save annotated image (with paddle bboxes drawn)
                if idx in self.annotated_images:
                    self._save_image(
                        self.annotated_images[idx],
                        folder / f"sub_{idx:04d}_annotated.png",
                    )

            (folder / f"{status}.txt").write_text(
                "\n".join(detail_lines), encoding="utf-8"
            )

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
