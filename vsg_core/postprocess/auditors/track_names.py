# vsg_core/postprocess/auditors/track_names.py
# -*- coding: utf-8 -*-
from typing import Dict
from pathlib import Path

from .base import BaseAuditor


class TrackNamesAuditor(BaseAuditor):
    """Verifies track names match expectations when apply_track_name is enabled."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Audits track names.
        Returns the number of issues found.
        """
        issues = 0
        final_tracks = final_mkvmerge_data.get('tracks', [])
        plan_items = self.ctx.extracted_items

        for i, item in enumerate(plan_items):
            if not item.apply_track_name:
                continue

            if i >= len(final_tracks):
                continue

            expected_name = item.track.props.name or ''
            actual_name = final_tracks[i].get('properties', {}).get('track_name', '')

            if expected_name and expected_name != actual_name:
                self.log(f"[WARNING] Track name mismatch for track {i}:")
                self.log(f"          Expected: '{expected_name}'")
                self.log(f"          Actual:   '{actual_name}'")
                issues += 1

        if issues == 0:
            self.log("✅ All track names are correct.")

        return issues
