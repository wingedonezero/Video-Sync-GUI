# vsg_core/subtitles/engines/tesseract.py
# -*- coding: utf-8 -*-
"""
Tesseract OCR engine integration using tesserocr.
Direct C++ API binding for better performance and control.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from PIL import Image


@dataclass
class WordInfo:
    """Information about a single recognized word."""
    text: str
    confidence: float  # 0-100


@dataclass
class OCRResult:
    """Result of OCR processing."""
    text: str
    confidence: float      # Average confidence 0-100
    words: List[WordInfo]


class TesseractEngine:
    """Tesseract OCR engine wrapper using tesserocr."""

    def __init__(self, config: dict):
        """
        Initialize Tesseract engine.

        Args:
            config: Configuration dictionary
        """
        self.lang = config.get('ocr_lang', 'eng')
        self.psm = config.get('ocr_tesseract_psm', 7)  # Single line mode
        self.oem = config.get('ocr_tesseract_oem', 1)  # LSTM mode
        self.whitelist = config.get('ocr_whitelist_chars', '')
        self.min_confidence = config.get('ocr_min_confidence', 0)

        # Initialize tesserocr API
        try:
            import tesserocr
            self.tesserocr = tesserocr
            self.api = None  # Will be created when needed

            # Try to detect tessdata path
            self.tessdata_path = self._find_tessdata_path()

        except ImportError:
            raise ImportError(
                "tesserocr not installed. Please install: pip install tesserocr\n"
                "Note: This requires Tesseract OCR to be installed on your system."
            )

    def _find_tessdata_path(self) -> Optional[str]:
        """
        Try to find the tessdata directory.
        Returns None to use tesserocr's default path detection.
        """
        import os
        import subprocess
        from pathlib import Path

        # First, check TESSDATA_PREFIX environment variable
        tessdata_prefix = os.environ.get('TESSDATA_PREFIX')
        if tessdata_prefix:
            tessdata = Path(tessdata_prefix)
            if tessdata.exists():
                return str(tessdata)

        # Try to get tessdata path from tesseract command
        try:
            result = subprocess.run(
                ['tesseract', '--print-parameters'],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Look for tessdata path in output
            for line in result.stdout.split('\n'):
                if 'tessdata' in line.lower() and 'prefix' in line.lower():
                    # Extract path from line
                    parts = line.split()
                    for part in parts:
                        if 'tessdata' in part:
                            p = Path(part)
                            if p.exists():
                                return str(p)
        except Exception:
            pass

        # Common installation paths to check
        common_paths = [
            '/usr/share/tesseract-ocr/4.00/tessdata',
            '/usr/share/tesseract-ocr/5/tessdata',
            '/usr/share/tessdata',
            '/usr/local/share/tessdata',
            '/opt/homebrew/share/tessdata',  # macOS Homebrew
            'C:\\Program Files\\Tesseract-OCR\\tessdata',  # Windows
            'C:\\Program Files (x86)\\Tesseract-OCR\\tessdata',
        ]

        for path in common_paths:
            p = Path(path)
            if p.exists() and (p / 'eng.traineddata').exists():
                return str(p)

        # Return None to use tesserocr's default detection
        return None

    def recognize(self, image: Image.Image) -> OCRResult:
        """
        Perform OCR on an image using HOCR output (like SubtitleEdit).

        HOCR provides structured output with word-level confidence scores,
        which is more reliable than plain text output.

        Args:
            image: PIL Image to recognize

        Returns:
            OCRResult with text and confidence
        """
        # Create API instance if needed
        if self.api is None:
            # Initialize API with or without explicit path
            if self.tessdata_path:
                self.api = self.tesserocr.PyTessBaseAPI(
                    path=self.tessdata_path,
                    lang=self.lang,
                    psm=self.psm,
                    oem=self.oem
                )
            else:
                # Let tesserocr auto-detect
                self.api = self.tesserocr.PyTessBaseAPI(
                    lang=self.lang,
                    psm=self.psm,
                    oem=self.oem
                )

            # Set character whitelist if specified
            if self.whitelist:
                self.api.SetVariable('tessedit_char_whitelist', self.whitelist)

        # Set the image
        self.api.SetImage(image)

        # Get HOCR output (like SubtitleEdit does)
        try:
            hocr = self.api.GetHOCRText(0)
            result = self._parse_hocr(hocr)
            return result
        except Exception:
            # Fallback to plain text if HOCR fails
            text = self.api.GetUTF8Text()

            # Get confidence scores
            try:
                # Get word-level confidence
                word_confidences = self.api.AllWordConfidences()

                # Get words
                words_text = text.split()

                # Create word info list
                words = []
                for i, word_text in enumerate(words_text):
                    if i < len(word_confidences):
                        confidence = word_confidences[i]
                    else:
                        confidence = 0

                    # Filter by minimum confidence
                    if confidence >= self.min_confidence:
                        words.append(WordInfo(text=word_text, confidence=confidence))

                # Calculate average confidence
                if word_confidences:
                    avg_confidence = sum(word_confidences) / len(word_confidences)
                else:
                    avg_confidence = 0.0

                # Reconstruct text from filtered words
                filtered_text = ' '.join(w.text for w in words)

            except Exception:
                # Fallback if confidence extraction fails
                words = [WordInfo(text=text.strip(), confidence=0.0)]
                avg_confidence = 0.0
                filtered_text = text.strip()

            return OCRResult(
                text=filtered_text.strip(),
                confidence=avg_confidence,
                words=words
            )

    def _parse_hocr(self, hocr: str) -> OCRResult:
        """
        Parse HOCR output to extract text and confidence scores.

        This matches SubtitleEdit's approach for better OCR quality.

        Args:
            hocr: HOCR HTML string from Tesseract

        Returns:
            OCRResult with parsed text and confidence
        """
        import re
        import html

        words = []
        all_text = []

        # Find all ocrx_word spans (word-level data)
        word_pattern = r'<span class=[\'"]ocrx_word[\'"][^>]*title="([^"]*)"[^>]*>([^<]*)</span>'

        for match in re.finditer(word_pattern, hocr):
            title = match.group(1)
            word_text = match.group(2).strip()

            if not word_text:
                continue

            # Decode HTML entities
            word_text = html.unescape(word_text)
            all_text.append(word_text)

            # Extract confidence from title attribute
            # Format: "bbox x1 y1 x2 y2; x_wconf 95"
            confidence = 0.0
            conf_match = re.search(r'x_wconf\s+(\d+)', title)
            if conf_match:
                confidence = float(conf_match.group(1))

            # Filter by minimum confidence
            if confidence >= self.min_confidence:
                words.append(WordInfo(text=word_text, confidence=confidence))

        # Combine text
        if words:
            text = ' '.join(w.text for w in words)
            confidences = [w.confidence for w in words]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        else:
            # No words passed confidence filter, but include all text
            text = ' '.join(all_text)
            avg_confidence = 0.0
            words = [WordInfo(text=text, confidence=0.0)] if text else []

        return OCRResult(
            text=text.strip(),
            confidence=avg_confidence,
            words=words
        )

    def __del__(self):
        """Clean up Tesseract API."""
        if hasattr(self, 'api') and self.api is not None:
            try:
                self.api.End()
            except Exception:
                pass
