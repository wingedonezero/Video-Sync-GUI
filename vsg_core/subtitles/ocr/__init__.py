# vsg_core/subtitles/ocr/__init__.py
# -*- coding: utf-8 -*-
"""
Integrated OCR System for VOB and PGS Subtitles

This module provides a complete OCR pipeline for converting image-based subtitles
(VobSub .sub/.idx and PGS .sup) to text-based formats (ASS/SRT).

Components:
    - parsers: Extract subtitle images and metadata from VOB/PGS files
    - preprocessing: Adaptive image preprocessing for optimal OCR accuracy
    - engine: Tesseract OCR wrapper with confidence tracking
    - postprocess: Pattern fixes and dictionary validation
    - report: OCR quality reporting (unknown words, confidence, fixes)
    - output: ASS/SRT generation with position support

The pipeline is designed to:
    1. Parse image-based subtitle formats, extracting timing and position
    2. Preprocess images adaptively based on quality analysis
    3. Run OCR with confidence tracking per line
    4. Apply pattern-based and dictionary-validated fixes
    5. Generate output with position tags for non-bottom subtitles
    6. Report unknown words and low-confidence results
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner

from .engine import OCREngine
from .pipeline import OCRPipeline
from .report import OCRReport, UnknownWord, LowConfidenceLine

__all__ = [
    'OCREngine',
    'OCRPipeline',
    'OCRReport',
    'UnknownWord',
    'LowConfidenceLine',
    'run_ocr',
    'check_ocr_available',
]


def run_ocr(
    subtitle_path: str,
    lang: str,
    runner: 'CommandRunner',
    tool_paths: dict,
    config: dict,
    work_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    track_id: int = 0,
) -> Optional[str]:
    """
    Runs OCR on an image-based subtitle file (VobSub IDX/SUB or PGS SUP).

    Uses the integrated OCR pipeline with:
        - Native VobSub parsing
        - Adaptive preprocessing
        - Tesseract OCR with confidence tracking
        - Post-processing and pattern fixes
        - ASS output with position support

    Args:
        subtitle_path: Path to the subtitle file (.idx for VobSub)
        lang: The 3-letter language code for OCR (e.g., 'eng')
        runner: The CommandRunner instance for logging
        tool_paths: A dictionary of tool paths (unused by new OCR)
        config: The application's configuration dictionary
        work_dir: Working directory for temp files
        logs_dir: Directory for OCR reports
        track_id: Track ID for organizing work files

    Returns:
        The path to the generated subtitle file (ASS or SRT), or None on failure.
    """
    sub_path = Path(subtitle_path)

    # Determine input type
    suffix = sub_path.suffix.lower()
    if suffix == '.idx':
        # VobSub - use .idx path
        input_path = sub_path
    elif suffix == '.sub':
        # VobSub - convert to .idx path
        input_path = sub_path.with_suffix('.idx')
        if not input_path.exists():
            runner._log_message(f"[OCR] ERROR: IDX file not found: {input_path}")
            return None
    elif suffix == '.sup':
        # PGS - not yet supported
        runner._log_message(f"[OCR] WARNING: PGS (.sup) support not yet implemented. Skipping {sub_path.name}")
        return None
    else:
        runner._log_message(f"[OCR] Skipping {sub_path.name}: Unsupported format.")
        return None

    # Check if OCR is enabled
    if not config.get('ocr_enabled', True):
        runner._log_message(f"[OCR] Skipping {sub_path.name}: OCR is disabled.")
        return None

    # Determine output format and path
    output_format = config.get('ocr_output_format', 'ass')
    output_suffix = '.ass' if output_format == 'ass' else '.srt'
    output_path = sub_path.with_suffix(output_suffix)

    # Set up directories
    if work_dir is None:
        work_dir = sub_path.parent / 'ocr_work'
    if logs_dir is None:
        logs_dir = sub_path.parent

    runner._log_message(f"[OCR] Starting OCR on {sub_path.name}...")
    runner._log_message(f"[OCR] Language: {lang}, Output: {output_format.upper()}")

    try:
        # Create progress callback that uses runner logging
        def progress_callback(message: str, progress: float):
            runner._log_message(f"[OCR] {message} ({int(progress * 100)}%)")

        # Build settings dict for pipeline
        ocr_settings = _build_ocr_settings(config, lang)

        # Create and run pipeline
        pipeline = OCRPipeline(
            settings_dict=ocr_settings,
            work_dir=work_dir,
            logs_dir=logs_dir,
            progress_callback=progress_callback
        )

        result = pipeline.process(
            input_path=input_path,
            output_path=output_path,
            track_id=track_id
        )

        if result.success:
            runner._log_message(f"[OCR] Successfully created {output_path.name}")
            runner._log_message(f"[OCR] Processed {result.subtitle_count} subtitles in {result.duration_seconds:.1f}s")

            # Log summary from report
            if result.report_summary:
                summary = result.report_summary
                runner._log_message(f"[OCR] Average confidence: {summary.get('average_confidence', 0):.1f}%")
                runner._log_message(f"[OCR] Fixes applied: {summary.get('total_fixes', 0)}")
                unknown_count = summary.get('unknown_word_count', 0)
                if unknown_count > 0:
                    runner._log_message(f"[OCR] Unknown words: {unknown_count}")
                    top_unknown = summary.get('top_unknown_words', [])[:5]
                    if top_unknown:
                        runner._log_message(f"[OCR] Top unknown: {', '.join(top_unknown)}")
                low_conf = summary.get('low_confidence_count', 0)
                if low_conf > 0:
                    runner._log_message(f"[OCR] Low confidence lines: {low_conf} (see report)")

            if result.report_path:
                runner._log_message(f"[OCR] Report saved: {result.report_path.name}")

            return str(output_path)
        else:
            runner._log_message(f"[OCR] ERROR: {result.error or 'Unknown error'}")
            return None

    except ImportError as e:
        runner._log_message(f"[OCR] ERROR: Missing dependency: {e}")
        runner._log_message("[OCR] Please install: pip install pytesseract")
        return None
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: Failed to perform OCR: {e}")
        return None


def _build_ocr_settings(config: dict, lang: str) -> dict:
    """
    Build OCR settings dict from application config.

    Maps config keys to OCR pipeline settings.
    """
    # Map 3-letter language codes to Tesseract codes
    lang_map = {
        'eng': 'eng',
        'jpn': 'jpn',
        'spa': 'spa',
        'fra': 'fra',
        'deu': 'deu',
        'chi': 'chi_sim',
        'kor': 'kor',
        'por': 'por',
        'ita': 'ita',
        'rus': 'rus',
    }

    tesseract_lang = lang_map.get(lang, lang)

    return {
        # Language
        'ocr_language': tesseract_lang,

        # Preprocessing
        'ocr_preprocess_auto': config.get('ocr_preprocess_auto', True),
        'ocr_force_binarization': config.get('ocr_force_binarization', False),
        'ocr_upscale_threshold': config.get('ocr_upscale_threshold', 40),
        'ocr_denoise': config.get('ocr_denoise', False),

        # OCR engine
        'ocr_char_blacklist': config.get('ocr_char_blacklist', ''),
        'ocr_low_confidence_threshold': config.get('ocr_low_confidence_threshold', 60.0),

        # Post-processing
        'ocr_cleanup_enabled': config.get('ocr_cleanup_enabled', True),
        'ocr_cleanup_normalize_ellipsis': config.get('ocr_cleanup_normalize_ellipsis', False),
        'ocr_custom_wordlist_path': config.get('ocr_custom_wordlist_path', ''),

        # Output
        'ocr_output_format': config.get('ocr_output_format', 'ass'),
        'ocr_preserve_positions': config.get('ocr_preserve_positions', True),
        'ocr_bottom_threshold': config.get('ocr_bottom_threshold', 75.0),

        # Reporting
        'ocr_generate_report': config.get('ocr_generate_report', True),
        'ocr_save_debug_images': config.get('ocr_save_debug_images', False),
    }


def check_ocr_available() -> tuple[bool, str]:
    """
    Check if OCR is available (Tesseract installed).

    Returns:
        Tuple of (is_available, message)
    """
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return True, f"Tesseract {version} available"
    except ImportError:
        return False, "pytesseract not installed (pip install pytesseract)"
    except Exception as e:
        return False, f"Tesseract not found: {e}"
