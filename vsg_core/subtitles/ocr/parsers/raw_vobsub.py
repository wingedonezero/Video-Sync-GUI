# vsg_core/subtitles/ocr/parsers/raw_vobsub.py
"""
Raw VobSub parser — extracts full-color RGBA images without preprocessing.

Overrides the standard VobSubParser's grayscale conversion to preserve
the original DVD subtitle bitmap colors and alpha. This produces images
with colored text (yellow, white, etc.) on a transparent background,
which work better with VLM-based OCR engines.

The standard parser converts to black-text-on-white using luminance
thresholding. This parser keeps the raw RGBA palette data intact.
"""

import numpy as np

from .vobsub import VobSubParser


class RawVobSubParser(VobSubParser):
    """
    VobSub parser that returns raw RGBA images with original DVD colors.

    Overrides only _decode_rle_image() — all other parsing logic
    (packet parsing, control sequences, timing, positioning) is
    inherited from VobSubParser unchanged.
    """

    def _decode_rle_image(
        self,
        data: bytes,
        top_offset: int,
        bottom_offset: int,
        width: int,
        height: int,
        color_indices: list[int],
        alpha_values: list[int],
        palette: list[tuple[int, int, int]],
    ) -> np.ndarray:
        """
        Decode RLE-encoded subtitle image to raw RGBA.

        Instead of converting to grayscale via luminance thresholding,
        this preserves the original DVD palette colors and alpha values.

        Returns:
            RGBA numpy array with original DVD colors
        """
        # Build 4-color RGBA palette from DVD indices
        colors = []
        for cidx, alpha in zip(color_indices, alpha_values):
            if cidx < len(palette):
                r, g, b = palette[cidx]
            else:
                r, g, b = 0, 0, 0
            a = int(alpha * 255 / 15)
            colors.append((r, g, b, a))

        # Create RGBA image (transparent background)
        image = np.zeros((height, width, 4), dtype=np.uint8)

        # Decode using the parent's RLE field decoder (handles interlaced fields)
        self._decode_rle_field(
            data, top_offset, image, 0, 2, width, height, colors
        )
        self._decode_rle_field(
            data, bottom_offset, image, 1, 2, width, height, colors
        )

        return image
