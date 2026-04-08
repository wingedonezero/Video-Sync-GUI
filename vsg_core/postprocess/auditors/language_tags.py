# vsg_core/postprocess/auditors/language_tags.py
from pathlib import Path

from .base import BaseAuditor


class LanguageTagsAuditor(BaseAuditor):
    """Verifies language tags were preserved correctly."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Audits language tags, respecting custom language overrides.
        Returns the number of issues found.
        """
        final_tracks = final_mkvmerge_data.get("tracks", [])
        plan_items = self.ctx.extracted_items

        for i, item in enumerate(plan_items):
            if i >= len(final_tracks):
                continue

            # Use custom language if set, otherwise use original
            expected_lang = (
                item.custom_lang
                if item.custom_lang
                else (item.track.props.lang or "und")
            )
            actual_lang = final_tracks[i].get("properties", {}).get("language", "und")

            if expected_lang != actual_lang:
                track_name = item.track.props.name or f"Track {i}"
                self._report(
                    f"Language tag mismatch for '{track_name}': expected "
                    f"'{expected_lang}', actual '{actual_lang}'"
                )

        if not self.issues:
            self.log("✅ All language tags are correct.")

        return len(self.issues)
