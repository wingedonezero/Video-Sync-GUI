# vsg_core/postprocess/auditors/stepping_separated.py
"""
Auditor for stepping patterns detected in source-separated audio stems.

Automatic stepping correction is unreliable on separated stems, so when
stepping is detected in such a source the pipeline skips the fix and this
auditor surfaces a warning recommending manual review.
"""

from pathlib import Path

from .base import BaseAuditor


class SteppingSeparatedAuditor(BaseAuditor):
    """Flags sources where stepping was detected but correction was skipped."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """Emit warnings for any source-separated sources with detected stepping.

        Returns the number of issues found.
        """
        detected = self.ctx.stepping_detected_separated
        if not detected:
            return 0

        self.log(
            "[WARNING] Stepping patterns were detected in sources using "
            "source separation."
        )
        self.log(
            "[WARNING] Automatic stepping correction is unreliable on separated stems."
        )
        self.log("[WARNING] The following sources may have timing inconsistencies:")
        for source_key in detected:
            self._report(
                f"{source_key}: Stepping detected but correction skipped "
                "(source separation enabled) - manually review sync quality, "
                "and consider re-syncing without source separation if "
                "same-language audio tracks are available"
            )

        return len(self.issues)
