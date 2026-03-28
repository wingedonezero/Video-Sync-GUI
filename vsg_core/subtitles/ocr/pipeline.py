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
import queue
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..data import SubtitleData

from .debug import OCRDebugger, create_debugger
from .backends import OCRBackend, create_ocr_engine_v2
from .output import (
    LineRegion,
    OCRSubtitleResult,
    OutputConfig,
    create_subtitle_data_from_ocr,
)
from .parsers import SubtitleImage, SubtitleImageParser
from .postprocess import OCRPostProcessor, create_postprocessor
from .preprocessing import ImagePreprocessor, create_preprocessor
from .report import OCRReport, SubtitleOCRResult, create_report

# VLM engine names that use the new region-based pipeline
_VLM_ENGINES = {"lfm2vl-450m", "qwen35-4b", "paddleocr-vl"}


@dataclass(slots=True)
class PipelineConfig:
    """Configuration for OCR pipeline."""

    # Input/Output
    language: str = "eng"
    output_format: str = "ass"

    # Position handling
    preserve_positions: bool = True
    bottom_threshold_percent: float = 75.0
    top_threshold_percent: float = 40.0

    # Confidence
    low_confidence_threshold: float = 60.0

    # Reporting
    generate_report: bool = True
    save_debug_images: bool = False

    # Debug output - saves images and text for problem subtitles
    debug_output: bool = False

    # Processing
    max_workers: int = 1  # For future parallel processing


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
        self._preprocessor: ImagePreprocessor | None = None
        self._engine: OCRBackend | None = None
        self._postprocessor: OCRPostProcessor | None = None
        self._vlm_backend = None  # VLM backend (loaded in _process_subtitles_vlm)
        self._extra_engines: list = []  # Additional engines for parallel processing

    def _create_config(self) -> PipelineConfig:
        """Create pipeline config from settings."""
        return PipelineConfig(
            language=self.settings.get("ocr_language", "eng"),
            output_format=self.settings.get("ocr_output_format", "ass"),
            preserve_positions=self.settings.get("ocr_preserve_positions", True),
            bottom_threshold_percent=self.settings.get("ocr_bottom_threshold", 75.0),
            top_threshold_percent=self.settings.get("ocr_top_threshold", 40.0),
            low_confidence_threshold=self.settings.get(
                "ocr_low_confidence_threshold", 60.0
            ),
            generate_report=self.settings.get("ocr_generate_report", True),
            save_debug_images=self.settings.get("ocr_save_debug_images", False),
            debug_output=self.settings.get("ocr_debug_output", False),
            max_workers=self.settings.get("ocr_max_workers", 1),
        )

    @property
    def preprocessor(self) -> ImagePreprocessor:
        """Lazy initialization of preprocessor."""
        if self._preprocessor is None:
            self._preprocessor = create_preprocessor(
                self.settings,
                self.ocr_work_dir if self.config.save_debug_images else None,
            )
        return self._preprocessor

    def _create_single_engine(self):
        """Create a single OCR engine instance."""
        logger = logging.getLogger(__name__)
        engine = create_ocr_engine_v2(self.settings)
        logger.info(f"Created OCR backend: {engine.name}")
        return engine

    @property
    def engine(self):
        """Lazy initialization of OCR engine.

        Returns configured OCRBackend based on settings.
        """
        if self._engine is None:
            logger = logging.getLogger(__name__)
            backend = self.settings.get("ocr_engine", "easyocr")
            logger.info(f"OCR engine setting: '{backend}'")
            self._engine = self._create_single_engine()
        return self._engine

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
            backend_setting = self.settings.get("ocr_engine", "easyocr")
            is_vlm = backend_setting in _VLM_ENGINES

            if is_vlm:
                self._log_progress(
                    f"Using VLM OCR engine: {backend_setting}", 0.02
                )
            else:
                # Access engine property to initialize it and get the actual backend name
                engine_name = getattr(self.engine, "name", "easyocr")
                self._log_progress(
                    f"Using OCR engine: {engine_name} (setting: {backend_setting})",
                    0.02,
                )

            # Step 1: Detect and create parser (raw for VLM, standard for traditional)
            self._log_progress("Parsing subtitle file", 0.05)
            parser = SubtitleImageParser.detect_parser(input_path, raw=is_vlm)
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

            # Step 4: Process each subtitle
            if is_vlm:
                ocr_results = self._process_subtitles_vlm(
                    subtitle_images, backend_setting, report, debugger
                )
            else:
                max_workers = max(1, self.config.max_workers)

                # Reduce workers for small subtitle counts to avoid race conditions
                # PaddleOCR can segfault if processing finishes before all workers initialize
                subtitle_count = len(subtitle_images)
                if subtitle_count < 30 and max_workers > 1:
                    original_workers = max_workers
                    max_workers = 1
                    self._log_progress(
                        f"Using 1 worker for {subtitle_count} subtitles "
                        f"(configured: {original_workers}, threshold: 30)",
                        0.10,
                    )

                if max_workers > 1:
                    ocr_results = self._process_subtitles_parallel(
                        subtitle_images, max_workers, report, debugger
                    )
                else:
                    ocr_results = self._process_subtitles_sequential(
                        subtitle_images, report, debugger
                    )

            # Step 5: Finalize report
            report.finalize()
            report.duration_seconds = time.time() - start_time

            # Step 6: Create output
            self._log_progress("Creating output", 0.92)

            # Create SubtitleData with all OCR metadata
            engine_name = (
                backend_setting if is_vlm
                else getattr(self.engine, "name", "easyocr")
            )
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
        # Clear progress callback to break reference cycles
        self.progress_callback = None

        # Clean up OCR backend (releases GPU memory, models)
        if self._engine is not None:
            if hasattr(self._engine, "cleanup"):
                self._engine.cleanup()
            self._engine = None

        # Clean up extra engines from parallel processing
        for engine in self._extra_engines:
            if hasattr(engine, "cleanup"):
                engine.cleanup()
        self._extra_engines.clear()

        # Clean up VLM backend
        if self._vlm_backend is not None:
            self._vlm_backend.unload()
            self._vlm_backend = None

        # Clear other cached objects
        self._preprocessor = None
        self._postprocessor = None

    def _process_subtitles_vlm(
        self,
        subtitle_images: list[SubtitleImage],
        engine_name: str,
        report: OCRReport,
        debugger: OCRDebugger,
    ) -> list[OCRSubtitleResult]:
        """Process subtitles using VLM backend with region detection."""
        import numpy as np
        import torch

        from .annotator import annotate_image, rgba_to_rgb_on_black
        from .region_detector import detect_regions_pixel
        from .vlm_backends import get_vlm_backend

        logger = logging.getLogger(__name__)
        total = len(subtitle_images)

        # ── Load model ────────────────────────────────────────────────
        self._log_progress(f"Loading model: {engine_name}", 0.10)
        load_start = time.time()
        backend = get_vlm_backend(engine_name)
        backend.load()
        self._vlm_backend = backend
        load_time = time.time() - load_start

        vram = torch.cuda.memory_allocated() / 1024**3
        self._log_progress(
            f"Model loaded in {load_time:.1f}s (VRAM: {vram:.2f}GB)", 0.15
        )

        # ── Warmup ────────────────────────────────────────────────────
        self._log_progress("Warming up model...", 0.16)
        sub0 = subtitle_images[0]
        rgb0 = rgba_to_rgb_on_black(sub0.image)
        regions0 = detect_regions_pixel(sub0.image)
        if regions0:
            if backend.uses_annotated:
                ann0 = annotate_image(rgb0, regions0)
                with torch.inference_mode():
                    backend.ocr(ann0, regions0)
            else:
                with torch.inference_mode():
                    backend.ocr(rgb0, regions0, raw_image=rgb0)

        # ── Process subtitles ─────────────────────────────────────────
        ocr_results: list[OCRSubtitleResult] = []
        ocr_start = time.time()
        ocr_times: list[float] = []
        empty_count = 0
        region_counts = {1: 0, 2: 0}  # 1-region, 2+ region
        zone_counts: dict[str, int] = {}
        pos_count = 0

        # Cross-validation tracking (VL bbox vs pixel regions)
        cv_aligned = 0
        cv_flagged: list[tuple[int, int, tuple, str]] = []  # (sub_idx, region_id, vl_bbox, text)

        # Validation tracking (for log + debug)
        wide_region_flags: list[tuple[int, int, int]] = []  # (sub_idx, width, h_gap)
        same_zone_splits: list[tuple[int, str, int]] = []  # (sub_idx, zone, gap_px)
        tiny_regions: list[tuple[int, int, int]] = []  # (sub_idx, w, h)
        huge_regions: list[tuple[int, int, int]] = []  # (sub_idx, w, h)
        very_tall_single: list[tuple[int, int, int]] = []  # (sub_idx, w, h)
        four_plus_regions: list[tuple[int, int]] = []  # (sub_idx, count)
        per_sub_data: list[dict] = []  # full per-sub tracking for debug

        # Line analysis tracking
        from collections import defaultdict
        line_counts: dict[int, int] = defaultdict(int)  # lines_per_region -> count
        all_internal_gaps: list[int] = []  # gaps between lines within regions
        all_inter_gaps: list[int] = []  # gaps between separate regions
        all_region_widths: list[int] = []
        all_region_heights: list[int] = []

        for i, sub_image in enumerate(subtitle_images):
            # Progress every 25 subs (not spammy)
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

            # Step 1: Detect regions
            regions = detect_regions_pixel(sub_image.image)

            if not regions:
                empty_count += 1
                continue

            frame_h = sub_image.image.shape[0]
            frame_w = sub_image.image.shape[1]

            # Track region stats
            n_regions = len(regions)
            if n_regions == 1:
                region_counts[1] = region_counts.get(1, 0) + 1
            elif n_regions >= 2:
                region_counts[2] = region_counts.get(2, 0) + 1
            if n_regions >= 4:
                four_plus_regions.append((sub_image.index, n_regions))

            # Per-sub tracking + line analysis
            import cv2 as _cv2

            _mask = (
                sub_image.image[:, :, 3]
                if sub_image.image.ndim == 3 and sub_image.image.shape[2] == 4
                else _cv2.cvtColor(sub_image.image, _cv2.COLOR_RGB2GRAY)
                if sub_image.image.ndim == 3
                else sub_image.image
            )

            sub_regions_info = []
            for r in regions:
                zone = r.classify_zone(frame_h, frame_w)
                all_region_widths.append(r.width)
                all_region_heights.append(r.height)

                # Line analysis: scan rows within region
                _crop = _mask[r.y1:r.y2, r.x1:r.x2]
                _n_lines = 0
                _max_gap = 0
                if _crop.size > 0:
                    _row_text = np.any(_crop > 10, axis=1)
                    _lines = []
                    _in_l = False
                    _ls = 0
                    for _y, _has in enumerate(_row_text):
                        if _has and not _in_l:
                            _ls = _y
                            _in_l = True
                        elif not _has and _in_l:
                            _lines.append((_ls, _y))
                            _in_l = False
                    if _in_l:
                        _lines.append((_ls, len(_row_text)))
                    _n_lines = len(_lines)
                    for _li in range(1, len(_lines)):
                        _g = _lines[_li][0] - _lines[_li - 1][1]
                        if _g > 0:
                            all_internal_gaps.append(_g)
                        _max_gap = max(_max_gap, _g)

                line_counts[_n_lines] += 1

                sub_regions_info.append({
                    "id": r.region_id, "zone": zone,
                    "bbox": [r.x1, r.y1, r.x2, r.y2],
                    "size": f"{r.width}x{r.height}",
                    "pos": r.needs_pos_tag(frame_h, frame_w),
                    "lines": _n_lines,
                    "max_gap": _max_gap,
                })

            # Inter-region gaps
            if n_regions >= 2:
                _sorted = sorted(regions, key=lambda _r: _r.y1)
                for _ri in range(1, len(_sorted)):
                    _g = _sorted[_ri].y1 - _sorted[_ri - 1].y2
                    if _g > 0:
                        all_inter_gaps.append(_g)
            if n_regions > 1 or any(ri["pos"] for ri in sub_regions_info):
                per_sub_data.append({
                    "index": sub_image.index,
                    "time": sub_image.start_time,
                    "n_regions": n_regions,
                    "regions": sub_regions_info,
                })

            # Anomaly checks
            for r in regions:
                # Tiny region
                if r.width < 10 or r.height < 5:
                    tiny_regions.append((sub_image.index, r.width, r.height))

                # Huge region (>90% width AND >50% height)
                if r.width > frame_w * 0.9 and r.height > frame_h * 0.5:
                    huge_regions.append((sub_image.index, r.width, r.height))

                # Very tall single region (>40% frame, single region only)
                if n_regions == 1 and r.height > frame_h * 0.4:
                    very_tall_single.append(
                        (sub_image.index, r.width, r.height)
                    )

                # Horizontal merge check (wide regions with column gaps)
                if r.width > frame_w * 0.7:
                    _mask = (
                        sub_image.image[:, :, 3]
                        if sub_image.image.ndim == 3
                        and sub_image.image.shape[2] == 4
                        else _cv2.cvtColor(sub_image.image, _cv2.COLOR_RGB2GRAY)
                        if sub_image.image.ndim == 3
                        else sub_image.image
                    )
                    _crop = _mask[r.y1:r.y2, r.x1:r.x2]
                    if _crop.size > 0:
                        _col_text = np.any(_crop > 10, axis=0)
                        _in_c = False
                        _clusters: list[tuple[int, int]] = []
                        _cs = 0
                        for _x, _has in enumerate(_col_text):
                            if _has and not _in_c:
                                _cs = _x
                                _in_c = True
                            elif not _has and _in_c:
                                _clusters.append((_cs, _x))
                                _in_c = False
                        if _in_c:
                            _clusters.append((_cs, len(_col_text)))
                        if len(_clusters) >= 2:
                            _max_gap = max(
                                _clusters[j][0] - _clusters[j - 1][1]
                                for j in range(1, len(_clusters))
                            )
                            if _max_gap > r.width * 0.15 and _max_gap > 30:
                                wide_region_flags.append(
                                    (sub_image.index, r.width, _max_gap)
                                )

            # Same-zone split check
            if n_regions >= 2:
                _sorted_r = sorted(regions, key=lambda _r: _r.y1)
                for _ri in range(1, len(_sorted_r)):
                    _gap = _sorted_r[_ri].y1 - _sorted_r[_ri - 1].y2
                    _z1 = _sorted_r[_ri - 1].classify_zone(frame_h, frame_w)
                    _z2 = _sorted_r[_ri].classify_zone(frame_h, frame_w)
                    if _z1 == _z2 and 0 < _gap < 80:
                        same_zone_splits.append(
                            (sub_image.index, _z1, _gap)
                        )

            # Step 2: Run OCR
            rgb = rgba_to_rgb_on_black(sub_image.image)

            if backend.uses_annotated:
                annotated = annotate_image(rgb, regions)
                with torch.inference_mode():
                    vlm_regions = backend.ocr(annotated, regions)
            else:
                with torch.inference_mode():
                    vlm_regions = backend.ocr(rgb, regions, raw_image=rgb)

            sub_ms = (time.time() - sub_start) * 1000
            ocr_times.append(sub_ms)

            # Step 2b: Cross-validate VL bboxes vs pixel regions (if available)
            has_vl_bboxes = any(
                getattr(vr, "vl_bbox", None) for vr in vlm_regions
            )
            if has_vl_bboxes:
                for vr in vlm_regions:
                    if not vr.vl_bbox or not vr.text:
                        continue
                    vl_cy = (vr.vl_bbox[1] + vr.vl_bbox[3]) / 2
                    matched_region = next(
                        (r for r in regions
                         if r.y1 - 10 <= vl_cy <= r.y2 + 10
                         and r.region_id == vr.region_id),
                        None,
                    )
                    if matched_region is None:
                        cv_flagged.append((
                            sub_image.index,
                            vr.region_id,
                            vr.vl_bbox,
                            vr.text[:40],
                        ))
                    else:
                        cv_aligned += 1

            # Step 3: Add to debugger FIRST (so add_unknown_word/add_fix can find it)
            # Generate annotated image for debug regardless of backend type
            if self.config.debug_output or not hasattr(self, '_debug_annotated'):
                debug_annotated = annotate_image(rgb, regions)

            if self.config.debug_output:
                full_text = " | ".join(
                    vr.text for vr in vlm_regions if vr.text
                )
                debugger.add_subtitle(
                    sub_image.index,
                    sub_image.start_time,
                    sub_image.end_time,
                    full_text,
                    90.0,
                    sub_image.image,
                    raw_ocr_text=full_text,
                )

                # Always save annotated image with region boxes for debug
                debugger.add_annotated_image(sub_image.index, debug_annotated)

                # Save region data
                has_pos = any(
                    r.needs_pos_tag(frame_h, frame_w) for r in regions
                )
                region_dicts = [
                    {
                        "region_id": r.region_id,
                        "zone": r.classify_zone(frame_h, frame_w),
                        "bbox": [r.x1, r.y1, r.x2, r.y2],
                        "needs_pos": r.needs_pos_tag(frame_h, frame_w),
                        "text": next(
                            (vr.text for vr in vlm_regions
                             if vr.region_id == r.region_id),
                            "",
                        ),
                    }
                    for r in regions
                ]
                debugger.add_region_data(
                    sub_image.index, region_dicts, has_pos=has_pos
                )

            # Step 4: Create one OCRSubtitleResult per region
            for vlm_r in vlm_regions:
                if not vlm_r.text:
                    continue

                region = next(
                    (r for r in regions if r.region_id == vlm_r.region_id), None
                )
                if region is None:
                    continue

                zone = region.classify_zone(frame_h, frame_w)
                needs_pos = region.needs_pos_tag(frame_h, frame_w)

                zone_counts[zone] = zone_counts.get(zone, 0) + 1
                if needs_pos:
                    pos_count += 1

                # Post-process text (dictionary fixes, pattern corrections)
                raw_text = vlm_r.text
                processed_text = vlm_r.text
                fixes = {}
                unknown = []

                try:
                    post_result = self.postprocessor.process(
                        vlm_r.text,
                        confidence=90.0,
                        timestamp=sub_image.start_time,
                    )
                    processed_text = post_result.text
                    fixes = post_result.fixes_applied
                    unknown = post_result.unknown_words

                    # Track unknown words in report + debugger
                    for word in post_result.unknown_words:
                        report.add_unknown_word(
                            word=word,
                            context=post_result.text[:50],
                            timestamp=sub_image.start_time,
                            confidence=90.0,
                        )
                        debugger.add_unknown_word(sub_image.index, word)

                    # Track fixes in debugger
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
                    x=region.x1,
                    y=region.y1,
                    width=region.width,
                    height=region.height,
                    frame_width=frame_w,
                    frame_height=frame_h,
                    is_forced=sub_image.is_forced,
                    zone=zone,
                    needs_pos=needs_pos,
                    pos_x=region.center_x,
                    pos_y=region.center_y,
                )
                ocr_results.append(ocr_result)

                # Report tracking
                report.add_subtitle_result(
                    SubtitleOCRResult(
                        index=sub_image.index,
                        timestamp_start=sub_image.start_time,
                        timestamp_end=sub_image.end_time,
                        text=processed_text,
                        confidence=90.0,
                        fixes_applied=fixes if isinstance(fixes, dict) else {},
                        unknown_words=unknown if isinstance(unknown, list) else [],
                        is_positioned=needs_pos,
                    )
                )

            # (debug tracking already done in Step 3 above)

        # ── Summary ───────────────────────────────────────────────────
        total_time = time.time() - ocr_start
        avg_ms = sum(ocr_times) / max(len(ocr_times), 1)

        summary = (
            f"OCR complete: {len(ocr_results)} events from {total} subs "
            f"in {total_time:.1f}s ({avg_ms:.0f}ms/sub avg)"
        )
        self._log_progress(summary, 0.90)
        logger.info(summary)

        # Normal log — one-line summary with percentages
        total_r = sum(zone_counts.values())
        single_pct = region_counts.get(1, 0) / max(total, 1) * 100
        pos_pct = pos_count / max(total_r, 1) * 100
        issues = len(wide_region_flags) + len(same_zone_splits) + len(tiny_regions) + len(huge_regions)
        self._log_progress(
            f"Pixel: {single_pct:.1f}% single-region, "
            f"{pos_pct:.1f}% need \\pos(), "
            f"{issues} issues",
            0.91,
        )
        self._log_progress(
            f"Regions: {region_counts.get(1, 0)} single, "
            f"{region_counts.get(2, 0)} multi, {empty_count} empty, "
            f"{pos_count} positioned",
            0.91,
        )
        if zone_counts:
            zones_str = ", ".join(
                f"{z}={c}" for z, c in sorted(zone_counts.items(), key=lambda x: -x[1])
            )
            self._log_progress(f"Zones: {zones_str}", 0.91)

        # Warnings only if issues found
        if wide_region_flags:
            self._log_progress(
                f"WARNING: Horizontal merge suspects: "
                f"{len(wide_region_flags)} (check debug)",
                0.91,
            )
        if same_zone_splits:
            self._log_progress(
                f"WARNING: Same-zone splits: {len(same_zone_splits)}",
                0.91,
            )
        if tiny_regions:
            self._log_progress(
                f"WARNING: Tiny regions: {len(tiny_regions)}", 0.91
            )

        # Cross-validation summary
        if cv_aligned > 0 or cv_flagged:
            cv_total = cv_aligned + len(cv_flagged)
            self._log_progress(
                f"Cross-validation: {cv_aligned}/{cv_total} aligned, "
                f"{len(cv_flagged)} flagged",
                0.91,
            )
            if cv_flagged:
                for sub_idx, rid, vl_bbox, text in cv_flagged[:5]:
                    self._log_progress(
                        f"  FLAGGED [{sub_idx:04d}] region {rid}: "
                        f"VL bbox {vl_bbox} — {text}",
                        0.91,
                    )
                if len(cv_flagged) > 5:
                    self._log_progress(
                        f"  ... and {len(cv_flagged) - 5} more (see debug)",
                        0.91,
                    )

        # Debug: write full pixel analysis + per-sub detail
        if self.config.debug_output:
            self._save_pixel_analysis_debug(
                debugger, total, empty_count, region_counts,
                zone_counts, pos_count, ocr_times,
                wide_region_flags, same_zone_splits,
                tiny_regions, huge_regions, very_tall_single,
                four_plus_regions, per_sub_data,
                dict(line_counts), all_internal_gaps, all_inter_gaps,
                all_region_widths, all_region_heights,
            )

            # Cross-validation debug
            if cv_aligned > 0 or cv_flagged:
                debugger.add_cross_validation_summary(
                    cv_aligned, cv_flagged
                )

        return ocr_results

    def _save_pixel_analysis_debug(
        self,
        debugger: OCRDebugger,
        total_subs: int,
        empty_count: int,
        region_counts: dict,
        zone_counts: dict,
        pos_count: int,
        ocr_times: list[float],
        wide_flags: list[tuple[int, int, int]],
        zone_splits: list[tuple[int, str, int]],
        tiny_regions: list | None = None,
        huge_regions: list | None = None,
        very_tall_single: list | None = None,
        four_plus_regions: list | None = None,
        per_sub_data: list[dict] | None = None,
        line_counts: dict | None = None,
        internal_gaps: list[int] | None = None,
        inter_gaps: list[int] | None = None,
        region_widths: list[int] | None = None,
        region_heights: list[int] | None = None,
    ) -> None:
        """Save full pixel analysis and validation to debug output."""
        tiny_regions = tiny_regions or []
        huge_regions = huge_regions or []
        very_tall_single = very_tall_single or []
        four_plus_regions = four_plus_regions or []
        per_sub_data = per_sub_data or []
        line_counts = line_counts or {}
        internal_gaps = internal_gaps or []
        inter_gaps = inter_gaps or []
        region_widths = region_widths or []
        region_heights = region_heights or []
        analysis_dir = debugger.debug_dir / "pixel_analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        total_regions = sum(zone_counts.values())
        single = region_counts.get(1, 0)
        multi = region_counts.get(2, 0)
        processed = single + multi
        std_count = total_regions - pos_count

        def pct(n: int, total: int) -> str:
            return f"{n / max(total, 1) * 100:.1f}%" if total > 0 else "0%"

        lines = [
            "Pixel Region Detection Analysis",
            "=" * 60,
            "",
            f"Total subtitles:  {total_subs}",
            f"Processed:        {processed}",
            f"Empty (no text):  {empty_count} ({pct(empty_count, total_subs)})",
            "",
            "Region Distribution:",
            f"  {'Stat':<25} {'Count':>6}  {'%':>6}",
            f"  {'-'*25} {'-'*6}  {'-'*6}",
            f"  {'Single region':<25} {single:>6}  {pct(single, total_subs):>6}",
            f"  {'Multi region':<25} {multi:>6}  {pct(multi, total_subs):>6}",
            f"  {'Empty':<25} {empty_count:>6}  {pct(empty_count, total_subs):>6}",
            "",
            "Zone Distribution:",
            f"  {'Zone':<10} {'Count':>6}  {'%':>6}",
            f"  {'-'*10} {'-'*6}  {'-'*6}",
        ]
        for zone in sorted(zone_counts.keys(), key=lambda z: -zone_counts[z]):
            count = zone_counts[zone]
            lines.append(
                f"  {zone:<10} {count:>6}  {pct(count, total_regions):>6}"
            )

        lines.extend([
            "",
            "Positioning:",
            f"  {'Stat':<25} {'Count':>6}  {'%':>6}",
            f"  {'-'*25} {'-'*6}  {'-'*6}",
            f"  {'Standard (no \\pos)':<25} {std_count:>6}  {pct(std_count, total_regions):>6}",
            f"  {'Needs \\pos()':<25} {pos_count:>6}  {pct(pos_count, total_regions):>6}",
        ])

        # Lines per region
        if line_counts:
            lines.extend([
                "",
                "Lines Per Region:",
                f"  {'Lines':<10} {'Count':>6}  {'%':>6}",
                f"  {'-'*10} {'-'*6}  {'-'*6}",
            ])
            total_lc = sum(line_counts.values())
            for lc in sorted(line_counts.keys()):
                cnt = line_counts[lc]
                lines.append(
                    f"  {lc:<10} {cnt:>6}  {pct(cnt, total_lc):>6}"
                )

        # Gap analysis
        if internal_gaps:
            ig = sorted(internal_gaps)
            lines.extend([
                "",
                "Internal Gaps (between lines within regions):",
                f"  Min: {ig[0]}px  Max: {ig[-1]}px  "
                f"Avg: {sum(ig)/len(ig):.1f}px  Median: {ig[len(ig)//2]}px",
            ])
        if inter_gaps:
            eg = sorted(inter_gaps)
            lines.extend([
                "",
                "Inter-Region Gaps (between separate regions):",
                f"  Min: {eg[0]}px  Max: {eg[-1]}px  "
                f"Avg: {sum(eg)/len(eg):.1f}px  Median: {eg[len(eg)//2]}px",
            ])

        # Region sizes
        if region_widths:
            rw = sorted(region_widths)
            rh = sorted(region_heights)
            lines.extend([
                "",
                "Region Sizes:",
                f"  Width:  min={rw[0]}  max={rw[-1]}  "
                f"avg={sum(rw)/len(rw):.0f}  median={rw[len(rw)//2]}",
                f"  Height: min={rh[0]}  max={rh[-1]}  "
                f"avg={sum(rh)/len(rh):.0f}  median={rh[len(rh)//2]}",
            ])

        if ocr_times:
            avg_ms = sum(ocr_times) / len(ocr_times)
            lines.extend([
                "",
                "OCR Timing:",
                f"  Avg:   {avg_ms:.0f}ms/sub",
                f"  Min:   {min(ocr_times):.0f}ms",
                f"  Max:   {max(ocr_times):.0f}ms",
                f"  Total: {sum(ocr_times)/1000:.1f}s",
            ])

        # Full anomaly report
        lines.extend([
            "",
            "=" * 60,
            "Anomaly Report",
            "=" * 60,
            "",
            f"  {'Issue':<35} {'Count':>6}  {'%':>8}  Verdict",
            f"  {'-'*35} {'-'*6}  {'-'*8}  {'-'*30}",
            f"  {'Empty subs':<35} {empty_count:>6}  "
            f"{pct(empty_count, total_subs):>8}  "
            f"{'Blank forced subs or timing markers' if empty_count else 'Clean'}",
            f"  {'Tiny regions (<10px)':<35} {len(tiny_regions):>6}  "
            f"{pct(len(tiny_regions), total_subs):>8}  "
            f"{'Possible noise' if tiny_regions else 'Clean'}",
            f"  {'Huge regions (>90%w+50%h)':<35} {len(huge_regions):>6}  "
            f"{pct(len(huge_regions), total_subs):>8}  "
            f"{'Check for merge errors' if huge_regions else 'Clean'}",
            f"  {'Very tall single (>40%h)':<35} {len(very_tall_single):>6}  "
            f"{pct(len(very_tall_single), total_subs):>8}  "
            f"{'Possible missed split' if very_tall_single else 'Clean'}",
            f"  {'4+ regions':<35} {len(four_plus_regions):>6}  "
            f"{pct(len(four_plus_regions), total_subs):>8}  "
            f"{'Unusual complexity' if four_plus_regions else 'Clean'}",
            f"  {'Same-zone splits (<80px gap)':<35} {len(zone_splits):>6}  "
            f"{pct(len(zone_splits), total_subs):>8}  "
            f"{'May be incorrect splits' if zone_splits else 'Clean'}",
            f"  {'Horizontal merge suspects':<35} {len(wide_flags):>6}  "
            f"{pct(len(wide_flags), total_subs):>8}  "
            f"{'Wide regions with column gaps' if wide_flags else 'Clean'}",
        ])

        # Detail sections for each issue type with sub indices
        has_issues = (
            wide_flags or zone_splits or tiny_regions
            or huge_regions or very_tall_single or four_plus_regions
        )

        if has_issues:
            lines.extend(["", "=" * 60, "Issue Details (by sub index)", "=" * 60])

        if tiny_regions:
            lines.extend(["", "Tiny regions:"])
            for idx, w, h in tiny_regions:
                lines.append(f"  [{idx:04d}] {w}x{h}")

        if huge_regions:
            lines.extend(["", "Huge regions:"])
            for idx, w, h in huge_regions:
                lines.append(f"  [{idx:04d}] {w}x{h}")

        if very_tall_single:
            lines.extend(["", "Very tall single regions:"])
            for idx, w, h in very_tall_single:
                lines.append(f"  [{idx:04d}] {w}x{h}")

        if four_plus_regions:
            lines.extend(["", "4+ regions:"])
            for idx, count in four_plus_regions:
                lines.append(f"  [{idx:04d}] {count} regions")

        if zone_splits:
            lines.extend(["", "Same-zone splits:"])
            for sub_idx, zone, gap in zone_splits:
                lines.append(f"  [{sub_idx:04d}] zone={zone}, gap={gap}px")

        if wide_flags:
            lines.extend(["", "Horizontal merge suspects:"])
            for sub_idx, width, h_gap in wide_flags:
                lines.append(
                    f"  [{sub_idx:04d}] region={width}px, "
                    f"gap={h_gap}px ({h_gap * 100 // width}%)"
                )

        if not has_issues:
            lines.extend(["", "No issues detected."])

        (analysis_dir / "pixel_analysis.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )

        # Per-sub region detail (multi-region and positioned subs only)
        if per_sub_data:
            detail_lines = [
                "Per-Subtitle Region Detail",
                "=" * 60,
                "(Only multi-region and positioned subs shown)",
                "",
            ]
            for sd in per_sub_data:
                detail_lines.append(f"[{sd['index']:04d}] {sd.get('time', '')} "
                                    f"— {sd['n_regions']} region(s)")
                for ri in sd["regions"]:
                    bbox = ri["bbox"]
                    pos_tag = " \\pos" if ri["pos"] else ""
                    lines_info = f" lines={ri.get('lines', '?')}" if ri.get("lines", 0) > 0 else ""
                    gap_info = f" max_gap={ri.get('max_gap', 0)}px" if ri.get("max_gap", 0) > 0 else ""
                    detail_lines.append(
                        f"  R{ri['id']}: {ri['zone']}{pos_tag} "
                        f"[{bbox[0]},{bbox[1]}]-[{bbox[2]},{bbox[3]}] "
                        f"({ri['size']}){lines_info}{gap_info}"
                    )
                detail_lines.append("")

            (analysis_dir / "per_sub_regions.txt").write_text(
                "\n".join(detail_lines), encoding="utf-8"
            )

    def _process_subtitles_sequential(
        self,
        subtitle_images: list[SubtitleImage],
        report: OCRReport,
        debugger: OCRDebugger,
    ) -> list[OCRSubtitleResult]:
        """Process subtitles sequentially (single worker)."""
        ocr_results: list[OCRSubtitleResult] = []
        last_logged_percent = -1

        for i, sub_image in enumerate(subtitle_images):
            progress = 0.10 + (0.80 * i / len(subtitle_images))
            current_percent = int((i / len(subtitle_images)) * 100)
            if current_percent >= last_logged_percent + 10:
                self._log_progress(
                    f"Processing subtitles ({current_percent}%)", progress
                )
                last_logged_percent = current_percent

            try:
                ocr_result, sub_result = self._process_single_subtitle_unified(
                    sub_image, report, debugger
                )
                if ocr_result is not None:
                    ocr_results.append(ocr_result)
                if sub_result is not None:
                    report.add_subtitle_result(sub_result)
            except Exception:
                report.add_subtitle_result(
                    SubtitleOCRResult(
                        index=sub_image.index,
                        timestamp_start=sub_image.start_time,
                        timestamp_end=sub_image.end_time,
                        text="",
                        confidence=0.0,
                    )
                )

        return ocr_results

    def _process_subtitles_parallel(
        self,
        subtitle_images: list[SubtitleImage],
        max_workers: int,
        report: OCRReport,
        debugger: OCRDebugger,
    ) -> list[OCRSubtitleResult]:
        """Process subtitles in parallel using a thread pool with multiple engines."""
        logger = logging.getLogger(__name__)
        total = len(subtitle_images)
        logger.info(f"Parallel OCR: {max_workers} workers for {total} subtitles")
        self._log_progress(f"Starting parallel OCR ({max_workers} workers)", 0.10)

        # Create engine pool: reuse self.engine as the first, create extras
        engine_pool: queue.Queue = queue.Queue()
        engine_pool.put(self.engine)
        for i in range(max_workers - 1):
            logger.info(f"Creating OCR engine {i + 2}/{max_workers}...")
            engine = self._create_single_engine()
            self._extra_engines.append(engine)
            engine_pool.put(engine)

        self._log_progress(f"All {max_workers} OCR engines ready", 0.12)

        # Shared preprocessor and postprocessor (stateless per-call, thread-safe)
        preprocessor = self.preprocessor
        postprocessor = self.postprocessor
        debug_images_dir = self.ocr_work_dir if self.config.save_debug_images else None

        # Submit all work to thread pool
        completed_count = 0
        last_logged_percent = -1
        # Collect results indexed by subtitle index for ordered output
        results_by_index: dict[int, tuple] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for sub_image in subtitle_images:
                future = executor.submit(
                    self._ocr_worker,
                    sub_image,
                    engine_pool,
                    preprocessor,
                    postprocessor,
                    debug_images_dir,
                )
                futures[future] = sub_image

            for future in as_completed(futures):
                sub_image = futures[future]
                completed_count += 1

                # Progress update
                current_percent = int((completed_count / total) * 100)
                if current_percent >= last_logged_percent + 10:
                    progress = 0.12 + (0.78 * completed_count / total)
                    self._log_progress(
                        f"Processing subtitles ({current_percent}%)", progress
                    )
                    last_logged_percent = current_percent

                try:
                    worker_result = future.result()
                    results_by_index[sub_image.index] = (
                        sub_image,
                        worker_result,
                    )
                except Exception:
                    logger.exception(f"Worker failed for subtitle {sub_image.index}")
                    results_by_index[sub_image.index] = (sub_image, None)

        # Process results in order for report/debugger (not thread-safe)
        ocr_results: list[OCRSubtitleResult] = []
        for idx in sorted(results_by_index.keys()):
            sub_image, worker_result = results_by_index[idx]

            if worker_result is None:
                report.add_subtitle_result(
                    SubtitleOCRResult(
                        index=sub_image.index,
                        timestamp_start=sub_image.start_time,
                        timestamp_end=sub_image.end_time,
                        text="",
                        confidence=0.0,
                    )
                )
                continue

            ocr_result, sub_result = self._build_subtitle_results(
                sub_image,
                worker_result,
                debugger,
            )
            if ocr_result is not None:
                ocr_results.append(ocr_result)
            if sub_result is not None:
                report.add_subtitle_result(sub_result)

        return ocr_results

    def _ocr_worker(
        self,
        sub_image: SubtitleImage,
        engine_pool: queue.Queue,
        preprocessor: ImagePreprocessor,
        postprocessor: OCRPostProcessor,
        debug_images_dir: Path | None,
    ) -> dict:
        """
        Worker function for parallel OCR processing.

        Grabs an engine from the pool, runs preprocess+OCR+postprocess,
        returns the engine to the pool. Returns raw result data.
        """
        engine = engine_pool.get()
        try:
            # Preprocess
            preprocessed = preprocessor.preprocess(sub_image, debug_images_dir)

            # OCR
            ocr_result = engine.ocr_lines_separately(preprocessed.image)

            if not ocr_result.success:
                return {
                    "success": False,
                    "ocr_result": ocr_result,
                    "raw_text": "",
                    "post_result": None,
                }

            raw_text = ocr_result.text

            # Post-process
            post_result = postprocessor.process(
                ocr_result.text,
                confidence=ocr_result.average_confidence,
                timestamp=sub_image.start_time,
            )

            return {
                "success": True,
                "ocr_result": ocr_result,
                "raw_text": raw_text,
                "post_result": post_result,
            }
        finally:
            engine_pool.put(engine)

    def _build_subtitle_results(
        self,
        sub_image: SubtitleImage,
        worker_result: dict,
        debugger: OCRDebugger,
    ) -> tuple[OCRSubtitleResult | None, SubtitleOCRResult | None]:
        """
        Build output results from worker data.

        Handles report/debugger updates and position classification.
        Called from main thread only (not thread-safe components).
        """
        ocr_result = worker_result["ocr_result"]
        raw_text = worker_result["raw_text"]
        post_result = worker_result["post_result"]

        if not worker_result["success"]:
            return (
                None,
                SubtitleOCRResult(
                    index=sub_image.index,
                    timestamp_start=sub_image.start_time,
                    timestamp_end=sub_image.end_time,
                    text="",
                    confidence=0.0,
                ),
            )

        # Add to debugger
        debugger.add_subtitle(
            index=sub_image.index,
            start_time=sub_image.start_time,
            end_time=sub_image.end_time,
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            image=sub_image.image,
            raw_ocr_text=raw_text,
        )

        # Track unknown words and fixes
        for word in post_result.unknown_words:
            debugger.add_unknown_word(sub_image.index, word)

        if post_result.was_modified:
            for fix_name, fix_count in post_result.fixes_applied.items():
                debugger.add_fix(
                    sub_image.index,
                    fix_name,
                    f"Applied {fix_count} time(s)",
                    original_text=raw_text,
                )

        # Position classification (same logic as _process_single_subtitle_unified)
        line_regions: list[LineRegion] = []
        if (
            self.config.preserve_positions
            and sub_image.frame_height > 0
            and ocr_result.lines
        ):
            line_y_pcts: list[float | None] = []
            for ocr_line in ocr_result.lines:
                if ocr_line.y_center > 0:
                    abs_y = ocr_line.y_center + sub_image.y
                    y_pct = (abs_y / sub_image.frame_height) * 100
                    line_y_pcts.append(y_pct)
                else:
                    line_y_pcts.append(None)

            cluster_gap = 15.0
            clusters: list[list[int]] = []
            for idx, y_pct in enumerate(line_y_pcts):
                if y_pct is None:
                    clusters.append([idx])
                    continue
                if clusters and line_y_pcts[clusters[-1][-1]] is not None:
                    prev_y = line_y_pcts[clusters[-1][-1]]
                    if abs(y_pct - prev_y) <= cluster_gap:
                        clusters[-1].append(idx)
                        continue
                clusters.append([idx])

            line_region_map: list[str] = ["bottom"] * len(ocr_result.lines)
            for cluster in clusters:
                min_pct = min(
                    (line_y_pcts[i] for i in cluster if line_y_pcts[i] is not None),
                    default=None,
                )
                if min_pct is not None and min_pct <= self.config.top_threshold_percent:
                    for i in cluster:
                        line_region_map[i] = "top"

            for idx_l, ocr_line in enumerate(ocr_result.lines):
                line_regions.append(
                    LineRegion(
                        text=ocr_line.text,
                        region=line_region_map[idx_l],
                        y_center=ocr_line.y_center,
                    )
                )

        is_positioned = not sub_image.is_bottom_positioned(
            self.config.bottom_threshold_percent
        )

        # Extract palette colors
        subtitle_colors: list[list[int]] = []
        dominant_color: list[int] = []
        if sub_image.palette:
            for color in sub_image.palette:
                if color and len(color) >= 3:
                    subtitle_colors.append(
                        list(color[:4]) if len(color) >= 4 else [*list(color), 255]
                    )
            for color in sub_image.palette:
                if color and len(color) >= 4 and color[3] > 128:
                    dominant_color = list(color[:4])
                    break

        ocr_subtitle_result = OCRSubtitleResult(
            index=sub_image.index,
            start_ms=float(sub_image.start_ms),
            end_ms=float(sub_image.end_ms),
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            raw_ocr_text=raw_text,
            fixes_applied=dict(post_result.fixes_applied),
            unknown_words=list(post_result.unknown_words),
            x=sub_image.x,
            y=sub_image.y,
            width=sub_image.width,
            height=sub_image.height,
            frame_width=sub_image.frame_width,
            frame_height=sub_image.frame_height,
            is_forced=sub_image.is_forced,
            subtitle_colors=subtitle_colors,
            dominant_color=dominant_color,
            debug_image=f"sub_{sub_image.index:04d}.png",
            line_regions=line_regions,
        )

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
            line_regions=[lr.region for lr in line_regions],
        )

        return ocr_subtitle_result, sub_result

    def _process_single_subtitle_unified(
        self, sub_image: SubtitleImage, report: OCRReport, debugger: OCRDebugger
    ) -> tuple[OCRSubtitleResult | None, SubtitleOCRResult | None]:
        """
        Process a single subtitle through the pipeline.

        Returns:
            Tuple of (OCRSubtitleResult for SubtitleData, SubtitleOCRResult for report)
        """
        # Preprocess image
        preprocessed = self.preprocessor.preprocess(
            sub_image, self.ocr_work_dir if self.config.save_debug_images else None
        )

        # Run OCR - use line splitting with PSM 7 for better accuracy
        ocr_result = self.engine.ocr_lines_separately(preprocessed.image)

        if not ocr_result.success:
            return (
                None,
                SubtitleOCRResult(
                    index=sub_image.index,
                    timestamp_start=sub_image.start_time,
                    timestamp_end=sub_image.end_time,
                    text="",
                    confidence=0.0,
                ),
            )

        # Store raw OCR text before post-processing
        raw_ocr_text = ocr_result.text

        # Post-process text
        post_result = self.postprocessor.process(
            ocr_result.text,
            confidence=ocr_result.average_confidence,
            timestamp=sub_image.start_time,
        )

        # Add to debugger (it checks if enabled internally)
        debugger.add_subtitle(
            index=sub_image.index,
            start_time=sub_image.start_time,
            end_time=sub_image.end_time,
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            image=preprocessed.image,
            raw_ocr_text=raw_ocr_text,
        )

        # Track unknown words
        for word in post_result.unknown_words:
            report.add_unknown_word(
                word=word,
                context=post_result.text[:50],
                timestamp=sub_image.start_time,
                confidence=ocr_result.average_confidence,
            )
            debugger.add_unknown_word(sub_image.index, word)

        # Track fixes applied
        if post_result.was_modified:
            for fix_name, fix_count in post_result.fixes_applied.items():
                debugger.add_fix(
                    sub_image.index,
                    fix_name,
                    f"Applied {fix_count} time(s)",
                    original_text=raw_ocr_text,
                )

        # Track low confidence
        if ocr_result.low_confidence:
            report.add_low_confidence_line(
                text=post_result.text,
                timestamp=sub_image.start_time,
                confidence=ocr_result.average_confidence,
                subtitle_index=sub_image.index,
                potential_issues=list(post_result.fixes_applied.keys()),
            )

        # Classify lines as top or bottom using y_center + VobSub offset.
        # Two-pass approach:
        #   1. Classify each line individually (top if < threshold, else bottom)
        #   2. Group adjacent lines with the same classification together —
        #      if a line is near its neighbors (within 15% of frame height),
        #      it belongs to the same text block and gets the block's region.
        # This handles multi-line top text (all lines stay "top" even if
        # lower lines cross the threshold) while still correctly splitting
        # images with both top signs and bottom dialogue.
        line_regions: list[LineRegion] = []
        if (
            self.config.preserve_positions
            and sub_image.frame_height > 0
            and ocr_result.lines
        ):
            # Pass 1: get absolute y_pct for each line
            line_y_pcts: list[float | None] = []
            for ocr_line in ocr_result.lines:
                if ocr_line.y_center > 0:
                    abs_y = ocr_line.y_center + sub_image.y
                    y_pct = (abs_y / sub_image.frame_height) * 100
                    line_y_pcts.append(y_pct)
                else:
                    line_y_pcts.append(None)

            # Pass 2: group into clusters of nearby lines, then classify
            # each cluster by its topmost line's position
            cluster_gap = 15.0  # max y_pct gap between lines in same cluster
            clusters: list[list[int]] = []  # list of [line indices]
            for idx, y_pct in enumerate(line_y_pcts):
                if y_pct is None:
                    # No position info — treat as its own bottom cluster
                    clusters.append([idx])
                    continue
                # Check if this line belongs to the previous cluster
                if clusters and line_y_pcts[clusters[-1][-1]] is not None:
                    prev_y = line_y_pcts[clusters[-1][-1]]
                    if abs(y_pct - prev_y) <= cluster_gap:
                        clusters[-1].append(idx)
                        continue
                # Start a new cluster
                clusters.append([idx])

            # Assign region per cluster based on topmost line
            line_region_map: list[str] = ["bottom"] * len(ocr_result.lines)
            for cluster in clusters:
                # Find the minimum y_pct in this cluster
                min_pct = min(
                    (line_y_pcts[i] for i in cluster if line_y_pcts[i] is not None),
                    default=None,
                )
                if min_pct is not None and min_pct <= self.config.top_threshold_percent:
                    for i in cluster:
                        line_region_map[i] = "top"

            for idx, ocr_line in enumerate(ocr_result.lines):
                line_regions.append(
                    LineRegion(
                        text=ocr_line.text,
                        region=line_region_map[idx],
                        y_center=ocr_line.y_center,
                    )
                )

        # Determine if positioned (legacy: whole-subtitle check)
        is_positioned = not sub_image.is_bottom_positioned(
            self.config.bottom_threshold_percent
        )

        # Extract palette colors if available
        subtitle_colors: list[list[int]] = []
        dominant_color: list[int] = []
        if sub_image.palette:
            # Convert palette tuples to lists for JSON serialization
            for color in sub_image.palette:
                if color and len(color) >= 3:
                    subtitle_colors.append(
                        list(color[:4]) if len(color) >= 4 else [*list(color), 255]
                    )
            # First non-transparent color is often the dominant text color
            for color in sub_image.palette:
                if color and len(color) >= 4 and color[3] > 128:  # Alpha > 128
                    dominant_color = list(color[:4])
                    break

        # Create unified OCRSubtitleResult with all metadata
        ocr_subtitle_result = OCRSubtitleResult(
            index=sub_image.index,
            start_ms=float(sub_image.start_ms),
            end_ms=float(sub_image.end_ms),
            text=post_result.text,
            confidence=ocr_result.average_confidence,
            raw_ocr_text=raw_ocr_text,
            fixes_applied=dict(post_result.fixes_applied),
            unknown_words=list(post_result.unknown_words),
            x=sub_image.x,
            y=sub_image.y,
            width=sub_image.width,
            height=sub_image.height,
            frame_width=sub_image.frame_width,
            frame_height=sub_image.frame_height,
            is_forced=sub_image.is_forced,
            subtitle_colors=subtitle_colors,
            dominant_color=dominant_color,
            debug_image=f"sub_{sub_image.index:04d}.png",
            line_regions=line_regions,
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
            line_regions=[lr.region for lr in line_regions],
        )

        return ocr_subtitle_result, sub_result

    def _get_report_path(self, input_path: Path, timestamp: str) -> Path:
        """Generate report file path."""
        report_name = f"{input_path.stem}_ocr_report_{timestamp}.json"
        return self.logs_dir / report_name

    def _log_progress(self, message: str, progress: float):
        """Log progress if callback is available."""
        if self.progress_callback:
            self.progress_callback(message, progress)
