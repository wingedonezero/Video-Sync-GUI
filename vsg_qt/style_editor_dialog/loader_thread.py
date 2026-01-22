# vsg_qt/style_editor_dialog/loader_thread.py
# -*- coding: utf-8 -*-
"""
Background loader thread for style editor subtitle preparation.

Handles both regular subtitle extraction and OCR preview generation
without blocking the UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Callable, Dict, Any

from PySide6.QtCore import QThread, Signal


class SubtitleLoaderThread(QThread):
    """
    Thread for loading/preparing subtitles for the style editor.

    Handles:
    - Regular subtitle extraction (ASS/SRT from container)
    - OCR preview generation (VobSub/PGS with EasyOCR)
    """

    # Signals
    progress = Signal(str, int)  # (message, percent 0-100)
    finished = Signal(bool, str, str)  # (success, subtitle_path, error_message)

    def __init__(
        self,
        prepare_func: Callable[[], Optional[str]],
        is_ocr: bool = False,
        parent=None
    ):
        """
        Initialize the loader thread.

        Args:
            prepare_func: Function that prepares the subtitle and returns the path.
                         For OCR, this should also handle progress via log_callback.
            is_ocr: Whether this is an OCR operation (affects progress messages)
        """
        super().__init__(parent)
        self.prepare_func = prepare_func
        self.is_ocr = is_ocr
        self._log_messages = []

    def run(self):
        """Run the subtitle preparation."""
        try:
            if self.is_ocr:
                self.progress.emit("Running OCR...", 0)
            else:
                self.progress.emit("Extracting subtitle...", 0)

            result = self.prepare_func()

            if result:
                self.progress.emit("Done", 100)
                self.finished.emit(True, result, "")
            else:
                self.finished.emit(False, "", "Failed to prepare subtitle")

        except Exception as e:
            self.finished.emit(False, "", str(e))


class OCRLoaderThread(QThread):
    """
    Specialized thread for OCR preview with detailed progress tracking.
    """

    # Signals
    progress = Signal(str, int)  # (message, percent 0-100)
    log = Signal(str)  # Log messages
    finished = Signal(bool, str, str, str)  # (success, json_path, ass_path, error_message)

    def __init__(
        self,
        extracted_path: str,
        lang: str,
        output_dir: Path,
        parent=None
    ):
        """
        Initialize the OCR loader thread.

        Args:
            extracted_path: Path to extracted image-based subtitle (.idx or .sup)
            lang: Language code for OCR
            output_dir: Directory for output files
        """
        super().__init__(parent)
        self.extracted_path = extracted_path
        self.lang = lang
        self.output_dir = output_dir
        self._current_progress = 0

    def _log_callback(self, message: str):
        """Handle log messages and extract progress info."""
        self.log.emit(message)

        # Try to extract progress percentage from OCR messages
        if "%" in message and "[Preview OCR]" in message:
            try:
                # Format: "[Preview OCR] message (XX%)"
                pct_str = message.split("(")[-1].rstrip("%)")
                pct = int(pct_str)
                self._current_progress = pct
                # Extract the message part
                msg_part = message.split("]")[1].split("(")[0].strip()
                self.progress.emit(msg_part, pct)
            except (ValueError, IndexError):
                pass
        elif "[Preview OCR]" in message:
            # Non-percentage message
            msg_part = message.split("]")[1].strip() if "]" in message else message
            self.progress.emit(msg_part, self._current_progress)

    def run(self):
        """Run the OCR preview."""
        try:
            self.progress.emit("Starting OCR preview...", 0)

            from vsg_core.subtitles.ocr import run_preview_ocr

            result = run_preview_ocr(
                subtitle_path=self.extracted_path,
                lang=self.lang,
                output_dir=self.output_dir,
                log_callback=self._log_callback,
            )

            if result:
                json_path, ass_path = result
                self.progress.emit("OCR complete", 100)
                self.finished.emit(True, json_path, ass_path, "")
            else:
                self.finished.emit(False, "", "", "OCR preview failed")

        except Exception as e:
            import traceback
            self.finished.emit(False, "", "", f"{e}\n{traceback.format_exc()}")
