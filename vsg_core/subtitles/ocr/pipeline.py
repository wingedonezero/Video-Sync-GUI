# vsg_core/subtitles/ocr/pipeline.py
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

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..data import SubtitleData

from .debug import OCRDebugger, create_debugger
from .output import (
    OCRSubtitleResult,
    OutputConfig,
    create_subtitle_data_from_ocr,
)
from .parsers import SubtitleImage, SubtitleImageParser
from .postprocess import OCRPostProcessor, create_postprocessor
from .report import OCRReport, SubtitleOCRResult, create_report

# VLM engine names that use the VLM pipeline (spotting + pixel verification)
_VLM_ENGINES = {"lfm2vl-450m", "qwen35-4b", "paddleocr-vl"}


@dataclass(slots=True)
class PipelineConfig:
    """Configuration for OCR pipeline."""

    # Input/Output
    language: str = "eng"
    output_format: str = "ass"

    # Confidence
    low_confidence_threshold: float = 60.0

    # Reporting
    generate_report: bool = True

    # Debug output - saves images and text for problem subtitles
    debug_output: bool = False


@dataclass(slots=True)
class PipelineResult:
    """Result of OCR pipeline execution."""

    success: bool = False
    output_path: Path | None = None
    report_path: Path | None = None
    report_summary: dict = field(default_factory=dict)
    subtitle_count: int = 0
    duration_seconds: float = 0.0
    error: str | None = None

    # Unified SubtitleData (when return_subtitle_data=True)
    subtitle_data: Optional["SubtitleData"] = None


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
        debug_output_dir: Path | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ):
        """
        Initialize OCR pipeline.

        Args:
            settings_dict: Application settings dictionary
            work_dir: Working directory for temp files
            logs_dir: Directory for reports
            debug_output_dir: Directory for debug output (if None, uses logs_dir)
            progress_callback: Optional callback for progress updates
                              Signature: callback(message: str, progress: float)
        """
        self.settings = settings_dict
        self.work_dir = Path(work_dir)
        self.logs_dir = Path(logs_dir)
        self.debug_output_dir = Path(debug_output_dir) if debug_output_dir else self.logs_dir
        self.progress_callback = progress_callback

        # Use work_dir directly (caller already provides ocr-specific dir)
        self.ocr_work_dir = self.work_dir
        self.ocr_work_dir.mkdir(parents=True, exist_ok=True)

        # Initialize configuration
        self.config = self._create_config()

        # Initialize components (lazily)
        self._postprocessor: OCRPostProcessor | None = None
        self._vlm_backend = None  # VLM backend (loaded in _process_subtitles_vlm)

    def _create_config(self) -> PipelineConfig:
        """Create pipeline config from settings."""
        return PipelineConfig(
            language=self.settings.get("ocr_language", "eng"),
            output_format=self.settings.get("ocr_output_format", "ass"),
            low_confidence_threshold=self.settings.get(
                "ocr_low_confidence_threshold", 60.0
            ),
            generate_report=self.settings.get("ocr_generate_report", True),
            debug_output=self.settings.get("ocr_debug_output", False),
        )

    @property
    def postprocessor(self) -> OCRPostProcessor:
        """Lazy initialization of post-processor."""
        if self._postprocessor is None:
            self._postprocessor = create_postprocessor(self.settings)
        return self._postprocessor

    def process(
        self,
        input_path: Path,
        output_path: Path | None = None,
        track_id: int = 0,
        return_subtitle_data: bool = True,
    ) -> PipelineResult:
        """
        Process a subtitle file through the OCR pipeline.

        Args:
            input_path: Path to input file (.idx for VobSub, .sup for PGS)
            output_path: Optional output path (auto-generated if None)
            track_id: Track ID for organizing work files
            return_subtitle_data: Always returns SubtitleData (kept for API compat).

        Returns:
            PipelineResult with output paths and statistics.
            result.subtitle_data contains the SubtitleData.
        """
        result = PipelineResult()
        start_time = time.time()

        try:
            self._log_progress("Starting OCR pipeline", 0.0)

            # Log which OCR engine is being used
            backend_setting = self.settings.get("ocr_engine", "paddleocr-vl")
            is_vlm = backend_setting in _VLM_ENGINES
            self._log_progress(
                f"Using OCR engine: {backend_setting}", 0.02
            )

            # Step 1: Detect and create parser (raw for VLM)
            self._log_progress("Parsing subtitle file", 0.05)
            parser = SubtitleImageParser.detect_parser(input_path, raw=True)
            if parser is None:
                result.error = f"No parser available for file: {input_path}"
                return result

            # Step 2: Parse input file
            track_work_dir = self.ocr_work_dir / f"track_{track_id}"
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
                    ".ass" if self.config.output_format == "ass" else ".srt"
                )

            # Generate timestamp for both report and debug output
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            report = create_report(
                source_file=str(input_path),
                output_file=str(output_path),
                language=self.config.language,
            )

            # Create debugger (only active if debug_output is enabled)
            debugger = create_debugger(
                logs_dir=self.debug_output_dir,
                base_name=input_path.stem,
                timestamp=timestamp,
                settings_dict=self.settings,
            )

            # Step 4: Process subtitles through VLM pipeline
            if not is_vlm:
                result.error = (
                    f"Backend '{backend_setting}' is not a VLM engine. "
                    f"Traditional OCR backends have been removed. "
                    f"Available VLM engines: {', '.join(_VLM_ENGINES)}"
                )
                return result

            ocr_results = self._process_subtitles_vlm(
                subtitle_images, backend_setting, report, debugger
            )

            # Step 5: Finalize report
            report.finalize()
            report.duration_seconds = time.time() - start_time

            # Step 6: Create output
            self._log_progress("Creating output", 0.92)

            # Create SubtitleData with all OCR metadata
            engine_name = backend_setting
            source_res = (
                subtitle_images[0].frame_width if subtitle_images else 720,
                subtitle_images[0].frame_height if subtitle_images else 480,
            )
            # Always use source resolution for PlayRes — OCR coordinates are
            # in source space. Rescaling happens later in style editor if needed.
            output_res = source_res

            # Calculate font size from ratio (% of PlayResY)
            font_ratio = self.settings.get("ocr_font_size_ratio", 5.80)
            calculated_font_size = round(output_res[1] * font_ratio / 100)
            self._log_progress(
                f"Font size: {calculated_font_size}pt ({font_ratio}% of {output_res[1]}p)",
                0.93,
            )

            # Create output config with calculated font size
            output_config = OutputConfig(font_size=calculated_font_size)

            subtitle_data = create_subtitle_data_from_ocr(
                ocr_results=ocr_results,
                source_file=str(input_path),
                engine=engine_name,
                language=self.config.language,
                source_format=parse_result.format_info.get("format", "vobsub").lower(),
                source_resolution=source_res,
                output_resolution=output_res,
                config=output_config,
            )
            result.subtitle_data = subtitle_data
            result.output_path = output_path  # Caller will save later

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

        finally:
            # Clean up resources to prevent memory leaks
            self._cleanup()

        return result

    def _cleanup(self):
        """Release resources held by the pipeline."""
        self.progress_callback = None

        # Clean up VLM backend (releases GPU memory)
        if self._vlm_backend is not None:
            self._vlm_backend.unload()
            self._vlm_backend = None

        self._postprocessor = None

    def _process_subtitles_vlm(
        self,
        subtitle_images: list[SubtitleImage],
        engine_name: str,
        report: OCRReport,
        debugger: OCRDebugger,
    ) -> list[OCRSubtitleResult]:
        """Process subtitles using VLM backend with pixel verification.

        Pipeline:
            1. Send raw image to backend (Spotting mode) → lines + bboxes
            2. Pixel verification: scan raw image vs backend bboxes
               → classify: clean / empty / paddle_empty / outside / bleed
            3. Every line gets \\pos() at its bbox center
            4. Post-process text (dictionary fixes)
        """
        from dataclasses import dataclass

        import numpy as np

        from .annotator import annotate_image, rgba_to_rgb_on_black
        from .vlm_backends import get_vlm_backend

        @dataclass
        class Line:
            """A single detected text line with bbox. Separate from Region
            (which will be used for grouping lines later)."""
            x1: int
            y1: int
            x2: int
            y2: int
            line_id: int = 0
            text: str = ""

            # Compatibility with annotate_image() which reads region_id
            @property
            def region_id(self) -> int:
                return self.line_id

            @property
            def center_x(self) -> int:
                return (self.x1 + self.x2) // 2

            @property
            def center_y(self) -> int:
                return (self.y1 + self.y2) // 2

        logger = logging.getLogger(__name__)
        total = len(subtitle_images)

        # ── Load model ────────────────────────────────────────────────
        self._log_progress(f"Loading model: {engine_name}", 0.10)
        load_start = time.time()
        crop_mode = self.settings.get("ocr_crop_mode", False)
        backend = get_vlm_backend(engine_name, crop_mode=crop_mode)
        backend.load()
        self._vlm_backend = backend
        load_time = time.time() - load_start
        self._log_progress(f"Model loaded in {load_time:.1f}s", 0.15)

        # Check if backend supports direct spotting
        has_spotting_direct = hasattr(backend, "spotting_direct")

        # ── Warmup ────────────────────────────────────────────────────
        self._log_progress("Warming up model...", 0.16)
        sub0 = subtitle_images[0]
        if has_spotting_direct:
            backend.spotting_direct(sub0.image)
        else:
            # Legacy path for non-paddle backends
            from .region_detector import detect_regions_pixel
            rgb0 = rgba_to_rgb_on_black(sub0.image)
            regions0 = detect_regions_pixel(sub0.image)
            if regions0:
                if backend.uses_annotated:
                    ann0 = annotate_image(rgb0, regions0)
                    backend.ocr(ann0, regions0)
                else:
                    backend.ocr(rgb0, regions0, raw_image=rgb0)

        # ── Process subtitles ─────────────────────────────────────────
        ocr_results: list[OCRSubtitleResult] = []
        ocr_start = time.time()
        ocr_times: list[float] = []

        # Pixel verification constants (same as validated test script)
        PIXEL_THRESHOLD = 10
        BBOX_MARGIN = 5
        MIN_OUTSIDE_PIXELS = 50
        BLEED_DISTANCE = 8  # px from bbox edge to count as bleed

        for i, sub_image in enumerate(subtitle_images):
            # Progress every 25 subs
            if i % 25 == 0 or i == total - 1:
                elapsed = time.time() - ocr_start
                avg_ms = (elapsed / max(i, 1)) * 1000
                eta = (total - i) * avg_ms / 1000
                progress = 0.18 + (0.72 * i / total)
                self._log_progress(
                    f"OCR {i+1}/{total} "
                    f"({avg_ms:.0f}ms/sub, ETA {eta:.0f}s)",
                    progress,
                )

            sub_start = time.time()
            frame_h = sub_image.image.shape[0]
            frame_w = sub_image.image.shape[1]

            # ── Step 1: Run backend OCR ──────────────────────────────
            if has_spotting_direct:
                vl_lines = backend.spotting_direct(sub_image.image)
            else:
                # Legacy: pixel regions → backend.ocr()
                from .region_detector import detect_regions_pixel
                rgb = rgba_to_rgb_on_black(sub_image.image)
                px_regions = detect_regions_pixel(sub_image.image)
                if not px_regions:
                    vl_lines = []
                elif backend.uses_annotated:
                    ann = annotate_image(rgb, px_regions)
                    vlm_results = backend.ocr(ann, px_regions)
                    vl_lines = [
                        {"text": vr.text, "bbox": vr.vl_bbox}
                        for vr in vlm_results if vr.text
                    ]
                else:
                    vlm_results = backend.ocr(rgb, px_regions, raw_image=rgb)
                    vl_lines = [
                        {"text": vr.text, "bbox": vr.vl_bbox}
                        for vr in vlm_results if vr.text
                    ]

            # Sort lines by reading order: top→bottom, then left→right
            vl_lines.sort(
                key=lambda vl: (vl["bbox"][1], vl["bbox"][0])
                if vl.get("bbox") else (9999, 9999)
            )

            sub_ms = (time.time() - sub_start) * 1000
            ocr_times.append(sub_ms)

            # ── Step 2: Pixel verification ───────────────────────────
            # Get pixel mask from raw image
            if sub_image.image.ndim == 3 and sub_image.image.shape[2] == 4:
                mask = sub_image.image[:, :, 3]
            elif sub_image.image.ndim == 3:
                import cv2 as _cv2
                mask = _cv2.cvtColor(sub_image.image, _cv2.COLOR_RGB2GRAY)
            else:
                mask = sub_image.image

            max_pixel = int(np.max(mask)) if mask.size > 0 else 0
            has_pixels = max_pixel > PIXEL_THRESHOLD
            has_lines = len(vl_lines) > 0 and any(vl["text"] for vl in vl_lines)

            if not has_pixels and not has_lines:
                # Truly empty — no pixels, no OCR
                status = "empty"
                debugger.add_verification_result(
                    sub_image.index, status, {"max_pixel": max_pixel}
                )
                if self.config.debug_output:
                    debugger.add_subtitle(
                        sub_image.index, sub_image.start_time,
                        sub_image.end_time, "", 0.0, sub_image.image,
                    )
                continue

            if has_pixels and not has_lines:
                # Paddle returned nothing but pixels exist
                status = "paddle_empty"
                total_pixels = int(np.sum(mask > PIXEL_THRESHOLD))
                debugger.add_verification_result(
                    sub_image.index, status,
                    {"total_pixels": total_pixels, "max_pixel": max_pixel},
                )
                if self.config.debug_output:
                    debugger.add_subtitle(
                        sub_image.index, sub_image.start_time,
                        sub_image.end_time, "[paddle_empty]", 0.0,
                        sub_image.image,
                    )
                    # Save annotated (will show empty — no boxes)
                    rgb_debug = rgba_to_rgb_on_black(sub_image.image)
                    debugger.add_annotated_image(sub_image.index, rgb_debug)
                continue

            # Has lines — check if pixels are covered by bboxes
            # Build coverage mask from all line bboxes
            covered = np.zeros(mask.shape, dtype=bool)
            for vl in vl_lines:
                if vl["bbox"]:
                    bx1, by1, bx2, by2 = vl["bbox"]
                    # Apply margin
                    bx1 = max(0, bx1 - BBOX_MARGIN)
                    by1 = max(0, by1 - BBOX_MARGIN)
                    bx2 = min(frame_w, bx2 + BBOX_MARGIN)
                    by2 = min(frame_h, by2 + BBOX_MARGIN)
                    covered[by1:by2, bx1:bx2] = True

            # Find pixels outside all bboxes
            pixel_mask = mask > PIXEL_THRESHOLD
            outside_mask = pixel_mask & ~covered
            outside_count = int(np.sum(outside_mask))

            if outside_count >= MIN_OUTSIDE_PIXELS:
                # Check if it's bleed (touching a bbox edge) or truly outside
                is_bleed = False
                if vl_lines:
                    # Expand bboxes by BLEED_DISTANCE and recheck
                    bleed_covered = np.zeros(mask.shape, dtype=bool)
                    for vl in vl_lines:
                        if vl["bbox"]:
                            bx1, by1, bx2, by2 = vl["bbox"]
                            bx1 = max(0, bx1 - BBOX_MARGIN - BLEED_DISTANCE)
                            by1 = max(0, by1 - BBOX_MARGIN - BLEED_DISTANCE)
                            bx2 = min(frame_w, bx2 + BBOX_MARGIN + BLEED_DISTANCE)
                            by2 = min(frame_h, by2 + BBOX_MARGIN + BLEED_DISTANCE)
                            bleed_covered[by1:by2, bx1:bx2] = True
                    remaining = int(np.sum(pixel_mask & ~bleed_covered))
                    if remaining < MIN_OUTSIDE_PIXELS:
                        is_bleed = True

                status = "bleed" if is_bleed else "outside"
                debugger.add_verification_result(
                    sub_image.index, status,
                    {"outside_pixels": outside_count},
                )
            else:
                status = "clean"
                debugger.add_verification_result(sub_image.index, status)

            # ── Step 3: Create Line objects from paddle bboxes ────────
            # Used for annotated images and pos_x/pos_y calculation
            # Already sorted by reading order (y1, x1) from Step 1
            lines = []
            for line_idx, vl in enumerate(vl_lines):
                if not vl["text"]:
                    continue
                if vl["bbox"]:
                    bx1, by1, bx2, by2 = vl["bbox"]
                    lines.append(Line(
                        x1=bx1, y1=by1, x2=bx2, y2=by2,
                        line_id=line_idx + 1, text=vl["text"],
                    ))
                else:
                    # No bbox from backend — use full frame as fallback
                    lines.append(Line(
                        x1=0, y1=0, x2=frame_w, y2=frame_h,
                        line_id=line_idx + 1, text=vl["text"],
                    ))

            # ── Step 4: Debug — annotated image + line data ──────────
            if self.config.debug_output:
                rgb_debug = rgba_to_rgb_on_black(sub_image.image)
                # annotate_image reads .region_id, .x1/.y1/.x2/.y2 — Line is compatible
                annotated_img = annotate_image(rgb_debug, lines)
                debugger.add_annotated_image(sub_image.index, annotated_img)

                line_dicts = [
                    {
                        "line_id": ln.line_id,
                        "bbox": [ln.x1, ln.y1, ln.x2, ln.y2],
                        "text": ln.text,
                    }
                    for ln in lines
                ]
                debugger.add_region_data(sub_image.index, line_dicts)

            # ── Step 5: Add subtitle to debugger FIRST ──────────────
            # Must happen before add_unknown_word/add_fix which check
            # if the subtitle exists in the debugger
            full_raw = "\n".join(vl["text"] for vl in vl_lines if vl["text"])
            if self.config.debug_output:
                debugger.add_subtitle(
                    sub_image.index, sub_image.start_time,
                    sub_image.end_time, full_raw, 90.0,
                    sub_image.image, raw_ocr_text=full_raw,
                )

            # ── Step 6: Build one OCRSubtitleResult per line ─────────
            # Each line gets its own \pos() at its own bbox center
            if not lines:
                continue

            for ln in lines:
                raw_text = ln.text

                # Post-process
                processed_text = raw_text
                fixes = {}
                unknown = []
                try:
                    post_result = self.postprocessor.process(
                        raw_text,
                        confidence=90.0,
                        timestamp=sub_image.start_time,
                    )
                    processed_text = post_result.text
                    fixes = post_result.fixes_applied
                    unknown = post_result.unknown_words

                    for word in post_result.unknown_words:
                        report.add_unknown_word(
                            word=word,
                            context=post_result.text[:50],
                            timestamp=sub_image.start_time,
                            confidence=90.0,
                        )
                        debugger.add_unknown_word(sub_image.index, word)

                    if post_result.was_modified:
                        for fix_name, fix_count in post_result.fixes_applied.items():
                            debugger.add_fix(
                                sub_image.index,
                                fix_name,
                                f"Applied {fix_count} time(s)",
                                original_text=raw_text,
                            )
                except Exception as e:
                    logger.debug(
                        f"Post-processing error on sub {sub_image.index}: {e}"
                    )

                ocr_result = OCRSubtitleResult(
                    index=sub_image.index,
                    start_ms=float(sub_image.start_ms),
                    end_ms=float(sub_image.end_ms),
                    text=processed_text,
                    confidence=90.0,
                    raw_ocr_text=raw_text,
                    fixes_applied=fixes,
                    unknown_words=unknown,
                    x=ln.x1,
                    y=ln.y1,
                    width=ln.x2 - ln.x1,
                    height=ln.y2 - ln.y1,
                    frame_width=frame_w,
                    frame_height=frame_h,
                    is_forced=sub_image.is_forced,
                    pos_x=ln.center_x,
                    pos_y=ln.center_y,
                )
                ocr_results.append(ocr_result)

                report.add_subtitle_result(
                    SubtitleOCRResult(
                        index=sub_image.index,
                        timestamp_start=sub_image.start_time,
                        timestamp_end=sub_image.end_time,
                        text=processed_text,
                        confidence=90.0,
                        fixes_applied=fixes if isinstance(fixes, dict) else {},
                        unknown_words=unknown if isinstance(unknown, list) else [],
                        is_positioned=True,
                    )
                )

        # ── Summary ───────────────────────────────────────────────────
        total_time = time.time() - ocr_start
        avg_ms = sum(ocr_times) / max(len(ocr_times), 1)

        summary = (
            f"OCR complete: {len(ocr_results)} events from {total} subs "
            f"in {total_time:.1f}s ({avg_ms:.0f}ms/sub avg)"
        )
        self._log_progress(summary, 0.90)
        logger.info(summary)

        # Verification summary
        vc = debugger.verification_counts
        v_total = sum(vc.values())
        if v_total > 0:
            self._log_progress(
                f"Verification: {vc.get('clean', 0)} clean, "
                f"{vc.get('empty', 0)} empty, "
                f"{vc.get('paddle_empty', 0)} paddle_empty, "
                f"{vc.get('outside', 0)} outside, "
                f"{vc.get('bleed', 0)} bleed",
                0.91,
            )

        return ocr_results

    def _get_report_path(self, input_path: Path, timestamp: str) -> Path:
        """Generate report file path."""
        report_name = f"{input_path.stem}_ocr_report_{timestamp}.json"
        return self.logs_dir / report_name

    def _log_progress(self, message: str, progress: float):
        """Log progress if callback is available."""
        if self.progress_callback:
            self.progress_callback(message, progress)
