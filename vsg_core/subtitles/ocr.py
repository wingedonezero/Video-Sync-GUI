# vsg_core/subtitles/ocr.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Optional

from ..io.runner import CommandRunner


def run_vobsub_ocr(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    tool_paths: dict,
    config: dict,
) -> Optional[str]:
    """
    Runs the subtile-ocr tool on VobSub (IDX/SUB) subtitle files.

    Args:
        subtitle_path: Path to the .idx file.
        lang: The 3-letter language code for OCR (e.g., 'eng').
        runner: The CommandRunner instance.
        tool_paths: A dictionary of tool paths.
        config: The application's configuration dictionary.

    Returns:
        The path to the generated SRT file, or None on failure.
    """
    sub_path = Path(subtitle_path)

    ocr_tool_path = config.get('subtile_ocr_path') or tool_paths.get('subtile-ocr')
    if not ocr_tool_path:
        runner._log_message("[OCR] ERROR: 'subtile-ocr' tool path is not configured or found in PATH.")
        return None

    output_path = sub_path.with_suffix('.srt')
    runner._log_message(f"[OCR] Performing VobSub OCR on {sub_path.name}...")

    cmd = [
        ocr_tool_path,
        '--lang', lang,
        '--output', str(output_path),
        str(sub_path)
    ]

    blacklist = config.get('subtile_ocr_char_blacklist', '').strip()
    if blacklist:
        cmd.extend(['--config', f"tessedit_char_blacklist='{blacklist}'"])

    result = runner.run(cmd, tool_paths)

    if result is not None and output_path.exists():
        runner._log_message(f"[OCR] Successfully created {output_path.name}")
        return str(output_path)
    else:
        runner._log_message(f"[OCR] ERROR: Failed to perform VobSub OCR on {sub_path.name}.")
        return None


def run_pgs_ocr(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    config: dict,
) -> Optional[str]:
    """
    Runs OCR on PGS (SUP) subtitle files using integrated PGS OCR system.

    Args:
        subtitle_path: Path to the .sup file.
        lang: The 3-letter language code for OCR (e.g., 'eng').
        runner: The CommandRunner instance.
        config: The application's configuration dictionary.

    Returns:
        The path to the generated ASS file, or None on failure.
    """
    sub_path = Path(subtitle_path)
    output_path = sub_path.with_suffix('.ass')

    runner._log_message(f"[OCR] Performing PGS OCR on {sub_path.name}...")

    try:
        # Import PGS OCR module
        from .pgs import extract_pgs_subtitles, PreprocessSettings

        # Get video dimensions from config (default to 1920x1080)
        video_width = config.get('pgs_video_width', 1920)
        video_height = config.get('pgs_video_height', 1080)

        # Get tesseract path from config if specified
        tesseract_path = config.get('tesseract_path')

        # Get font size from config (0 = auto-calculate)
        font_size_config = config.get('pgs_font_size', 0)
        font_size = None if font_size_config == 0 else font_size_config

        # Create preprocessing settings from config
        preprocess_settings = PreprocessSettings(
            crop_transparent=config.get('pgs_crop_transparent', True),
            crop_max=config.get('pgs_crop_max', 20),
            add_margin=config.get('pgs_add_margin', 10),
            invert_colors=config.get('pgs_invert_colors', False),
            yellow_to_white=config.get('pgs_yellow_to_white', True),
            binarize=config.get('pgs_binarize', True),
            binarize_threshold=config.get('pgs_binarize_threshold', 200),
            scale_percent=config.get('pgs_scale_percent', 100),
            enhance_contrast=config.get('pgs_enhance_contrast', 1.5),
        )

        # Run PGS OCR
        result = extract_pgs_subtitles(
            sup_file=str(sub_path),
            output_file=str(output_path),
            lang=lang,
            video_width=video_width,
            video_height=video_height,
            from_matroska=False,
            tesseract_path=tesseract_path,
            preprocess_settings=preprocess_settings,
            font_size=font_size,
            log_callback=runner._log_message,
            save_debug_images=True  # Enable debug images for now
        )

        if result and Path(result).exists():
            runner._log_message(f"[OCR] Successfully created {Path(result).name}")
            return result
        else:
            runner._log_message(f"[OCR] ERROR: Failed to perform PGS OCR on {sub_path.name}.")
            return None

    except ImportError as e:
        runner._log_message(f"[OCR] ERROR: PGS OCR module not available: {e}")
        return None
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: PGS OCR failed: {e}")
        import traceback
        runner._log_message(traceback.format_exc())
        return None


def run_ocr(
    subtitle_path: str,
    lang: str,
    runner: CommandRunner,
    tool_paths: dict,
    config: dict,
) -> Optional[str]:
    """
    Runs OCR on image-based subtitle files.
    Supports both VobSub (IDX/SUB) and PGS (SUP) formats.

    Args:
        subtitle_path: Path to the subtitle file (.idx or .sup).
        lang: The 3-letter language code for OCR (e.g., 'eng').
        runner: The CommandRunner instance.
        tool_paths: A dictionary of tool paths.
        config: The application's configuration dictionary.

    Returns:
        The path to the generated subtitle file (SRT or ASS), or None on failure.
    """
    sub_path = Path(subtitle_path)
    suffix = sub_path.suffix.lower()

    if suffix == '.idx':
        # VobSub format
        return run_vobsub_ocr(subtitle_path, lang, runner, tool_paths, config)
    elif suffix == '.sup':
        # PGS format
        return run_pgs_ocr(subtitle_path, lang, runner, config)
    else:
        runner._log_message(f"[OCR] Skipping {sub_path.name}: Unsupported format (expected .idx or .sup)")
        return None
