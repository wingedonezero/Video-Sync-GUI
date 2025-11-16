# vsg_core/subtitles/ocr_vobsub.py
# -*- coding: utf-8 -*-
"""
VobSub OCR orchestrator using native Python parsing and tesserocr.
Replaces external subtile-ocr dependency with integrated solution.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from ..io.runner import CommandRunner
from .parsers.vobsub import VobSubParser
from .preprocessing.image import ImagePreprocessor
from .engines.tesseract import TesseractEngine
from .builders.ass import ASSBuilder


def run_vobsub_ocr(
    idx_path: str,
    lang: str,
    runner: CommandRunner,
    config: dict,
) -> Optional[str]:
    """
    Runs OCR on a VobSub (.idx/.sub) subtitle file using native Python implementation.

    This function:
    1. Parses VobSub files to extract subtitle images and timing
    2. Preprocesses images for optimal Tesseract accuracy
    3. Runs Tesseract OCR with subtitle-optimized settings
    4. Generates ASS file with preserved positioning

    Args:
        idx_path: Path to the .idx file
        lang: 3-letter language code (e.g., 'eng')
        runner: CommandRunner for logging
        config: Configuration dictionary

    Returns:
        Path to generated .ass file, or None on failure
    """
    idx_file = Path(idx_path)

    # Validate input
    if not idx_file.exists():
        runner._log_message(f"[OCR] ERROR: IDX file not found: {idx_path}")
        return None

    if idx_file.suffix.lower() != '.idx':
        runner._log_message(f"[OCR] ERROR: Not an IDX file: {idx_path}")
        return None

    runner._log_message(f"[OCR] Processing VobSub file: {idx_file.name}")
    runner._log_message(f"[OCR] Language: {lang}")

    try:
        # Step 1: Parse VobSub files
        runner._log_message("[OCR] Parsing VobSub files...")
        parser = VobSubParser(str(idx_file))
        events = parser.parse()

        if not events:
            runner._log_message("[OCR] WARNING: No subtitle events found in VobSub file.")
            runner._log_message("[OCR] This may indicate an empty subtitle track or parsing failure.")
            return None

        runner._log_message(f"[OCR] Found {len(events)} subtitle events")

        # Step 2: Initialize preprocessing and OCR
        runner._log_message("[OCR] Initializing OCR engine...")

        # Add language to config
        ocr_config = config.copy()
        ocr_config['ocr_lang'] = lang

        preprocessor = ImagePreprocessor(ocr_config)

        try:
            ocr_engine = TesseractEngine(ocr_config)

            # Log tessdata path being used
            if hasattr(ocr_engine, 'tessdata_path') and ocr_engine.tessdata_path:
                runner._log_message(f"[OCR] Using tessdata path: {ocr_engine.tessdata_path}")
            else:
                runner._log_message("[OCR] Using tesserocr auto-detected tessdata path")

            # Log OCR settings
            runner._log_message(f"[OCR] Settings: PSM={ocr_engine.psm}, OEM={ocr_engine.oem}, Lang={ocr_engine.lang}")

        except ImportError as e:
            runner._log_message(f"[OCR] ERROR: {str(e)}")
            return None
        except Exception as e:
            runner._log_message(f"[OCR] ERROR: Failed to initialize Tesseract: {str(e)}")
            runner._log_message("[OCR] Make sure Tesseract OCR and language data are installed.")
            return None

        # Step 3: Initialize ASS builder
        ass_builder = ASSBuilder(
            frame_width=parser.frame_width,
            frame_height=parser.frame_height
        )

        # Step 4: Process each subtitle event
        runner._log_message("[OCR] Performing OCR on subtitle images...")

        successful_count = 0
        low_confidence_count = 0
        failed_count = 0

        for i, event in enumerate(events, 1):
            try:
                # Preprocess image
                preprocessed_lines = preprocessor.preprocess(event.image)

                # OCR each line
                line_texts = []
                line_confidences = []

                for line_image in preprocessed_lines:
                    ocr_result = ocr_engine.recognize(line_image)

                    if ocr_result.text.strip():
                        line_texts.append(ocr_result.text.strip())
                        line_confidences.append(ocr_result.confidence)

                        # Log low confidence warnings
                        if ocr_result.confidence < 70 and ocr_result.confidence > 0:
                            low_confidence_count += 1

                # Combine lines with line break
                if line_texts:
                    combined_text = '\\N'.join(line_texts)
                    avg_confidence = sum(line_confidences) / len(line_confidences) if line_confidences else 0

                    # Add to ASS file with positioning
                    preserve_pos = config.get('ocr_preserve_positioning', True)
                    ass_builder.add_event(
                        start_ms=event.start_time,
                        end_ms=event.end_time,
                        text=combined_text,
                        x=event.x,
                        y=event.y,
                        width=event.width,
                        height=event.height,
                        preserve_position=preserve_pos
                    )

                    successful_count += 1
                else:
                    # No text recognized
                    failed_count += 1

            except Exception as e:
                # Log error but continue processing
                runner._log_message(f"[OCR] Warning: Failed to process event {i}: {str(e)}")
                failed_count += 1
                continue

        # Step 5: Save ASS file
        output_path = idx_file.with_suffix('.ass')
        ass_builder.save(str(output_path))

        # Step 6: Report statistics
        runner._log_message("[OCR] === OCR Statistics ===")
        runner._log_message(f"[OCR] Total events: {len(events)}")
        runner._log_message(f"[OCR] Successful: {successful_count}")
        runner._log_message(f"[OCR] Low confidence: {low_confidence_count}")
        runner._log_message(f"[OCR] Failed: {failed_count}")
        runner._log_message(f"[OCR] Output: {output_path.name}")

        # Check if output is reasonable
        if successful_count == 0:
            runner._log_message("[OCR] WARNING: No text was recognized from any subtitle.")
            runner._log_message("[OCR] This may indicate a problem with Tesseract or the subtitle images.")
            return None

        if successful_count < len(events) * 0.5:
            runner._log_message("[OCR] WARNING: Less than 50% of subtitles were successfully recognized.")
            runner._log_message("[OCR] The OCR quality may be poor. Consider checking Tesseract installation.")

        runner._log_message(f"[OCR] Successfully created {output_path.name}")
        return str(output_path)

    except FileNotFoundError as e:
        runner._log_message(f"[OCR] ERROR: File not found: {e}")
        return None
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: Unexpected error during OCR: {str(e)}")
        runner._log_message(f"[OCR] Error type: {type(e).__name__}")
        import traceback
        runner._log_message(f"[OCR] Traceback: {traceback.format_exc()}")
        return None
