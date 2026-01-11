# vsg_core/orchestrator/validation.py
# -*- coding: utf-8 -*-
"""
Validation helpers for pipeline steps.
Ensures each step completed successfully before proceeding.
"""
from pathlib import Path
from typing import List

from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.enums import TrackType


class PipelineValidationError(Exception):
    """Raised when a pipeline step validation fails."""
    pass


class StepValidator:
    """Validates that pipeline steps completed successfully."""

    @staticmethod
    def validate_analysis(ctx: Context) -> None:
        """
        Validates analysis step results.
        Raises PipelineValidationError if validation fails.
        """
        if not ctx.delays:
            raise PipelineValidationError(
                "Analysis failed: No delays calculated. "
                "Check that audio correlation or VideoDiff completed successfully."
            )

        if ctx.and_merge and len(ctx.sources) > 1:
            for source_key in ctx.sources:
                if source_key == "Source 1":
                    continue
                if source_key not in ctx.delays.source_delays_ms:
                    raise PipelineValidationError(
                        f"Analysis incomplete: No delay calculated for {source_key}. "
                        f"Audio correlation may have failed."
                    )

        for source_key, delay in ctx.delays.source_delays_ms.items():
            if not isinstance(delay, (int, float)):
                raise PipelineValidationError(
                    f"Invalid delay value for {source_key}: {delay}"
                )
            if abs(delay) > 3600000:
                raise PipelineValidationError(
                    f"Unreasonable delay for {source_key}: {delay}ms. "
                    f"This likely indicates an analysis error."
                )

    @staticmethod
    def validate_extraction(ctx: Context) -> None:
        """
        Validates extraction step results.
        Raises PipelineValidationError if validation fails.
        """
        if not ctx.extracted_items:
            raise PipelineValidationError(
                "Extraction failed: No tracks extracted. "
                "Check that mkvextract completed successfully."
            )

        expected = len([item for item in ctx.manual_layout if item])
        actual = len([item for item in ctx.extracted_items if not item.is_preserved])

        if actual < expected:
            raise PipelineValidationError(
                f"Extraction incomplete: Expected {expected} tracks, got {actual}. "
                f"Some tracks may have failed to extract."
            )

        for item in ctx.extracted_items:
            if not item.extracted_path or not item.extracted_path.exists():
                raise PipelineValidationError(
                    f"Extraction failed: Track file missing at {item.extracted_path}"
                )

    @staticmethod
    def validate_correction(ctx: Context) -> None:
        """
        Validates audio correction results.
        Raises PipelineValidationError if validation fails.
        """
        errors = []

        for analysis_key in ctx.pal_drift_flags:
            source_key = analysis_key.split('_')[0]
            corrected_items = [
                item for item in ctx.extracted_items
                if (item.track.source == source_key and
                    item.track.type == TrackType.AUDIO and
                    item.is_corrected and
                    not item.is_preserved)
            ]
            if not corrected_items:
                errors.append(
                    f"PAL drift correction failed for {source_key}: "
                    f"No corrected track found in extraction list"
                )
            else:
                for item in corrected_items:
                    if item.track.props.codec_id != "FLAC":
                        errors.append(
                            f"PAL drift corrected track for {source_key} is not FLAC: "
                            f"{item.track.props.codec_id}"
                        )
                    if not item.extracted_path or not item.extracted_path.exists():
                        errors.append(
                            f"PAL drift corrected file missing for {source_key}"
                        )

        for analysis_key in ctx.linear_drift_flags:
            source_key = analysis_key.split('_')[0]
            corrected_items = [
                item for item in ctx.extracted_items
                if (item.track.source == source_key and
                    item.track.type == TrackType.AUDIO and
                    item.is_corrected and
                    not item.is_preserved)
            ]
            if not corrected_items:
                errors.append(
                    f"Linear drift correction failed for {source_key}: "
                    f"No corrected track found in extraction list"
                )
            else:
                for item in corrected_items:
                    if item.track.props.codec_id != "FLAC":
                        errors.append(
                            f"Linear drift corrected track for {source_key} is not FLAC: "
                            f"{item.track.props.codec_id}"
                        )
                    if not item.extracted_path or not item.extracted_path.exists():
                        errors.append(
                            f"Linear drift corrected file missing for {source_key}"
                        )

        for analysis_key, flag_info in ctx.segment_flags.items():
            source_key = analysis_key.split('_')[0]

            # Skip audio validation for subs-only stepping (no audio to correct)
            if flag_info.get('subs_only', False):
                # For subs-only, just verify EDL was stored
                if source_key not in ctx.stepping_edls:
                    errors.append(
                        f"Stepping correction (subs-only) failed for {source_key}: "
                        f"No EDL stored for subtitle adjustment"
                    )
                continue

            corrected_items = [
                item for item in ctx.extracted_items
                if (item.track.source == source_key and
                    item.track.type == TrackType.AUDIO and
                    item.is_corrected and
                    not item.is_preserved)
            ]
            if not corrected_items:
                errors.append(
                    f"Stepping correction failed for {source_key}: "
                    f"No corrected track found in extraction list"
                )
            else:
                for item in corrected_items:
                    if item.track.props.codec_id != "FLAC":
                        errors.append(
                            f"Stepping corrected track for {source_key} is not FLAC: "
                            f"{item.track.props.codec_id}"
                        )
                    if not item.extracted_path or not item.extracted_path.exists():
                        errors.append(
                            f"Stepping corrected file missing for {source_key}"
                        )

        if errors:
            raise PipelineValidationError(
                "Audio correction validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

    @staticmethod
    def validate_subtitles(ctx: Context) -> None:
        """
        Validates subtitle processing results.
        Raises PipelineValidationError if validation fails.
        """
        errors = []

        subtitle_items = [
            item for item in ctx.extracted_items
            if item.track.type == TrackType.SUBTITLES
        ]

        for item in subtitle_items:
            # CRITICAL FIX: Skip validation for preserved tracks (original image-based subtitles)
            # Preserved tracks are created when OCR is performed to keep the original .sub/.idx files
            # alongside the new OCR'd text subtitles. These preserved tracks should NOT be validated
            # for OCR conversion since they're intentionally kept in their original format.
            if item.is_preserved:
                continue

            if item.perform_ocr:
                if item.extracted_path:
                    ext = item.extracted_path.suffix.lower()
                    if ext not in ['.srt', '.ass', '.ssa']:
                        errors.append(
                            f"OCR track '{item.track.props.name}' has wrong extension: {ext}"
                        )

            if item.convert_to_ass:
                if item.extracted_path:
                    ext = item.extracted_path.suffix.lower()
                    if ext not in ['.ass', '.ssa']:
                        errors.append(
                            f"ASS conversion failed for '{item.track.props.name}': "
                            f"file is {ext}"
                        )

            if item.extracted_path and not item.extracted_path.exists():
                errors.append(
                    f"Subtitle file missing: {item.extracted_path}"
                )

        if errors:
            raise PipelineValidationError(
                "Subtitle processing validation failed:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )

    @staticmethod
    def validate_mux(ctx: Context) -> None:
        """
        Validates merge planning results.
        Raises PipelineValidationError if validation fails.
        """
        if not ctx.tokens:
            raise PipelineValidationError(
                "Merge planning failed: No mkvmerge command tokens generated"
            )

        errors = []
        path_flags = {'--chapters', '--attach-file'}
        in_parens = False

        for i, token in enumerate(ctx.tokens):
            if token == '(':
                in_parens = True
                continue
            if token == ')':
                in_parens = False
                continue

            prev_token = ctx.tokens[i - 1] if i > 0 else ''

            is_path_argument = prev_token in path_flags
            is_input_file = in_parens

            if is_path_argument or is_input_file:
                if not Path(token).exists():
                    errors.append(f"Input file missing from mux command: {token}")

        if errors:
            raise PipelineValidationError(
                "Merge planning validation failed:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )
