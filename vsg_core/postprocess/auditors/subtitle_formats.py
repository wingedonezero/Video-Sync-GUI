# vsg_core/postprocess/auditors/subtitle_formats.py
import re
from pathlib import Path

from .base import BaseAuditor


class SubtitleFormatsAuditor(BaseAuditor):
    """Validates subtitle conversions and all processing steps."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Comprehensive subtitle audit including:
        - Track count verification
        - Generated track verification
        - OCR conversion
        - ASS conversion
        - Rescaling
        - Font size multipliers

        Note: Subtitle timing validation happens during processing (metadata_preserver),
        not in final audit, since subtitle delay metadata in MKV is unreliable.

        Returns the number of issues found.
        """
        subtitle_items = [
            item for item in self.ctx.extracted_items if item.track.type == "subtitles"
        ]

        if not subtitle_items:
            self.log("✅ No subtitle tracks to audit.")
            return 0

        final_tracks = final_mkvmerge_data.get("tracks", [])
        final_subtitle_tracks = [
            t for t in final_tracks if t.get("type") == "subtitles"
        ]

        # NEW: Check total subtitle track count
        expected_count = len(subtitle_items)
        actual_count = len(final_subtitle_tracks)
        generated_count = sum(1 for item in subtitle_items if item.is_generated)

        if expected_count != actual_count:
            gen_info = (
                f" (including {generated_count} generated)"
                if generated_count > 0
                else ""
            )
            self._report(
                f"Subtitle track count mismatch! Expected {expected_count} "
                f"tracks{gen_info}, actual {actual_count} tracks in final "
                f"output (missing {expected_count - actual_count} track(s))",
                severity="error",
            )
        else:
            gen_info = (
                f" (including {generated_count} generated)"
                if generated_count > 0
                else ""
            )
            self.log(f"✓ Subtitle track count verified: {actual_count}{gen_info}")

        final_subtitle_idx = 0
        for plan_item in subtitle_items:
            # Use custom_name if set, otherwise use track.props.name
            track_name = (
                plan_item.custom_name
                or plan_item.track.props.name
                or f"Track {final_subtitle_idx}"
            )

            if final_subtitle_idx >= len(final_subtitle_tracks):
                # Identify if missing track is generated
                track_type = (
                    "Generated track" if plan_item.is_generated else "Subtitle track"
                )
                self.log(
                    f"[WARNING] {track_type} '{track_name}' missing from final file!"
                )

                # Show source and track ID for ALL missing tracks
                if plan_item.is_generated:
                    filter_cfg = plan_item.filter_config or {}
                    self.log(
                        f"          Source: {plan_item.track.source} Track {plan_item.source_track_id}"
                    )
                    self.log(
                        f"          Filter: {filter_cfg.get('filter_mode', 'exclude')} {filter_cfg.get('filter_styles', [])}"
                    )
                    self._track_issue(
                        f"Generated track '{track_name}' missing from final "
                        f"file (source: {plan_item.track.source} Track "
                        f"{plan_item.source_track_id})"
                    )
                else:
                    # For normal tracks, show source and track ID
                    self.log(
                        f"          Source: {plan_item.track.source} Track {plan_item.track.id}"
                    )
                    self._track_issue(
                        f"Subtitle track '{track_name}' missing from final "
                        f"file (source: {plan_item.track.source} Track "
                        f"{plan_item.track.id})"
                    )

                continue

            final_track = final_subtitle_tracks[final_subtitle_idx]

            # Label generated tracks in logs for clarity
            if plan_item.is_generated:
                track_label = f"{track_name} [Generated]"
            else:
                track_label = track_name

            # --- Skip OCR checks for preserved tracks ---
            if not plan_item.is_preserved:
                # Check 1: OCR conversion
                if plan_item.perform_ocr:
                    self._verify_ocr(final_track, track_label)

                # Check 1b: Pixel verification issues
                if plan_item.perform_ocr:
                    self._check_pixel_verification(plan_item, track_label)

                # Check 2: ASS conversion
                if plan_item.convert_to_ass:
                    self._verify_ass_conversion(final_track, track_label)

            # Check 3: Rescaling (requires reading the actual subtitle file)
            if plan_item.rescale and plan_item.extracted_path:
                self._verify_rescaling(plan_item, track_label)

            # Check 4: Font size multiplier
            if abs(plan_item.size_multiplier - 1.0) > 0.01 and plan_item.extracted_path:
                self._verify_font_size(plan_item, track_label)

            final_subtitle_idx += 1

        if not self.issues:
            self.log("✅ All subtitle processing verified correctly.")

        return len(self.issues)

    def _check_pixel_verification(self, plan_item, track_name: str) -> None:
        """Check pixel verification results for OCR issues that need review."""
        # Get pixel verification from plan item (stored by OCR wrapper)
        pv = getattr(plan_item, "pixel_verification", None)
        if not pv:
            return

        paddle_empty = pv.get("paddle_empty", 0)
        recovered = pv.get("paddle_empty_recovered", 0)
        outside = pv.get("outside", 0)
        lost = paddle_empty - recovered

        if lost > 0:
            self.log(
                f"[WARNING] OCR '{track_name}': {lost} subtitle(s) had content "
                f"but OCR engine returned nothing (paddle_empty, not recovered)"
            )
            self.log("          Check debug/pixel_verification/ for images")
            self._track_issue(
                f"OCR '{track_name}': {lost} subtitle(s) had content but "
                "OCR engine returned nothing (paddle_empty, not recovered)"
            )

        if recovered > 0:
            self.log(
                f"  ✓ OCR '{track_name}': {recovered} paddle_empty sub(s) "
                f"recovered via OCR fallback"
            )

        if outside > 0:
            self.log(
                f"[WARNING] OCR '{track_name}': {outside} subtitle(s) had content "
                f"outside OCR detection boxes (possible missed text)"
            )
            self.log("          Check debug/pixel_verification/ for images")
            self._track_issue(
                f"OCR '{track_name}': {outside} subtitle(s) had content "
                "outside OCR detection boxes (possible missed text)"
            )

    def _verify_ocr(self, final_track: dict, track_name: str) -> None:
        """Verify OCR was performed and resulted in text format."""
        codec_id = final_track.get("properties", {}).get("codec_id", "")
        if "TEXT" not in codec_id.upper():
            self._report(
                f"OCR track '{track_name}' is not in text format "
                f"(codec: {codec_id}) - OCR conversion was enabled but "
                "not applied"
            )
        else:
            self.log(f"  ✓ OCR track '{track_name}' successfully converted to text")

    def _verify_ass_conversion(self, final_track: dict, track_name: str) -> None:
        """Verify subtitle was converted to ASS/SSA format."""
        codec_id = final_track.get("properties", {}).get("codec_id", "")
        if "ASS" not in codec_id.upper() and "SSA" not in codec_id.upper():
            self._report(
                f"Track '{track_name}' was not converted to ASS/SSA "
                f"(codec: {codec_id}) - ASS conversion was enabled but "
                "not applied"
            )
        else:
            self.log(f"  ✓ Track '{track_name}' successfully converted to ASS")

    def _verify_rescaling(self, plan_item, track_name: str) -> None:
        """
        Verify PlayResX/PlayResY were updated to match video resolution.
        This requires reading the subtitle file from disk.
        """
        if not plan_item.extracted_path or not plan_item.extracted_path.exists():
            self._report(f"Cannot verify rescaling for '{track_name}' - file not found")
            return

        # Only check ASS/SSA files
        if plan_item.extracted_path.suffix.lower() not in [".ass", ".ssa"]:
            return

        try:
            # Get video resolution from Source 1
            source1_file = self.ctx.sources.get("Source 1")
            if not source1_file:
                return  # Can't verify without source

            video_data = self._get_metadata(source1_file, "ffprobe")
            if not video_data:
                return

            video_stream = next(
                (
                    s
                    for s in video_data.get("streams", [])
                    if s.get("codec_type") == "video"
                ),
                None,
            )
            if not video_stream:
                return

            expected_width = video_stream.get("width")
            expected_height = video_stream.get("height")

            if not expected_width or not expected_height:
                return

            # Read subtitle file and check PlayRes values
            content = plan_item.extracted_path.read_text(encoding="utf-8")

            rx = re.search(r"^\s*PlayResX:\s*(\d+)", content, re.MULTILINE)
            ry = re.search(r"^\s*PlayResY:\s*(\d+)", content, re.MULTILINE)

            if not rx or not ry:
                # No PlayRes tags - rescaling might not have been needed
                return

            actual_width = int(rx.group(1))
            actual_height = int(ry.group(1))

            if actual_width != expected_width or actual_height != expected_height:
                self._report(
                    f"Rescaling verification failed for '{track_name}': "
                    f"expected {expected_width}x{expected_height}, actual "
                    f"{actual_width}x{actual_height} - rescaling was enabled "
                    "but not applied"
                )
            else:
                self.log(
                    f"  ✓ Subtitle '{track_name}' correctly rescaled to {actual_width}x{actual_height}"
                )

        except Exception as e:
            self._report(f"Could not verify rescaling for '{track_name}': {e}")

    def _verify_font_size(self, plan_item, track_name: str) -> None:
        """
        Verify font size multiplier was applied.
        Checks if font sizes in the subtitle are reasonable for the multiplier.
        """
        if not plan_item.extracted_path or not plan_item.extracted_path.exists():
            self._report(f"Cannot verify font size for '{track_name}' - file not found")
            return

        # Only check ASS/SSA files
        if plan_item.extracted_path.suffix.lower() not in [".ass", ".ssa"]:
            return

        try:
            content = plan_item.extracted_path.read_text(encoding="utf-8-sig")

            # Find all Style: lines and extract font sizes
            style_pattern = re.compile(r"^Style:\s*(.+?)$", re.MULTILINE)
            styles = style_pattern.findall(content)

            if not styles:
                return  # No styles to check

            font_sizes = []
            for style_line in styles:
                parts = style_line.split(",")
                if len(parts) >= 3:
                    try:
                        # Font size is typically the 3rd field (index 2) in Style definition
                        font_size = float(parts[2].strip())
                        font_sizes.append(font_size)
                    except (ValueError, IndexError):
                        continue

            if not font_sizes:
                return

            # Check if font sizes seem reasonable
            # If multiplier is 2.0, sizes should be roughly 2x larger than typical (which is ~20-40)
            # We'll just verify they're not unchanged from typical values
            avg_size = sum(font_sizes) / len(font_sizes)

            # Typical subtitle sizes are 20-50
            # If multiplier is applied, they should be outside this range (for multipliers != 1.0)
            multiplier = plan_item.size_multiplier

            if multiplier > 1.5:
                # Should be larger than typical
                if avg_size < 45:  # If still in typical range, might not be applied
                    self._report(
                        f"Font size multiplier {multiplier:.2f}x may not "
                        f"have been applied to '{track_name}' (average font "
                        f"size {avg_size:.1f}, expected >45)"
                    )
                else:
                    self.log(
                        f"  ✓ Font size multiplier {multiplier:.2f}x applied to '{track_name}' (avg: {avg_size:.1f})"
                    )
            elif multiplier < 0.8:
                # Should be smaller than typical
                if avg_size > 25:
                    self._report(
                        f"Font size multiplier {multiplier:.2f}x may not "
                        f"have been applied to '{track_name}' (average font "
                        f"size {avg_size:.1f}, expected <25)"
                    )
                else:
                    self.log(
                        f"  ✓ Font size multiplier {multiplier:.2f}x applied to '{track_name}' (avg: {avg_size:.1f})"
                    )
            else:
                # Multiplier close to 1.0 or within normal range - sizes should be typical
                self.log(
                    f"  ✓ Font sizes appear normal for '{track_name}' (multiplier {multiplier:.2f}x)"
                )

        except Exception as e:
            self._report(f"Could not verify font size for '{track_name}': {e}")
