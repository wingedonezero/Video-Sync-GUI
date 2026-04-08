# vsg_core/postprocess/auditors/attachments.py
from pathlib import Path

from .base import BaseAuditor


class AttachmentsAuditor(BaseAuditor):
    """Checks if expected attachments are present with correct filenames and reasonable sizes."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Comprehensive attachment audit:
        - Count verification
        - Filename verification
        - Size sanity checks (not truncated)

        Returns the number of issues found.
        """
        actual_attachments = final_mkvmerge_data.get("attachments", [])

        if not self.ctx.attachments:
            if not actual_attachments:
                self.log("✅ No attachments were planned or found.")
            else:
                self.log(
                    f"[INFO] File contains {len(actual_attachments)} attachment(s) (likely from source files)."
                )
            return 0

        expected_count = len(self.ctx.attachments)
        actual_count = len(actual_attachments)

        # Check 1: Count
        if actual_count < expected_count:
            self._report(
                f"Expected {expected_count} attachments but only found "
                f"{actual_count} - some fonts may be missing, which could "
                "affect subtitle rendering"
            )
            # Don't return early - check what we do have
        elif actual_count > expected_count:
            self.log(
                f"[INFO] Found {actual_count} attachments (expected {expected_count})."
            )
            self.log("       Extra attachments may be from source files.")

        # Check 2: Build expected attachment info
        expected_attachments = []
        for att_path in self.ctx.attachments:
            try:
                att_file = Path(att_path)
                if att_file.exists():
                    expected_attachments.append(
                        {"name": att_file.name, "size": att_file.stat().st_size}
                    )
            except Exception as e:
                self._report(f"Could not read expected attachment {att_path}: {e}")

        if not expected_attachments:
            self.log("✅ Could not verify attachment details (files not accessible).")
            return len(self.issues)

        # Check 3: Verify each expected attachment is present
        self._verify_attachments(expected_attachments, actual_attachments)

        if not self.issues:
            self.log(
                f"✅ All {len(expected_attachments)} attachment(s) verified correctly."
            )

        return len(self.issues)

    def _verify_attachments(self, expected: list[dict], actual: list[dict]) -> None:
        """
        Verify expected attachments are in the final file with correct names
        and reasonable sizes. Issues are appended to ``self.issues``.
        """
        for exp_att in expected:
            exp_name = exp_att["name"]
            exp_size = exp_att["size"]

            # Find matching attachment in actual
            matching = None
            for act_att in actual:
                act_name = act_att.get("file_name", "")
                if act_name == exp_name:
                    matching = act_att
                    break

            if not matching:
                self._report(
                    f"Expected attachment '{exp_name}' not found in final file"
                )
                continue

            # Check size
            act_size = matching.get("size")
            if act_size is None:
                self.log(f"  ✓ Attachment '{exp_name}' present (size unknown)")
                continue

            # Verify size is reasonable (within 5% or exact match for small files)
            size_diff = abs(act_size - exp_size)
            size_diff_pct = (size_diff / exp_size * 100) if exp_size > 0 else 0

            if size_diff == 0:
                self.log(f"  ✓ Attachment '{exp_name}' verified ({act_size:,} bytes)")
            elif act_size < 100:
                # File was truncated to almost nothing - definitely wrong
                self._report(
                    f"Attachment '{exp_name}' appears corrupted "
                    f"(expected {exp_size:,} bytes, got {act_size:,} bytes, "
                    "likely truncated)"
                )
            elif size_diff_pct > 5.0:
                # Size differs by more than 5% - might be wrong file
                self._report(
                    f"Attachment '{exp_name}' size mismatch "
                    f"(expected {exp_size:,} bytes, got {act_size:,} bytes, "
                    f"{size_diff_pct:.1f}% difference) - may be a different "
                    "version of the file"
                )
            else:
                # Size is close enough
                self.log(
                    f"  ✓ Attachment '{exp_name}' verified ({act_size:,} bytes, within tolerance)"
                )
