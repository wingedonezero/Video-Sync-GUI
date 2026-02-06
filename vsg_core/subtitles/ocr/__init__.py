# vsg_core/subtitles/ocr/__init__.py
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.settings import AppSettings
    from vsg_core.subtitles.data import SubtitleData

from .engine import OCREngine
from .pipeline import OCRPipeline
from .report import LowConfidenceLine, OCRReport, UnknownWord
from .romaji_dictionary import (
    KanaToRomaji,
    RomajiDictionary,
    get_romaji_dictionary,
    is_romaji_word,
)

__all__ = [
    "KanaToRomaji",
    "LowConfidenceLine",
    "OCREngine",
    "OCRPipeline",
    "OCRReport",
    "RomajiDictionary",
    "UnknownWord",
    "check_ocr_available",
    "get_romaji_dictionary",
    "is_romaji_word",
    "run_ocr",
    "run_ocr_unified",
    "run_preview_ocr",
]


def run_ocr(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    tool_paths: dict,
    settings: AppSettings,
    work_dir: Path | None = None,
    logs_dir: Path | None = None,
    track_id: int = 0,
) -> str | None:
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
        settings: The application's typed settings (AppSettings)
        work_dir: Working directory for temp files
        logs_dir: Directory for OCR reports
        track_id: Track ID for organizing work files

    Returns:
        The path to the generated subtitle file (ASS or SRT), or None on failure.
    """
    sub_path = Path(subtitle_path)

    # Determine input type
    suffix = sub_path.suffix.lower()
    if suffix == ".idx":
        # VobSub - use .idx path
        input_path = sub_path
    elif suffix == ".sub":
        # VobSub - convert to .idx path
        input_path = sub_path.with_suffix(".idx")
        if not input_path.exists():
            runner._log_message(f"[OCR] ERROR: IDX file not found: {input_path}")
            return None
    elif suffix == ".sup":
        # PGS - not yet supported
        runner._log_message(
            f"[OCR] WARNING: PGS (.sup) support not yet implemented. Skipping {sub_path.name}"
        )
        return None
    else:
        runner._log_message(f"[OCR] Skipping {sub_path.name}: Unsupported format.")
        return None

    # Determine output format and path
    output_format = settings.ocr_output_format
    output_suffix = ".ass" if output_format == "ass" else ".srt"
    output_path = sub_path.with_suffix(output_suffix)

    # Set up directories
    if work_dir is None:
        work_dir = sub_path.parent / "ocr_work"
    if logs_dir is None:
        logs_dir = sub_path.parent

    runner._log_message(f"[OCR] Starting OCR on {sub_path.name}...")
    runner._log_message(f"[OCR] Language: {lang}, Output: {output_format.upper()}")

    try:
        # Create progress callback that uses runner logging
        def progress_callback(message: str, progress: float):
            runner._log_message(f"[OCR] {message} ({int(progress * 100)}%)")

        # Build settings dict for pipeline from typed AppSettings
        ocr_settings = _build_ocr_settings(settings, lang)

        # Create and run pipeline
        pipeline = OCRPipeline(
            settings_dict=ocr_settings,
            work_dir=work_dir,
            logs_dir=logs_dir,
            progress_callback=progress_callback,
        )

        result = pipeline.process(
            input_path=input_path, output_path=output_path, track_id=track_id
        )

        if result.success:
            runner._log_message(f"[OCR] Successfully created {output_path.name}")
            runner._log_message(
                f"[OCR] Processed {result.subtitle_count} subtitles in {result.duration_seconds:.1f}s"
            )

            # Log summary from report
            if result.report_summary:
                summary = result.report_summary
                runner._log_message(
                    f"[OCR] Average confidence: {summary.get('average_confidence', 0):.1f}%"
                )
                total_fixes = summary.get("total_fixes", 0)
                if total_fixes > 0:
                    runner._log_message(f"[OCR] Fixes applied: {total_fixes} total")
                unknown_count = summary.get("unknown_word_count", 0)
                if unknown_count > 0:
                    runner._log_message(f"[OCR] Unknown words: {unknown_count} unique")
                    top_unknown = summary.get("top_unknown_words", [])[:5]
                    if top_unknown:
                        runner._log_message(
                            f"[OCR] Top unknown: {', '.join(top_unknown)}"
                        )
                low_conf = summary.get("low_confidence_count", 0)
                if low_conf > 0:
                    runner._log_message(
                        f"[OCR] Low confidence lines: {low_conf} (see report)"
                    )

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


def _build_ocr_settings(settings: AppSettings, lang: str) -> dict:
    """
    Build OCR settings dict from AppSettings for internal OCR pipeline.

    Maps AppSettings fields to OCR pipeline settings dict.
    The internal OCR components use dict for their own config.
    """

    def get_val(key: str, default=None):
        return getattr(settings, key, default)

    # Map 3-letter language codes to Tesseract codes
    lang_map = {
        "eng": "eng",
        "jpn": "jpn",
        "spa": "spa",
        "fra": "fra",
        "deu": "deu",
        "chi": "chi_sim",
        "kor": "kor",
        "por": "por",
        "ita": "ita",
        "rus": "rus",
    }

    tesseract_lang = lang_map.get(lang, lang)

    return {
        # Language
        "ocr_language": tesseract_lang,
        # Preprocessing
        "ocr_preprocess_auto": get_val("ocr_preprocess_auto", True),
        "ocr_force_binarization": get_val("ocr_force_binarization", False),
        "ocr_upscale_threshold": get_val("ocr_upscale_threshold", 40),
        "ocr_target_height": get_val("ocr_target_height", 80),
        "ocr_border_size": get_val("ocr_border_size", 5),
        "ocr_binarization_method": get_val("ocr_binarization_method", "otsu"),
        "ocr_denoise": get_val("ocr_denoise", False),
        # OCR engine
        "ocr_engine": get_val("ocr_engine", "tesseract"),
        "ocr_psm": get_val("ocr_psm", 7),
        "ocr_char_whitelist": get_val("ocr_char_whitelist", ""),
        "ocr_char_blacklist": get_val("ocr_char_blacklist", "|"),
        "ocr_multi_pass": get_val("ocr_multi_pass", True),
        "ocr_low_confidence_threshold": get_val("ocr_low_confidence_threshold", 60.0),
        # Post-processing
        "ocr_cleanup_enabled": get_val("ocr_cleanup_enabled", True),
        "ocr_cleanup_normalize_ellipsis": get_val(
            "ocr_cleanup_normalize_ellipsis", False
        ),
        "ocr_custom_wordlist_path": get_val("ocr_custom_wordlist_path", ""),
        # Output
        "ocr_output_format": get_val("ocr_output_format", "ass"),
        "ocr_preserve_positions": get_val("ocr_preserve_positions", True),
        "ocr_bottom_threshold": get_val("ocr_bottom_threshold", 75.0),
        "ocr_video_width": get_val("ocr_video_width", 1920),
        "ocr_video_height": get_val("ocr_video_height", 1080),
        "ocr_font_size_ratio": get_val("ocr_font_size_ratio", 5.80),
        # Reporting
        "ocr_generate_report": get_val("ocr_generate_report", True),
        "ocr_save_debug_images": get_val("ocr_save_debug_images", False),
        # Debug output - saves images and text files for problem subtitles
        "ocr_debug_output": get_val("ocr_debug_output", False),
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


def run_ocr_unified(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    tool_paths: dict,
    settings: AppSettings,
    work_dir: Path | None = None,
    logs_dir: Path | None = None,
    track_id: int = 0,
) -> SubtitleData | None:
    """
    Run OCR and return SubtitleData with all OCR metadata preserved.

    This is the unified entry point for OCR -> SubtitleData conversion.
    All OCR metadata (confidence, raw text, fixes, position, colors) is
    preserved on each event for the unified subtitle pipeline.

    Args:
        subtitle_path: Path to the subtitle file (.idx for VobSub)
        lang: The 3-letter language code for OCR (e.g., 'eng')
        runner: The CommandRunner instance for logging
        tool_paths: A dictionary of tool paths (unused by new OCR)
        settings: The application's typed settings
        work_dir: Working directory for temp files
        logs_dir: Directory for OCR reports
        track_id: Track ID for organizing work files

    Returns:
        SubtitleData with OCR metadata, or None on failure.
    """
    sub_path = Path(subtitle_path)

    # Determine input type
    suffix = sub_path.suffix.lower()
    if suffix == ".idx":
        input_path = sub_path
    elif suffix == ".sub":
        input_path = sub_path.with_suffix(".idx")
        if not input_path.exists():
            runner._log_message(f"[OCR] ERROR: IDX file not found: {input_path}")
            return None
    elif suffix == ".sup":
        runner._log_message(
            f"[OCR] WARNING: PGS (.sup) support not yet implemented. Skipping {sub_path.name}"
        )
        return None
    else:
        runner._log_message(f"[OCR] Skipping {sub_path.name}: Unsupported format.")
        return None

    # Set up directories
    if work_dir is None:
        work_dir = sub_path.parent / "ocr_work"
    if logs_dir is None:
        logs_dir = sub_path.parent

    runner._log_message(f"[OCR] Starting OCR on {sub_path.name}...")
    runner._log_message(f"[OCR] Language: {lang}, Mode: Unified (SubtitleData)")

    try:
        # Create progress callback that uses runner logging
        def progress_callback(message: str, progress: float):
            runner._log_message(f"[OCR] {message} ({int(progress * 100)}%)")

        # Build settings dict for pipeline from typed AppSettings
        ocr_settings = _build_ocr_settings(settings, lang)

        # Create and run pipeline with return_subtitle_data=True
        pipeline = OCRPipeline(
            settings_dict=ocr_settings,
            work_dir=work_dir,
            logs_dir=logs_dir,
            progress_callback=progress_callback,
        )

        result = pipeline.process(
            input_path=input_path,
            output_path=sub_path.with_suffix(".ass"),  # Provide path for reference
            track_id=track_id,
            return_subtitle_data=True,  # Return SubtitleData instead of writing file
        )

        if result.success and result.subtitle_data:
            runner._log_message(
                f"[OCR] Successfully processed {result.subtitle_count} subtitles in {result.duration_seconds:.1f}s"
            )

            # Log summary from report
            if result.report_summary:
                summary = result.report_summary
                runner._log_message(
                    f"[OCR] Average confidence: {summary.get('average_confidence', 0):.1f}%"
                )
                total_fixes = summary.get("total_fixes", 0)
                if total_fixes > 0:
                    runner._log_message(f"[OCR] Fixes applied: {total_fixes} total")
                unknown_count = summary.get("unknown_word_count", 0)
                if unknown_count > 0:
                    runner._log_message(f"[OCR] Unknown words: {unknown_count} unique")

            if result.report_path:
                runner._log_message(f"[OCR] Report saved: {result.report_path.name}")

            return result.subtitle_data
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


def run_preview_ocr(
    subtitle_path: str,
    lang: str,
    output_dir: Path,
    log_callback=None,
) -> tuple[str, str] | None:
    """
    Run fast preview OCR for style editor.

    Uses EasyOCR (faster than PaddleOCR) with minimal settings for quick preview.
    Returns SubtitleData JSON and ASS file for style editing.

    Args:
        subtitle_path: Path to the subtitle file (.idx for VobSub, .sup for PGS)
        lang: The 3-letter language code for OCR (e.g., 'eng')
        output_dir: Directory to save output files (style_editor_temp/)
        log_callback: Optional callback for logging messages

    Returns:
        Tuple of (json_path, ass_path) on success, or None on failure.
        - json_path: SubtitleData with full OCR metadata
        - ass_path: ASS file for visual editing in style editor
    """
    import time

    from .backends import get_available_backends

    sub_path = Path(subtitle_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str):
        if log_callback:
            log_callback(msg)

    # Validate input format
    suffix = sub_path.suffix.lower()
    if suffix == ".idx":
        input_path = sub_path
    elif suffix == ".sub":
        input_path = sub_path.with_suffix(".idx")
        if not input_path.exists():
            log(f"[Preview OCR] ERROR: IDX file not found: {input_path}")
            return None
    elif suffix == ".sup":
        log("[Preview OCR] WARNING: PGS (.sup) support not yet implemented.")
        return None
    else:
        log(f"[Preview OCR] ERROR: Unsupported format: {suffix}")
        return None

    # Determine OCR engine - prefer EasyOCR for speed, fallback to Tesseract
    available = get_available_backends()
    if "easyocr" in available:
        ocr_engine = "easyocr"
    elif "tesseract" in available:
        ocr_engine = "tesseract"
        log("[Preview OCR] EasyOCR not available, using Tesseract")
    else:
        log("[Preview OCR] ERROR: No OCR backend available (need EasyOCR or Tesseract)")
        return None

    log(f"[Preview OCR] Starting preview OCR with {ocr_engine}...")

    # Map language code
    lang_map = {
        "eng": "eng",
        "jpn": "jpn",
        "spa": "spa",
        "fra": "fra",
        "deu": "deu",
        "chi": "chi_sim",
        "kor": "kor",
        "por": "por",
        "ita": "ita",
        "rus": "rus",
    }
    ocr_lang = lang_map.get(lang, lang)

    # Minimal settings for fast preview
    preview_settings = {
        "ocr_language": ocr_lang,
        "ocr_engine": ocr_engine,
        "ocr_preprocess_auto": True,
        "ocr_force_binarization": False,
        "ocr_upscale_threshold": 40,
        "ocr_denoise": False,
        "ocr_char_blacklist": "",
        "ocr_low_confidence_threshold": 60.0,
        "ocr_cleanup_enabled": True,
        "ocr_cleanup_normalize_ellipsis": False,
        "ocr_custom_wordlist_path": "",
        "ocr_output_format": "ass",
        "ocr_preserve_positions": True,
        "ocr_bottom_threshold": 75.0,
        # Disable reports and debug for speed
        "ocr_generate_report": False,
        "ocr_save_debug_images": False,
        "ocr_debug_output": False,
    }

    try:
        # Create work directory for OCR processing
        work_dir = output_dir / "ocr_work"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Progress callback
        def progress_callback(message: str, progress: float):
            log(f"[Preview OCR] {message} ({int(progress * 100)}%)")

        # Run OCR pipeline
        pipeline = OCRPipeline(
            settings_dict=preview_settings,
            work_dir=work_dir,
            logs_dir=output_dir,
            progress_callback=progress_callback,
        )

        result = pipeline.process(
            input_path=input_path,
            output_path=output_dir / f"preview_{sub_path.stem}.ass",
            track_id=0,
            return_subtitle_data=True,
        )

        if not result.success or not result.subtitle_data:
            log(f"[Preview OCR] ERROR: {result.error or 'OCR failed'}")
            return None

        subtitle_data = result.subtitle_data

        if not subtitle_data.events:
            log("[Preview OCR] WARNING: OCR produced no events")
            return None

        log(f"[Preview OCR] Processed {len(subtitle_data.events)} subtitles")

        # Generate unique output filenames
        unique_id = int(time.time() * 1000) % 1000000
        stem = sub_path.stem
        json_path = output_dir / f"preview_{stem}_{unique_id}.json"
        ass_path = output_dir / f"preview_{stem}_{unique_id}.ass"

        # Save SubtitleData to JSON (preserves all OCR metadata)
        subtitle_data.save_json(json_path)
        log(f"[Preview OCR] Saved metadata: {json_path.name}")

        # Save ASS for style editing
        subtitle_data.save_ass(ass_path)
        log(f"[Preview OCR] Saved ASS: {ass_path.name}")

        return str(json_path), str(ass_path)

    except ImportError as e:
        log(f"[Preview OCR] ERROR: Missing dependency: {e}")
        return None
    except Exception as e:
        log(f"[Preview OCR] ERROR: {e}")
        import traceback

        log(f"[Preview OCR] {traceback.format_exc()}")
        return None
