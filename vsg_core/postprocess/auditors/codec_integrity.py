# vsg_core/postprocess/auditors/codec_integrity.py
# -*- coding: utf-8 -*-
from typing import Dict, List
from pathlib import Path

from .base import BaseAuditor


class CodecIntegrityAuditor(BaseAuditor):
    """Ensures codecs weren't accidentally transcoded during muxing."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Verifies codecs match expectations.
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get('streams', [])
        plan_items = self.ctx.extracted_items

        for i, plan_item in enumerate(plan_items):
            if i >= len(actual_streams):
                continue

            actual_stream = actual_streams[i]
            expected_codec = plan_item.track.props.codec_id.upper()
            actual_codec = actual_stream.get('codec_name', '').upper()

            # Skip if this is a corrected audio track (intentionally converted to FLAC)
            if plan_item.is_corrected and 'FLAC' in expected_codec:
                self.log(f"  ✓ Track {i}: Corrected audio (FLAC) as expected")
                continue

            # Check if codecs match
            if self._codecs_match(expected_codec, actual_codec):
                continue  # Codecs match, no issue

            track_name = plan_item.track.props.name or f"Track {i}"
            self.log(f"[WARNING] Codec mismatch for '{track_name}':")
            self.log(f"          Expected: {expected_codec}")
            self.log(f"          Actual:   {actual_codec}")
            issues += 1

        if issues == 0:
            self.log("✅ All codecs preserved correctly (no unintended transcoding).")

        return issues
