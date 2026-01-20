# vsg_core/subtitles/ocr/pipeline.py
# -*- coding: utf-8 -*-
"""
OCR Pipeline - Main Entry Point

Orchestrates the complete OCR workflow:
    1. Parse source file (VobSub/PGS)
    2. Preprocess images
    3. Run OCR with confidence tracking
    4. Post-process text (pattern fixes, validation)
    5. Generate output (ASS/SRT)
    6. Create report

Usage:
    pipeline = OCRPipeline(settings_dict, work_dir, logs_dir)
    result = pipeline.process(input_path, output_path)
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .parsers import SubtitleImageParser, SubtitleImage
from .preprocessing import ImagePreprocessor, PreprocessingConfig, create_preprocessor
from .engine import OCREngine, OCRConfig, create_ocr_engine
from .postprocess import OCRPostProcessor, PostProcessConfig, create_postprocessor
from .output import SubtitleWriter, OutputConfig, SubtitleEntry, create_writer
from .report import OCRReport, SubtitleOCRResult, create_report
from .debug import OCRDebugger, create_debugger


@dataclass
class PipelineConfig:
    """Configuration for OCR pipeline."""
    # Input/Output
    language: str = 'eng'
    output_format: str = 'ass'

    # Position handling
    preserve_positions: bool = True
    bottom_threshold_percent: float = 75.0

    # Confidence
    low_confidence_threshold: float = 60.0

    # Reporting
    generate_report: bool = True
    save_debug_images: bool = False

    # Debug output - saves images and text for problem subtitles
    debug_output: bool = False

    # Processing
    max_workers: int = 1  # For future parallel processing


@dataclass
class PipelineResult:
    """Result of OCR pipeline execution."""
    success: bool = False
    output_path: Optional[Path] = None
    report_path: Optional[Path] = None
    report_summary: dict = field(default_factory=dict)
    subtitle_count: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


class OCRPipeline:
    """
    Main OCR pipeline for converting image-based subtitles to text.

    Coordinates all OCR components and manages the workflow.
    """

    def __init__(
        self,
        settings_dict: dict,
        work_dir: Path,
        logs_dir: Path,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ):
        """
        Initialize OCR pipeline.

        Args:
            settings_dict: Application settings dictionary
            work_dir: Working directory for temp files
            logs_dir: Directory for reports
            progress_callback: Optional callback for progress updates
                              Signature: callback(message: str, progress: float)
        """
        self.settings = settings_dict
        self.work_dir = Path(work_dir)
        self.logs_dir = Path(logs_dir)
        self.progress_callback = progress_callback

        # Use work_dir directly (caller already provides ocr-specific dir)
        self.ocr_work_dir = self.work_dir
        self.ocr_work_dir.mkdir(parents=True, exist_ok=True)

        # Initialize configuration
        self.config = self._create_config()

        # Initialize components (lazily)
        self._preprocessor: Optional[ImagePreprocessor] = None
        self._engine: Optional[OCREngine] = None
        self._postprocessor: Optional[OCRPostProcessor] = None
        self._writer: Optional[SubtitleWriter] = None

    def _create_config(self) -> PipelineConfig:
        """Create pipeline config from settings."""
        return PipelineConfig(
            language=self.settings.get('ocr_language', 'eng'),
            output_format=self.settings.get('ocr_output_format', 'ass'),
            preserve_positions=self.settings.get('ocr_preserve_positions', True),
            bottom_threshold_percent=self.settings.get('ocr_bottom_threshold', 75.0),
            low_confidence_threshold=self.settings.get('ocr_low_confidence_threshold', 60.0),
            generate_report=self.settings.get('ocr_generate_report', True),
            save_debug_images=self.settings.get('ocr_save_debug_images', False),
            debug_output=self.settings.get('ocr_debug_output', False),
        )

    @property
    def preprocessor(self) -> ImagePreprocessor:
        """Lazy initialization of preprocessor."""
        if self._preprocessor is None:
            self._preprocessor = create_preprocessor(
                self.settings,
                self.ocr_work_dir if self.config.save_debug_images else None
            )
        return self._preprocessor

    @property
    def engine(self) -> OCREngine:
        """Lazy initialization of OCR engine."""
        if self._engine is None:
            self._engine = create_ocr_engine(self.settings)
        return self._engine

    @property
    def postprocessor(self) -> OCRPostProcessor:
        """Lazy initialization of post-processor."""
        if self._postprocessor is None:
            self._postprocessor = create_postprocessor(self.settings)
        return self._postprocessor

    @property
    def writer(self) -> SubtitleWriter:
        """Lazy initialization of subtitle writer."""
        if self._writer is None:
            self._writer = create_writer(self.settings)
        return self._writer

    def process(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        track_id: int = 0
    ) -> PipelineResult:
        """
        Process a subtitle file through the OCR pipeline.

        Args:
            input_path: Path to input file (.idx for VobSub, .sup for PGS)
            output_path: Optional output path (auto-generated if None)
            track_id: Track ID for organizing work files

        Returns:
            PipelineResult with output paths and statistics
        """
        result = PipelineResult()
        start_time = time.time()

        try:
            self._log_progress("Starting OCR pipeline", 0.0)

            # Step 1: Detect and create parser
            self._log_progress("Parsing subtitle file", 0.05)
            parser = SubtitleImageParser.detect_parser(input_path)
            if parser is None:
                result.error = f"No parser available for file: {input_path}"
                return result

            # Step 2: Parse input file
            track_work_dir = self.ocr_work_dir / f'track_{track_id}'
            track_work_dir.mkdir(parents=True, exist_ok=True)

            parse_result = parser.parse(input_path, track_work_dir)
            if not parse_result.success:
                result.error = f"Failed to parse: {'; '.join(parse_result.errors)}"
                return result

            subtitle_images = parse_result.subtitles
            result.subtitle_count = len(subtitle_images)

            if not subtitle_images:
                result.error = "No subtitles found in file"
                return result

            self._log_progress(f"Found {len(subtitle_images)} subtitles", 0.10)

            # Step 3: Initialize report and debugger with same timestamp
            if output_path is None:
                output_path = input_path.with_suffix(
                    '.ass' if self.config.output_format == 'ass' else '.srt'
                )

            # Generate timestamp for both report and debug output
            timestamp = time.strftime('%Y%m%d_%H%M%S')

            report = create_report(
                source_file=str(input_path),
                output_file=str(output_path),
                language=self.config.language
            )

            # Create debugger (only active if debug_output is enabled)
            debugger = create_debugger(
                logs_dir=self.logs_dir,
                base_name=input_path.stem,
                timestamp=timestamp,
                settings_dict=self.settings
            )

            # Step 4: Process each subtitle
            output_entries: List[SubtitleEntry] = []
            last_logged_percent = -1

            for i, sub_image in enumerate(subtitle_images):
                progress = 0.10 + (0.80 * i / len(subtitle_images))
                # Only log at 10% intervals to reduce log spam
                current_percent = int((i / len(subtitle_images)) * 100)
                if current_percent >= last_logged_percent + 10:
                    self._log_progress(f"Processing subtitles ({current_percent}%)", progress)
                    last_logged_percent = current_percent

                try:
                    entry, sub_result = self._process_single_subtitle(
                        sub_image, report, debugger
                    )
                    if entry is not None:
                        output_entries.append(entry)
                        report.add_subtitle_result(sub_result)
                except Exception as e:
                    report.add_subtitle_result(SubtitleOCRResult(
                        index=sub_image.index,
                        timestamp_start=sub_image.start_time,
                        timestamp_end=sub_image.end_time,
                        text="",
                        confidence=0.0,
                    ))

            # Step 5: Finalize report
            report.finalize()
            report.duration_seconds = time.time() - start_time

            # Step 6: Write output file
            self._log_progress("Writing output file", 0.92)
            self.writer.write(output_entries, output_path)
            result.output_path = output_path

            # Step 7: Save report
            if self.config.generate_report:
                self._log_progress("Saving report", 0.96)
                report_path = self._get_report_path(input_path, timestamp)
                report.save(report_path)
                result.report_path = report_path
                result.report_summary = report.to_summary()

            # Step 8: Save debug output (if enabled)
            if self.config.debug_output:
                self._log_progress("Saving debug output", 0.98)
                debugger.save()

            result.success = True
            result.duration_seconds = time.time() - start_time
            self._log_progress("OCR complete", 1.0)

        except Exception as e:
            result.error = str(e)
            result.duration_seconds = time.time() - start_time

        return result

    def _process_single_subtitle(
        self,
        sub_image: SubtitleImage,
        report: OCRReport,
        debugger: OCRDebugger
    ) -> tuple[Optional[SubtitleEntry], SubtitleOCRResult]:
        """
        Process a single subtitle through the pipeline.

        Returns:
            Tuple of (SubtitleEntry for output, SubtitleOCRResult for report)
        """
        # Preprocess image
        preprocessed = self.preprocessor.preprocess(
            sub_image,
            self.ocr_work_dir if self.config.save_debug_images else None
        )

        # Run OCR - use line splitting with PSM 7 for better accuracy
        # This splits multi-line subtitles and OCRs each line separately
        ocr_result = self.engine.ocr_lines_separately(preprocessed.image)

        if not ocr_result.success:
            return None, SubtitleOCRResult(
                index=sub_image.index,
                timestamp_start=sub_image.start_time,
                timestamp_end=sub_image.end_time,
                text="",
                confidence=0.0,
            )

        # Store raw OCR text before post-processing
        raw_ocr_text = ocr_result.text

        # Post-process text
        post_result = self.postprocessor.process(
            ocr_result.text,
            confidence=ocr_result.average_confidence,
            timestamp=sub_image.start_time
        )

        # Add to debugger (it checks if enabled internally)
        debugger.add_subtitle(
            index=sub_image.index,
            start_time=sub_image.start_time,
            end_time=sub_image.end_time,
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            image=preprocessed.image
        )

        # Track unknown words
        for word in post_result.unknown_words:
            report.add_unknown_word(
                word=word,
                context=post_result.text[:50],
                timestamp=sub_image.start_time,
                confidence=ocr_result.average_confidence
            )
            # Also track in debugger
            debugger.add_unknown_word(sub_image.index, word)

        # Track fixes applied
        if post_result.was_modified:
            for fix_name, fix_count in post_result.fixes_applied.items():
                debugger.add_fix(
                    sub_image.index,
                    fix_name,
                    f"Applied {fix_count} time(s)",
                    original_text=raw_ocr_text
                )

        # Track low confidence
        if ocr_result.low_confidence:
            report.add_low_confidence_line(
                text=post_result.text,
                timestamp=sub_image.start_time,
                confidence=ocr_result.average_confidence,
                subtitle_index=sub_image.index,
                potential_issues=list(post_result.fixes_applied.keys())
            )

        # Determine if positioned
        is_positioned = not sub_image.is_bottom_positioned(
            self.config.bottom_threshold_percent
        )

        # Create output entry
        entry = SubtitleEntry(
            index=sub_image.index,
            start_ms=sub_image.start_ms,
            end_ms=sub_image.end_ms,
            text=post_result.text,
            x=sub_image.x,
            y=sub_image.y,
            frame_width=sub_image.frame_width,
            frame_height=sub_image.frame_height,
            is_forced=sub_image.is_forced,
        )

        # Create report entry
        sub_result = SubtitleOCRResult(
            index=sub_image.index,
            timestamp_start=sub_image.start_time,
            timestamp_end=sub_image.end_time,
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            was_modified=post_result.was_modified,
            fixes_applied=dict(post_result.fixes_applied),
            unknown_words=post_result.unknown_words,
            position_x=sub_image.x,
            position_y=sub_image.y,
            is_positioned=is_positioned,
        )

        return entry, sub_result

    def _get_report_path(self, input_path: Path, timestamp: str) -> Path:
        """Generate report file path."""
        report_name = f"{input_path.stem}_ocr_report_{timestamp}.json"
        return self.logs_dir / report_name

    def _log_progress(self, message: str, progress: float):
        """Log progress if callback is available."""
        if self.progress_callback:
            self.progress_callback(message, progress)


def run_ocr_pipeline(
    input_path: Path,
    output_path: Optional[Path],
    settings_dict: dict,
    work_dir: Path,
    logs_dir: Path,
    track_id: int = 0,
    progress_callback: Optional[Callable[[str, float], None]] = None
) -> PipelineResult:
    """
    Convenience function to run the OCR pipeline.

    Args:
        input_path: Path to input subtitle file
        output_path: Optional output path
        settings_dict: Application settings
        work_dir: Working directory
        logs_dir: Logs directory
        track_id: Track ID for work organization
        progress_callback: Optional progress callback

    Returns:
        PipelineResult with output paths and statistics
    """
    pipeline = OCRPipeline(
        settings_dict=settings_dict,
        work_dir=work_dir,
        logs_dir=logs_dir,
        progress_callback=progress_callback
    )

    return pipeline.process(
        input_path=Path(input_path),
        output_path=Path(output_path) if output_path else None,
        track_id=track_id
    )
