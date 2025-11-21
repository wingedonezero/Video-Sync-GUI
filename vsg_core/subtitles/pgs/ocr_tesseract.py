# vsg_core/subtitles/pgs/ocr_tesseract.py
# -*- coding: utf-8 -*-
"""
Tesseract OCR integration for PGS subtitles.
Based on SubtitleEdit's TesseractRunner implementation.
"""
from __future__ import annotations
import subprocess
import tempfile
import os
import re
from pathlib import Path
from typing import Optional
from PIL import Image
import html


def find_tesseract() -> Optional[str]:
    """
    Find tesseract executable in system.

    Returns:
        Path to tesseract or None if not found
    """
    # Try common locations
    common_paths = [
        'tesseract',  # In PATH
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
        'C:\\Program Files\\Tesseract-OCR\\tesseract.exe',
        'C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe',
    ]

    for path in common_paths:
        try:
            result = subprocess.run(
                [path, '--version'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None


def run_tesseract_ocr(
    image: Image.Image,
    lang: str = 'eng',
    psm: int = 6,
    oem: int = 3,
    tesseract_path: Optional[str] = None,
    config: Optional[str] = None
) -> str:
    """
    Run Tesseract OCR on image.

    Args:
        image: PIL Image to OCR
        lang: Language code (default 'eng' for English)
        psm: Page Segmentation Mode
            0 = Orientation and script detection (OSD) only
            1 = Automatic page segmentation with OSD
            3 = Fully automatic page segmentation (default)
            4 = Assume a single column of text
            6 = Assume a single uniform block of text (best for subtitles)
            7 = Treat the image as a single text line
            8 = Treat the image as a single word
            11 = Sparse text. Find as much text as possible
            13 = Raw line. Treat as single text line, bypass Tesseract specific hacks
        oem: OCR Engine Mode
            0 = Legacy engine only
            1 = Neural nets LSTM engine only
            2 = Legacy + LSTM engines
            3 = Default, based on what's available
        tesseract_path: Path to tesseract executable (auto-detect if None)
        config: Additional tesseract config string

    Returns:
        Extracted text string (empty string if OCR fails)
    """
    # Find tesseract (handle empty string as None)
    if not tesseract_path:
        tesseract_path = find_tesseract()

    if not tesseract_path:
        raise FileNotFoundError("Tesseract not found. Please install Tesseract OCR.")

    # Save image to temporary file
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_img:
        image.save(tmp_img.name, 'PNG')
        input_file = tmp_img.name

    try:
        # Create output filename (without extension)
        output_base = tempfile.mktemp()

        # Build command
        cmd = [
            tesseract_path,
            input_file,
            output_base,
            '-l', lang,
            '--psm', str(psm),
            '--oem', str(oem),
            'hocr'  # Output in hOCR format (HTML with positioning)
        ]

        # Add additional config if provided
        if config:
            cmd.extend(['-c', config])

        # Run tesseract
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Check if tesseract failed
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            print(f"[Tesseract] ERROR: Command failed with exit code {result.returncode}")
            print(f"[Tesseract] Command: {' '.join(cmd)}")
            print(f"[Tesseract] Error output: {error_msg}")
            return ""

        # Read hOCR output
        hocr_file = output_base + '.hocr'
        if os.path.exists(hocr_file):
            with open(hocr_file, 'r', encoding='utf-8') as f:
                hocr_content = f.read()

            # Parse hOCR to extract text
            text = parse_hocr(hocr_content)

            # Clean up output file
            try:
                os.unlink(hocr_file)
            except:
                pass

            return text
        else:
            # hOCR file not created, possibly error
            print(f"[Tesseract] ERROR: hOCR file not created at {hocr_file}")
            print(f"[Tesseract] Stdout: {result.stdout}")
            print(f"[Tesseract] Stderr: {result.stderr}")
            return ""

    except subprocess.TimeoutExpired:
        print(f"[Tesseract] ERROR: Command timed out after 30 seconds")
        return ""
    except Exception as e:
        # Log error but don't crash
        print(f"[Tesseract] ERROR: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return ""
    finally:
        # Clean up input file
        try:
            os.unlink(input_file)
        except:
            pass


def parse_hocr(hocr_html: str) -> str:
    """
    Parse Tesseract hOCR output to extract text.

    hOCR format has structure:
        <span class='ocr_line' ...>
            <span class='ocrx_word' ...>word1</span>
            <span class='ocrx_word' ...>word2</span>
        </span>

    Args:
        hocr_html: hOCR HTML string from Tesseract

    Returns:
        Extracted and cleaned text
    """
    lines = []

    # Find all ocr_line spans
    line_pattern = re.compile(r"<span class='ocr_line'[^>]*>(.*?)</span>", re.DOTALL)
    word_pattern = re.compile(r"<span class='ocrx_word'[^>]*>(.*?)</span>", re.DOTALL)

    for line_match in line_pattern.finditer(hocr_html):
        line_content = line_match.group(1)
        words = []

        # Extract words from line
        for word_match in word_pattern.finditer(line_content):
            word = word_match.group(1)

            # Decode HTML entities
            word = html.unescape(word)

            # Handle italic tags (Tesseract uses <em>)
            word = word.replace('<em>', '<i>').replace('</em>', '</i>')

            # Remove other HTML tags
            word = re.sub(r'<(?!/?i>)[^>]*>', '', word)

            if word.strip():
                words.append(word)

        if words:
            lines.append(' '.join(words))

    return '\n'.join(lines)


def postprocess_text(text: str) -> str:
    """
    Post-process OCR text to fix common errors.

    Args:
        text: Raw OCR text

    Returns:
        Cleaned text
    """
    # Remove spurious italic tags
    text = text.replace('<i> </i>', ' ')
    text = text.replace('<i></i>', '')
    text = re.sub(r'<i>\s*</i>', '', text)

    # Fix italic tags around punctuation
    text = text.replace('<i>-</i>', '-')
    text = text.replace('<i>—</i>', '—')
    text = text.replace('<i>...</i>', '...')
    text = text.replace('<i>.</i>', '.')
    text = text.replace('<i>,</i>', ',')

    # Normalize whitespace
    text = re.sub(r' +', ' ', text)  # Multiple spaces to single
    text = re.sub(r' \n', '\n', text)  # Space before newline
    text = re.sub(r'\n ', '\n', text)  # Space after newline

    # Fix common OCR errors (optional - can be expanded)
    # l/I confusion at start of sentences
    text = re.sub(r'\bl\b', 'I', text)  # Standalone 'l' -> 'I'

    # Trim
    text = text.strip()

    return text


def run_ocr_with_postprocessing(
    image: Image.Image,
    lang: str = 'eng',
    psm: int = 6,
    tesseract_path: Optional[str] = None
) -> str:
    """
    Run OCR with automatic post-processing.

    Args:
        image: PIL Image
        lang: Language code
        psm: Page segmentation mode
        tesseract_path: Path to tesseract executable

    Returns:
        Cleaned OCR text
    """
    raw_text = run_tesseract_ocr(image, lang, psm, tesseract_path=tesseract_path)
    return postprocess_text(raw_text)
