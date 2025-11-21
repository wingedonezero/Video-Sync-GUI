# vsg_core/subtitles/pgs/image.py
# -*- coding: utf-8 -*-
"""
RLE decompression and image processing for PGS subtitles.
Based on SubtitleEdit's BluRaySupParser DecodeImage implementation.
"""
from __future__ import annotations
from typing import Tuple, Optional
from PIL import Image
from .models import PcsData, OdsData, PaletteInfo
from .palette import ycbcr_to_rgba


def decompress_rle(
    buffer: bytes,
    width: int,
    height: int,
    palette: PaletteInfo,
    use_bt709: bool = False
) -> Image.Image:
    """
    Decompress RLE-encoded PGS bitmap and convert to PIL Image.
    Exactly matches SubtitleEdit's DecodeImage implementation.

    RLE encoding patterns:
        - 0xNN (non-zero): Single pixel with palette index NN
        - 0x00 0x00: End of line, move to next row
        - 0x00 0xNN: NN transparent pixels (NN < 0x40)
        - 0x00 0x4N 0xNN: Long transparent run ((N-0x40) << 8) + NN pixels
        - 0x00 0x8N 0xCC: (N-0x80) pixels of color CC
        - 0x00 0xCN 0xNN 0xCC: Long run ((N-0xC0) << 8) + NN pixels of color CC

    Args:
        buffer: RLE-compressed image data
        width: Image width in pixels
        height: Image height in pixels
        palette: Color palette
        use_bt709: If True, use BT.709 color conversion; else BT.601

    Returns:
        PIL Image in RGBA mode
    """
    # Create image
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    pixels = img.load()

    # Decode palette to RGBA
    palette_rgba = {}
    for entry in palette.entries:
        r, g, b, a = ycbcr_to_rgba(entry.y, entry.cr, entry.cb, entry.alpha, use_bt709)
        palette_rgba[entry.index] = (r, g, b, a)

    # Ensure index 0 is transparent
    if 0 not in palette_rgba:
        palette_rgba[0] = (0, 0, 0, 0)

    # Use linear offset like SubtitleEdit
    ofs = 0  # Linear pixel offset
    xpos = 0  # Current x position in line
    index = 0  # Buffer index

    def put_pixel(offset: int, color: tuple):
        """Set pixel at linear offset"""
        if offset < width * height:
            y = offset // width
            x = offset % width
            if y < height and x < width:
                pixels[x, y] = color

    # Process RLE data
    while index < len(buffer):
        b = buffer[index]
        index += 1

        if b == 0 and index < len(buffer):
            # Escape sequence
            b = buffer[index]
            index += 1

            if b == 0:
                # 0x00 0x00: End of line - move to next line boundary
                # This matches SubtitleEdit's logic exactly
                ofs = (ofs // width) * width  # Start of current line
                if xpos < width:
                    ofs += width  # Move to next line if current not complete
                xpos = 0

            elif (b & 0xC0) == 0x40:
                # 0x00 0x4N 0xNN: Long transparent run
                if index < len(buffer):
                    size = ((b - 0x40) << 8) + buffer[index]
                    index += 1
                    color = palette_rgba.get(0, (0, 0, 0, 0))
                    for _ in range(size):
                        put_pixel(ofs, color)
                        ofs += 1
                        xpos += 1

            elif (b & 0xC0) == 0x80:
                # 0x00 0x8N 0xCC: Medium run of color
                if index < len(buffer):
                    size = b - 0x80
                    color_index = buffer[index]
                    index += 1
                    color = palette_rgba.get(color_index, (0, 0, 0, 0))
                    for _ in range(size):
                        put_pixel(ofs, color)
                        ofs += 1
                        xpos += 1

            elif (b & 0xC0) == 0xC0:
                # 0x00 0xCN 0xNN 0xCC: Long run of color
                if index + 1 < len(buffer):
                    size = ((b - 0xC0) << 8) + buffer[index]
                    index += 1
                    color_index = buffer[index]
                    index += 1
                    color = palette_rgba.get(color_index, (0, 0, 0, 0))
                    for _ in range(size):
                        put_pixel(ofs, color)
                        ofs += 1
                        xpos += 1

            else:
                # 0x00 0xNN: Short transparent run
                size = b
                color = palette_rgba.get(0, (0, 0, 0, 0))
                for _ in range(size):
                    put_pixel(ofs, color)
                    ofs += 1
                    xpos += 1

        else:
            # Single pixel with palette index b
            color = palette_rgba.get(b, (0, 0, 0, 0))
            put_pixel(ofs, color)
            ofs += 1
            xpos += 1

    return img


def composite_objects(pcs: PcsData, use_bt709: bool = False) -> Optional[Tuple[Image.Image, int, int]]:
    """
    Composite all objects in a PCS into a single image.
    Handles multiple objects with relative positioning.

    Args:
        pcs: Picture Composition data
        use_bt709: Use BT.709 color conversion

    Returns:
        Tuple of (image, x_offset, y_offset) or None if no objects
        x_offset and y_offset are the top-left position of the composite
    """
    if not pcs.objects or not pcs.bitmaps or not pcs.palette:
        return None

    # If single object, just decompress it
    if len(pcs.objects) == 1 and len(pcs.bitmaps) == 1:
        obj = pcs.objects[0]
        ods = pcs.bitmaps[0]
        img = decompress_rle(ods.image_buffer, ods.width, ods.height, pcs.palette, use_bt709)
        return (img, obj.x, obj.y)

    # Multiple objects: calculate bounding box
    min_x = min(obj.x for obj in pcs.objects)
    min_y = min(obj.y for obj in pcs.objects)
    max_x = max(obj.x + ods.width for obj, ods in zip(pcs.objects, pcs.bitmaps))
    max_y = max(obj.y + ods.height for obj, ods in zip(pcs.objects, pcs.bitmaps))

    composite_width = max_x - min_x
    composite_height = max_y - min_y

    # Create composite image
    composite = Image.new('RGBA', (composite_width, composite_height), (0, 0, 0, 0))

    # Paste each object at its relative position
    for obj, ods in zip(pcs.objects, pcs.bitmaps):
        if obj.object_id == ods.object_id:
            img = decompress_rle(ods.image_buffer, ods.width, ods.height, pcs.palette, use_bt709)
            rel_x = obj.x - min_x
            rel_y = obj.y - min_y
            composite.paste(img, (rel_x, rel_y), img)

    return (composite, min_x, min_y)


def get_image_bounds(img: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """
    Get bounding box of non-transparent content in image.

    Args:
        img: PIL Image (RGBA)

    Returns:
        Tuple of (left, top, right, bottom) or None if fully transparent
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    pixels = img.load()
    width, height = img.size

    # Find bounds
    min_x = width
    min_y = height
    max_x = 0
    max_y = 0
    found = False

    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] > 10:  # Alpha > 10
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x + 1)
                max_y = max(max_y, y + 1)

    if not found:
        return None

    return (min_x, min_y, max_x, max_y)


def crop_transparent(img: Image.Image, max_crop: int = 999) -> Tuple[Image.Image, int, int]:
    """
    Crop transparent borders from image.

    Args:
        img: PIL Image (RGBA)
        max_crop: Maximum pixels to crop from each side

    Returns:
        Tuple of (cropped_image, left_cropped, top_cropped)
    """
    bounds = get_image_bounds(img)
    if bounds is None:
        return (img, 0, 0)

    left, top, right, bottom = bounds

    # Limit cropping
    left = max(0, left - max_crop) if left < max_crop else 0
    top = max(0, top - max_crop) if top < max_crop else 0

    cropped = img.crop((left, top, right, bottom))
    return (cropped, left, top)
