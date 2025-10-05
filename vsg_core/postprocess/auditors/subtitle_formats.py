# vsg_core/postprocess/auditors/subtitle_formats.py
# -*- coding: utf-8 -*-
import re
from typing import Dict
from pathlib import Path

from vsg_core.models.enums import TrackType
from .base import BaseAuditor


class SubtitleFormatsAuditor(BaseAuditor):
    """Validates subtitle conversions and all processing steps."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Comprehensive subtitle audit including:
        - OCR conversion
        - ASS conversion
        - Rescaling
        - Font size multipliers
        - Timing corrections (if applied)

        Returns the number of issues found.
        """
        issues = 0
        subtitle_items = [item for item in self.ctx.extracted_items if item.track.type == TrackType.SUBTITLES]

        if not subtitle_items:
            self.log("✅ No subtitle tracks to audit.")
            return 0

        final_tracks = final_mkvmerge_data.get('tracks', [])
        final_subtitle_tracks = [t for t in final_tracks if t.get('type') == 'subtitles']

        for i, plan_item in enumerate(subtitle_items):
            if i >= len(final_subtitle_tracks):
                self.log(f"[WARNING] Subtitle track {i} missing from final file!")
                issues += 1
                continue

            final_track = final_subtitle_tracks[i]
            track_name = plan_item.track.props.name or f"Subtitle {i}"

            # Check 1: OCR conversion
            if plan_item.perform_ocr:
                issues += self._verify_ocr(final_track, track_name)

            # Check 2: ASS conversion
            if plan_item.convert_to_ass:
                issues += self._verify_ass_conversion(final_track, track_name)

            # Check 3: Rescaling (requires reading the actual subtitle file)
            if plan_item.rescale and plan_item.extracted_path:
                issues += self._verify_rescaling(plan_item, track_name)

            # Check 4: Font size multiplier
            if abs(plan_item.size_multiplier - 1.0) > 0.01 and plan_item.extracted_path:
                issues += self._verify_font_size(plan_item, track_name)

        if issues == 0:
            self.log("✅ All subtitle processing verified correctly.")

        return issues

    def _verify_ocr(self, final_track: Dict, track_name: str) -> int:
        """Verify OCR was performed and resulted in text format."""
        codec_id = final_track.get('properties', {}).get('codec_id', '')
        if 'TEXT' not in codec_id.upper():
            self.log(f"[WARNING] OCR track '{track_name}' is not in text format!")
            self.log(f"          Codec: {codec_id}")
            self.log(f"          → OCR conversion was enabled but not applied!")
            return 1
        else:
            self.log(f"  ✓ OCR track '{track_name}' successfully converted to text")
            return 0

    def _verify_ass_conversion(self, final_track: Dict, track_name: str) -> int:
        """Verify subtitle was converted to ASS/SSA format."""
        codec_id = final_track.get('properties', {}).get('codec_id', '')
        if 'ASS' not in codec_id.upper() and 'SSA' not in codec_id.upper():
            self.log(f"[WARNING] Track '{track_name}' was not converted to ASS/SSA!")
            self.log(f"          Codec: {codec_id}")
            self.log(f"          → ASS conversion was enabled but not applied!")
            return 1
        else:
            self.log(f"  ✓ Track '{track_name}' successfully converted to ASS")
            return 0

    def _verify_rescaling(self, plan_item, track_name: str) -> int:
        """
        Verify PlayResX/PlayResY were updated to match video resolution.
        This requires reading the subtitle file from disk.
        """
        issues = 0

        if not plan_item.extracted_path or not plan_item.extracted_path.exists():
            self.log(f"[WARNING] Cannot verify rescaling for '{track_name}' - file not found")
            return 1

        # Only check ASS/SSA files
        if plan_item.extracted_path.suffix.lower() not in ['.ass', '.ssa']:
            return 0

        try:
            # Get video resolution from Source 1
            source1_file = self.ctx.sources.get("Source 1")
            if not source1_file:
                return 0  # Can't verify without source

            video_data = self._get_metadata(source1_file, 'ffprobe')
            if not video_data:
                return 0

            video_stream = next((s for s in video_data.get('streams', []) if s.get('codec_type') == 'video'), None)
            if not video_stream:
                return 0

            expected_width = video_stream.get('width')
            expected_height = video_stream.get('height')

            if not expected_width or not expected_height:
                return 0

            # Read subtitle file and check PlayRes values
            content = plan_item.extracted_path.read_text(encoding='utf-8')

            rx = re.search(r'^\s*PlayResX:\s*(\d+)', content, re.MULTILINE)
            ry = re.search(r'^\s*PlayResY:\s*(\d+)', content, re.MULTILINE)

            if not rx or not ry:
                # No PlayRes tags - rescaling might not have been needed
                return 0

            actual_width = int(rx.group(1))
            actual_height = int(ry.group(1))

            if actual_width != expected_width or actual_height != expected_height:
                self.log(f"[WARNING] Rescaling verification failed for '{track_name}'")
                self.log(f"          Expected: {expected_width}x{expected_height}")
                self.log(f"          Actual:   {actual_width}x{actual_height}")
                self.log(f"          → Rescaling was enabled but not applied!")
                issues += 1
            else:
                self.log(f"  ✓ Subtitle '{track_name}' correctly rescaled to {actual_width}x{actual_height}")

        except Exception as e:
            self.log(f"[WARNING] Could not verify rescaling for '{track_name}': {e}")
            issues += 1

        return issues

    def _verify_font_size(self, plan_item, track_name: str) -> int:
        """
        Verify font size multiplier was applied.
        Checks if font sizes in the subtitle are reasonable for the multiplier.
        """
        issues = 0

        if not plan_item.extracted_path or not plan_item.extracted_path.exists():
            self.log(f"[WARNING] Cannot verify font size for '{track_name}' - file not found")
            return 1

        # Only check ASS/SSA files
        if plan_item.extracted_path.suffix.lower() not in ['.ass', '.ssa']:
            return 0

        try:
            content = plan_item.extracted_path.read_text(encoding='utf-8-sig')

            # Find all Style: lines and extract font sizes
            style_pattern = re.compile(r'^Style:\s*(.+?)$', re.MULTILINE)
            styles = style_pattern.findall(content)

            if not styles:
                return 0  # No styles to check

            font_sizes = []
            for style_line in styles:
                parts = style_line.split(',')
                if len(parts) >= 3:
                    try:
                        # Font size is typically the 3rd field (index 2) in Style definition
                        font_size = float(parts[2].strip())
                        font_sizes.append(font_size)
                    except (ValueError, IndexError):
                        continue

            if not font_sizes:
                return 0

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
                    self.log(f"[WARNING] Font size multiplier {multiplier:.2f}x may not have been applied to '{track_name}'")
                    self.log(f"          Average font size: {avg_size:.1f} (expected >45 for {multiplier:.2f}x)")
                    issues += 1
                else:
                    self.log(f"  ✓ Font size multiplier {multiplier:.2f}x applied to '{track_name}' (avg: {avg_size:.1f})")
            elif multiplier < 0.8:
                # Should be smaller than typical
                if avg_size > 25:
                    self.log(f"[WARNING] Font size multiplier {multiplier:.2f}x may not have been applied to '{track_name}'")
                    self.log(f"          Average font size: {avg_size:.1f} (expected <25 for {multiplier:.2f}x)")
                    issues += 1
                else:
                    self.log(f"  ✓ Font size multiplier {multiplier:.2f}x applied to '{track_name}' (avg: {avg_size:.1f})")
            else:
                # Multiplier close to 1.0 or within normal range - sizes should be typical
                self.log(f"  ✓ Font sizes appear normal for '{track_name}' (multiplier {multiplier:.2f}x)")

        except Exception as e:
            self.log(f"[WARNING] Could not verify font size for '{track_name}': {e}")
            issues += 1

        return issues
