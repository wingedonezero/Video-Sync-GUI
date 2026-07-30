# vsg_core/postprocess/auditors/flac_conversion.py
from pathlib import Path

from .base import BaseAuditor


class FlacConversionAuditor(BaseAuditor):
    """Surfaces FLAC conversion outcomes and verifies converted tracks muxed as FLAC.

    Conversion failures keep the original track in the mux (by design), but
    must be reported so the user knows their conversion request was not
    honored. Skips (object-based audio, pending correction, lossy codecs)
    are informational only.
    """

    def run(
        self, final_mkv_path: Path, final_mkvmerge_data: dict, final_ffprobe_data=None
    ) -> int:
        converted_items = [
            item for item in (self.ctx.extracted_items or []) if item.flac_converted
        ]

        if not (
            converted_items
            or self.ctx.flac_conversion_failures
            or self.ctx.flac_conversion_skips
        ):
            self.log("No FLAC conversions were requested for this job.")
            return 0

        for entry in self.ctx.flac_conversion_failures:
            self._report(f"FLAC conversion failed (original track kept): {entry}")

        for entry in self.ctx.flac_conversion_skips:
            self.log(f"[INFO] FLAC conversion skipped: {entry}")

        # Verify each converted track really landed in the output as FLAC.
        # By this point FinalAuditor has re-sorted extracted_items to match
        # the final mux order, so plan index == output track index.
        final_tracks = final_mkvmerge_data.get("tracks", [])
        for i, item in enumerate(self.ctx.extracted_items or []):
            if not item.flac_converted:
                continue
            if i >= len(final_tracks):
                self._report(
                    f"Converted track at plan index {i} not found in final file"
                )
                continue
            actual_codec = (
                final_tracks[i].get("properties", {}).get("codec_id", "") or ""
            )
            source_label = f"{item.track.source} track {item.track.id}"
            if actual_codec.upper() != "A_FLAC":
                self._report(
                    f"Converted track ({source_label}) expected A_FLAC in output, "
                    f"found '{actual_codec}'"
                )
            else:
                self.log(f"✅ {source_label} muxed as FLAC (converted, verified).")

        if not self.issues:
            self.log("✅ FLAC conversion audit clean.")

        return len(self.issues)
