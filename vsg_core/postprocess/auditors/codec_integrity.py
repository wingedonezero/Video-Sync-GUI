# vsg_core/postprocess/auditors/codec_integrity.py
from pathlib import Path

from vsg_core.models.enums import TrackType

from .base import BaseAuditor


class CodecIntegrityAuditor(BaseAuditor):
    """Ensures codecs weren't accidentally transcoded during muxing."""

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        """
        Verifies codecs match expectations, accounting for intentional conversions.
        Returns the number of issues found.
        """
        if not final_ffprobe_data:
            return 0

        issues = 0
        actual_streams = final_ffprobe_data.get("streams", [])
        plan_items = self.ctx.extracted_items

        for i, plan_item in enumerate(plan_items):
            if i >= len(actual_streams):
                continue

            actual_stream = actual_streams[i]

            # Start with the original codec from the source file
            expected_codec = plan_item.track.props.codec_id.upper()
            actual_codec = actual_stream.get("codec_name", "").upper()
            track_name = plan_item.track.props.name or f"Track {i}"

            # --- THE FIX: Adjust the 'expected_codec' based on the processing plan ---

            # If audio was corrected (e.g., for drift), the new expected codec is FLAC
            if plan_item.is_corrected:
                expected_codec = "FLAC"

            # If subtitles were processed, determine the final expected format
            if plan_item.track.type == TrackType.SUBTITLES:
                if plan_item.is_preserved:
                    # This is a preserved original, so the expected codec IS the original codec.
                    # No change is needed to expected_codec.
                    pass
                else:
                    # This is the main, processed track.
                    # If OCR was performed, the intermediate format is SRT
                    if plan_item.perform_ocr:
                        expected_codec = "S_TEXT/UTF8"
                    # If it was then converted to ASS, that is the final expected format
                    if plan_item.convert_to_ass:
                        expected_codec = "S_TEXT/ASS"

            # Now, perform the comparison with the true expected codec
            if self._codecs_match(expected_codec, actual_codec):
                continue  # Codecs match, no issue

            # If there's still a mismatch, it's a real warning
            self.log(f"[WARNING] Codec mismatch for '{track_name}':")
            self.log(f"          Expected: {expected_codec}")
            self.log(f"          Actual:   {actual_codec}")
            issues += 1

        if issues == 0:
            self.log("✅ All codecs preserved correctly (no unintended transcoding).")

        return issues
