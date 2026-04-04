# vsg_core/subtitles/ocr/parsers/pgs.py
"""
PGS (Presentation Graphic Stream) / SUP Parser

Extracts subtitle images from Blu-ray PGS format files (.sup).
Based on the Blu-ray specification (Part 3, section 9.14),
BDSup2SubPlusPlus, and SubtitleEdit's BluRaySupParser.

PGS format uses Display Sets composed of segments:
    - PCS (0x16): Presentation Composition Segment — control/timing
    - WDS (0x17): Window Definition Segment — display window bounds
    - PDS (0x14): Palette Definition Segment — 256-entry YCbCr+A palette
    - ODS (0x15): Object Definition Segment — RLE-encoded bitmap
    - END (0x80): End of Display Set

Key characteristics:
    - Bitmaps are 8-bit indexed color (256 entries) with per-pixel alpha
    - RLE encoding is row-based, different from DVD VobSub
    - Timestamps use 90kHz PTS clock
    - End times are implicit (derived from next display set's start time)
    - ODS can be fragmented across multiple segments
    - Up to 2 objects can be displayed simultaneously per composition

Region grouping note:
    PGS objects carry position metadata (pgs_objects field on SubtitleImage)
    which is used by the pipeline's _group_lines_pgs() for object-level
    region classification. This is different from VobSub's line-level grouping
    because PGS objects physically separate dialogue from signs.

Validated on 55,645 display sets (89,421 lines) across 167 files.
"""

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .base import ParseResult, SubtitleImage, SubtitleImageParser

logger = logging.getLogger(__name__)

# PGS segment type IDs
SEG_PDS = 0x14  # Palette Definition Segment
SEG_ODS = 0x15  # Object Definition Segment
SEG_PCS = 0x16  # Presentation Composition Segment
SEG_WDS = 0x17  # Window Definition Segment
SEG_END = 0x80  # End of Display Set

# PGS magic bytes
PGS_MAGIC = b"PG"

# Composition states
COMP_NORMAL = 0x00
COMP_ACQUISITION = 0x40
COMP_EPOCH_START = 0x80

# ODS sequence flags
ODS_FIRST = 0x80
ODS_LAST = 0x40
ODS_FIRST_AND_LAST = 0xC0

# Timing
PTS_CLOCK_HZ = 90000  # 90kHz clock


@dataclass(slots=True)
class PaletteEntry:
    """Single palette entry in YCbCr + Alpha."""

    y: int = 0
    cr: int = 0
    cb: int = 0
    alpha: int = 0


@dataclass(slots=True)
class CompositionObject:
    """Object reference within a Presentation Composition Segment."""

    object_id: int = 0
    window_id: int = 0
    forced: bool = False
    cropped: bool = False
    x: int = 0
    y: int = 0
    crop_x: int = 0
    crop_y: int = 0
    crop_width: int = 0
    crop_height: int = 0


@dataclass(slots=True)
class WindowDefinition:
    """Window bounds from WDS."""

    window_id: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class ObjectDefinition:
    """Object bitmap data from ODS (potentially fragmented)."""

    object_id: int = 0
    version: int = 0
    width: int = 0
    height: int = 0
    rle_data: bytearray = field(default_factory=bytearray)
    is_complete: bool = False


@dataclass(slots=True)
class DisplaySet:
    """
    Complete display set — one subtitle event.

    A display set contains all segments needed to render one subtitle frame.
    """

    pts_ms: float = 0.0  # Start time in milliseconds
    composition_state: int = 0
    palette_update_only: bool = False
    palette_id: int = 0
    composition_number: int = 0
    composition_objects: list[CompositionObject] = field(default_factory=list)
    windows: list[WindowDefinition] = field(default_factory=list)
    palette: list[PaletteEntry] = field(
        default_factory=lambda: [PaletteEntry()] * 256
    )
    objects: dict[int, ObjectDefinition] = field(default_factory=dict)
    video_width: int = 1920
    video_height: int = 1080


class PGSParser(SubtitleImageParser):
    """
    Parser for PGS/SUP (.sup) Blu-ray subtitle format.

    Extracts subtitle bitmaps with timing and position information.
    PGS subtitles are always raw RGBA — no grayscale variant needed
    since Blu-ray palettes are full-color with per-pixel alpha.
    """

    def can_parse(self, file_path: Path) -> bool:
        """Check if file is a PGS/SUP file."""
        if file_path.suffix.lower() != ".sup":
            return False
        # Check magic bytes
        try:
            with open(file_path, "rb") as f:
                magic = f.read(2)
                return magic == PGS_MAGIC
        except OSError:
            return False

    def parse(self, file_path: Path, work_dir: Path | None = None) -> ParseResult:
        """
        Parse PGS/SUP file and extract subtitle images.

        Each renderable display set produces one SubtitleImage with:
        - Full-frame RGBA image (all objects composited onto video-sized canvas)
        - pgs_objects: list of composition object positions for region grouping

        Args:
            file_path: Path to .sup file
            work_dir: Optional working directory (unused for PGS)

        Returns:
            ParseResult with extracted subtitle images
        """
        result = ParseResult()

        if not file_path.exists():
            result.errors.append(f"SUP file not found: {file_path}")
            return result

        try:
            display_sets = self._parse_segments(file_path)

            if not display_sets:
                result.warnings.append("No display sets found in SUP file")
                return result

            # Get video dimensions from first display set
            video_w = display_sets[0].video_width
            video_h = display_sets[0].video_height

            result.format_info = {
                "format": "PGS",
                "frame_size": (video_w, video_h),
                "display_set_count": len(display_sets),
            }

            # Convert display sets to SubtitleImages
            subtitle_index = 0
            for i, ds in enumerate(display_sets):
                # Skip empty compositions (these are "clear" events for timing)
                if not ds.composition_objects:
                    continue

                # Skip palette-update-only sets (bitmap unchanged)
                if ds.palette_update_only:
                    continue

                try:
                    images = self._render_display_set(ds, video_w, video_h)
                except Exception as e:
                    result.warnings.append(
                        f"Failed to render display set {i}: {e}"
                    )
                    continue

                if not images:
                    continue

                # Calculate end time from next display set
                end_ms = self._find_end_time(display_sets, i)

                # Build pgs_objects metadata for region grouping.
                # Each composition object's position + decoded bitmap size.
                pgs_objects = []
                for co in ds.composition_objects:
                    obj = ds.objects.get(co.object_id)
                    if obj is not None and obj.is_complete:
                        pgs_objects.append(
                            {
                                "pgs_x": co.x,
                                "pgs_y": co.y,
                                "obj_w": obj.width,
                                "obj_h": obj.height,
                            }
                        )

                for img, x, y, forced in images:
                    if img is None:
                        continue

                    sub = SubtitleImage(
                        index=subtitle_index,
                        start_ms=int(ds.pts_ms),
                        end_ms=int(end_ms),
                        image=img,
                        x=x,
                        y=y,
                        frame_width=video_w,
                        frame_height=video_h,
                        is_forced=forced,
                        pgs_objects=pgs_objects if pgs_objects else None,
                    )
                    result.subtitles.append(sub)
                    subtitle_index += 1

        except Exception as e:
            result.errors.append(f"Failed to parse PGS: {e}")

        return result

    def _parse_segments(self, file_path: Path) -> list[DisplaySet]:
        """
        Parse all segments from a PGS/SUP file.

        Reads the file sequentially, accumulating segments into display sets.
        A new display set starts with each PCS segment.

        Returns:
            List of complete DisplaySets
        """
        display_sets: list[DisplaySet] = []
        current_ds: DisplaySet | None = None

        # Epoch-level state: persists across display sets within an epoch
        epoch_palettes: dict[int, list[PaletteEntry]] = {}
        epoch_objects: dict[int, ObjectDefinition] = {}

        file_size = file_path.stat().st_size

        with open(file_path, "rb") as f:
            while f.tell() < file_size:
                # Read segment header (13 bytes)
                header = f.read(13)
                if len(header) < 13:
                    break

                # Validate magic
                if header[0:2] != PGS_MAGIC:
                    logger.warning(
                        f"Invalid PGS magic at offset {f.tell() - 13}, "
                        f"got {header[0:2]!r}"
                    )
                    # Try to resync by scanning for next PG magic
                    if not self._resync(f, file_size):
                        break
                    continue

                # Parse header fields
                pts = struct.unpack(">I", header[2:6])[0]
                # DTS at header[6:10] — always 0 in practice, ignored
                seg_type = header[10]
                seg_size = struct.unpack(">H", header[11:13])[0]

                pts_ms = pts / 90.0

                # Read segment payload
                if seg_size > 0:
                    payload = f.read(seg_size)
                    if len(payload) < seg_size:
                        logger.warning(
                            f"Truncated segment at offset {f.tell()}: "
                            f"expected {seg_size}, got {len(payload)}"
                        )
                        break
                else:
                    payload = b""

                # Process by segment type
                if seg_type == SEG_PCS:
                    # New display set starts with each PCS
                    if current_ds is not None:
                        display_sets.append(current_ds)

                    current_ds = self._parse_pcs(payload, pts_ms)
                    if current_ds is None:
                        continue

                    # Handle epoch state
                    if current_ds.composition_state == COMP_EPOCH_START:
                        # Epoch start: clear all state
                        epoch_palettes.clear()
                        epoch_objects.clear()
                    else:
                        # Normal/acquisition: inherit epoch state
                        # Deep copy palette entries
                        for pid, pal in epoch_palettes.items():
                            if pid == current_ds.palette_id:
                                current_ds.palette = [
                                    PaletteEntry(
                                        y=e.y, cr=e.cr, cb=e.cb, alpha=e.alpha
                                    )
                                    for e in pal
                                ]
                        current_ds.objects = {
                            oid: ObjectDefinition(
                                object_id=obj.object_id,
                                version=obj.version,
                                width=obj.width,
                                height=obj.height,
                                rle_data=bytearray(obj.rle_data),
                                is_complete=obj.is_complete,
                            )
                            for oid, obj in epoch_objects.items()
                        }

                elif seg_type == SEG_WDS:
                    if current_ds is not None:
                        self._parse_wds(payload, current_ds)

                elif seg_type == SEG_PDS:
                    if current_ds is not None:
                        self._parse_pds(payload, current_ds)
                        # Update epoch palette
                        epoch_palettes[current_ds.palette_id] = [
                            PaletteEntry(
                                y=e.y, cr=e.cr, cb=e.cb, alpha=e.alpha
                            )
                            for e in current_ds.palette
                        ]

                elif seg_type == SEG_ODS:
                    if current_ds is not None:
                        self._parse_ods(payload, current_ds)
                        # Update epoch objects
                        for oid, obj in current_ds.objects.items():
                            if obj.is_complete:
                                epoch_objects[oid] = ObjectDefinition(
                                    object_id=obj.object_id,
                                    version=obj.version,
                                    width=obj.width,
                                    height=obj.height,
                                    rle_data=bytearray(obj.rle_data),
                                    is_complete=True,
                                )

                elif seg_type == SEG_END:
                    # End of display set — finalize
                    if current_ds is not None:
                        display_sets.append(current_ds)
                        current_ds = None

                else:
                    logger.debug(
                        f"Unknown segment type 0x{seg_type:02X} "
                        f"at PTS {pts_ms:.1f}ms"
                    )

        # Don't lose last display set if file doesn't end with END segment
        if current_ds is not None:
            display_sets.append(current_ds)

        logger.info(
            f"Parsed {len(display_sets)} display sets from {file_path.name}"
        )
        return display_sets

    def _resync(self, f, file_size: int) -> bool:
        """
        Try to resync to the next PG magic bytes after a parse error.

        Returns True if resync succeeded, False if EOF reached.
        """
        # Back up 1 byte in case magic is at current position
        pos = f.tell()
        if pos > 0:
            f.seek(pos - 1)

        while f.tell() < file_size - 13:
            byte = f.read(1)
            if not byte:
                return False
            if byte == b"P":
                next_byte = f.read(1)
                if not next_byte:
                    return False
                if next_byte == b"G":
                    # Found PG — back up so the main loop reads the full header
                    f.seek(f.tell() - 2)
                    return True
        return False

    def _parse_pcs(
        self, payload: bytes, pts_ms: float
    ) -> DisplaySet | None:
        """
        Parse Presentation Composition Segment.

        Layout:
            0-1:  Video width
            2-3:  Video height
            4:    Frame rate (high nibble) | reserved
            5-6:  Composition number
            7:    Composition state
            8:    Palette update flag (0x80 = palette update only)
            9:    Palette ID
            10:   Number of composition objects
            11+:  Composition object data (8+ bytes each)
        """
        if len(payload) < 11:
            logger.warning(f"PCS too short: {len(payload)} bytes")
            return None

        ds = DisplaySet()
        ds.pts_ms = pts_ms
        ds.video_width = struct.unpack(">H", payload[0:2])[0]
        ds.video_height = struct.unpack(">H", payload[2:4])[0]
        # payload[4] = frame rate | reserved (not needed for parsing)
        ds.composition_number = struct.unpack(">H", payload[5:7])[0]
        ds.composition_state = payload[7]
        ds.palette_update_only = (payload[8] & 0x80) != 0
        ds.palette_id = payload[9]

        num_objects = payload[10]

        # Parse composition objects
        offset = 11
        for _ in range(num_objects):
            if offset + 8 > len(payload):
                break

            co = CompositionObject()
            co.object_id = struct.unpack(
                ">H", payload[offset : offset + 2]
            )[0]
            co.window_id = payload[offset + 2]

            flags = payload[offset + 3]
            co.cropped = (flags & 0x80) != 0
            co.forced = (flags & 0x40) != 0

            co.x = struct.unpack(">H", payload[offset + 4 : offset + 6])[0]
            co.y = struct.unpack(">H", payload[offset + 6 : offset + 8])[0]
            offset += 8

            # Cropping data (optional, 8 additional bytes)
            if co.cropped and offset + 8 <= len(payload):
                co.crop_x = struct.unpack(
                    ">H", payload[offset : offset + 2]
                )[0]
                co.crop_y = struct.unpack(
                    ">H", payload[offset + 2 : offset + 4]
                )[0]
                co.crop_width = struct.unpack(
                    ">H", payload[offset + 4 : offset + 6]
                )[0]
                co.crop_height = struct.unpack(
                    ">H", payload[offset + 6 : offset + 8]
                )[0]
                offset += 8

            ds.composition_objects.append(co)

        return ds

    def _parse_wds(self, payload: bytes, ds: DisplaySet) -> None:
        """
        Parse Window Definition Segment.

        Layout:
            0:    Number of windows
            1+:   Per window (9 bytes each):
                  0:    Window ID
                  1-2:  X position
                  3-4:  Y position
                  5-6:  Width
                  7-8:  Height
        """
        if len(payload) < 1:
            return

        num_windows = payload[0]
        offset = 1
        for _ in range(num_windows):
            if offset + 9 > len(payload):
                break

            wd = WindowDefinition()
            wd.window_id = payload[offset]
            wd.x = struct.unpack(">H", payload[offset + 1 : offset + 3])[0]
            wd.y = struct.unpack(">H", payload[offset + 3 : offset + 5])[0]
            wd.width = struct.unpack(
                ">H", payload[offset + 5 : offset + 7]
            )[0]
            wd.height = struct.unpack(
                ">H", payload[offset + 7 : offset + 9]
            )[0]
            offset += 9

            ds.windows.append(wd)

    def _parse_pds(self, payload: bytes, ds: DisplaySet) -> None:
        """
        Parse Palette Definition Segment.

        Layout:
            0:    Palette ID
            1:    Palette version
            2+:   Palette entries (5 bytes each):
                  0:    Entry ID (index 0-255)
                  1:    Y (luminance)
                  2:    Cr (color difference red)
                  3:    Cb (color difference blue)
                  4:    Alpha (0=transparent, 255=opaque)
        """
        if len(payload) < 2:
            return

        # payload[0] = palette ID, payload[1] = version
        # We use the palette already on the display set

        offset = 2
        while offset + 5 <= len(payload):
            entry_id = payload[offset]
            if entry_id < 256:
                ds.palette[entry_id] = PaletteEntry(
                    y=payload[offset + 1],
                    cr=payload[offset + 2],
                    cb=payload[offset + 3],
                    alpha=payload[offset + 4],
                )
            offset += 5

    def _parse_ods(self, payload: bytes, ds: DisplaySet) -> None:
        """
        Parse Object Definition Segment (potentially fragmented).

        Layout (first fragment):
            0-1:  Object ID
            2:    Version number
            3:    Sequence flag (0x80=first, 0x40=last, 0xC0=both)
            4-6:  Object data length (3 bytes, includes width+height)
            7-8:  Width
            9-10: Height
            11+:  RLE data

        Layout (continuation fragments):
            0-1:  Object ID
            2:    Version number
            3:    Sequence flag
            4+:   RLE data (no width/height)
        """
        if len(payload) < 4:
            return

        object_id = struct.unpack(">H", payload[0:2])[0]
        # version = payload[2]
        seq_flag = payload[3]

        is_first = (seq_flag & ODS_FIRST) != 0
        is_last = (seq_flag & ODS_LAST) != 0

        if is_first:
            # First (or only) fragment — has width/height
            if len(payload) < 11:
                return

            # Object data length is 3 bytes at offset 4
            obj_data_len = (
                (payload[4] << 16) | (payload[5] << 8) | payload[6]
            )
            width = struct.unpack(">H", payload[7:9])[0]
            height = struct.unpack(">H", payload[9:11])[0]

            obj = ObjectDefinition(
                object_id=object_id,
                version=payload[2],
                width=width,
                height=height,
            )
            # RLE data starts at offset 11
            obj.rle_data = bytearray(payload[11:])

            # Actual RLE length = obj_data_len - 4 (width + height fields)
            expected_rle_len = obj_data_len - 4
            obj.is_complete = is_last or len(obj.rle_data) >= expected_rle_len

            ds.objects[object_id] = obj

            logger.debug(
                f"ODS first: id={object_id} {width}x{height} "
                f"rle={len(obj.rle_data)}/{expected_rle_len} "
                f"complete={obj.is_complete}"
            )
        else:
            # Continuation fragment — append RLE data
            if object_id not in ds.objects:
                logger.warning(
                    f"ODS continuation for unknown object {object_id}"
                )
                return

            obj = ds.objects[object_id]
            obj.rle_data.extend(payload[4:])
            if is_last:
                obj.is_complete = True

            logger.debug(
                f"ODS continuation: id={object_id} "
                f"+{len(payload) - 4} bytes, "
                f"total={len(obj.rle_data)}, complete={obj.is_complete}"
            )

    def _render_display_set(
        self, ds: DisplaySet, video_w: int, video_h: int
    ) -> list[tuple[np.ndarray | None, int, int, bool]]:
        """
        Render display set to a single full-frame RGBA image.

        All composition objects are composited onto a video-sized canvas
        at their PGS-specified positions. This produces an image identical
        to what VobSub returns — full frame with text on transparent bg.
        The OCR pipeline can then process it identically to VobSub.

        Returns:
            List with a single (image, x=0, y=0, forced) tuple,
            or empty list if nothing to render.
        """
        if not ds.composition_objects:
            return []

        # Build RGBA palette from YCbCr + Alpha
        rgba_palette = self._build_rgba_palette(ds.palette)

        # Decode all objects first
        decoded = []
        for co in ds.composition_objects:
            obj = ds.objects.get(co.object_id)
            if obj is None or not obj.is_complete:
                logger.debug(
                    f"Missing/incomplete object {co.object_id} "
                    f"at PTS {ds.pts_ms:.1f}ms"
                )
                continue

            if obj.width <= 0 or obj.height <= 0:
                continue

            # Decode RLE bitmap
            bitmap = self._decode_rle(
                bytes(obj.rle_data), obj.width, obj.height
            )
            if bitmap is None:
                continue

            # Apply palette to get RGBA image
            image = self._apply_palette(bitmap, rgba_palette)

            # Apply cropping if flagged
            if co.cropped:
                cx = max(0, co.crop_x)
                cy = max(0, co.crop_y)
                cw = min(co.crop_width, image.shape[1] - cx)
                ch = min(co.crop_height, image.shape[0] - cy)
                if cw > 0 and ch > 0:
                    image = image[cy : cy + ch, cx : cx + cw].copy()

            decoded.append((image, co.x, co.y, co.forced))

        if not decoded:
            return []

        # Composite all objects onto a full-frame canvas
        frame = np.zeros((video_h, video_w, 4), dtype=np.uint8)
        forced = any(d[3] for d in decoded)

        for img, ox, oy, _ in decoded:
            h, w = img.shape[:2]
            # Clamp to frame bounds
            y_end = min(oy + h, video_h)
            x_end = min(ox + w, video_w)
            paste_h = y_end - oy
            paste_w = x_end - ox
            if paste_h > 0 and paste_w > 0:
                # Simple paste (PGS objects don't overlap in practice)
                region = frame[oy:y_end, ox:x_end]
                src = img[:paste_h, :paste_w]
                # Only paste where source has alpha > 0
                mask = src[:, :, 3] > 0
                region[mask] = src[mask]

        return [(frame, 0, 0, forced)]

    def _build_rgba_palette(
        self, palette: list[PaletteEntry]
    ) -> np.ndarray:
        """
        Convert PGS YCbCr + Alpha palette to RGBA.

        BT.709 color space conversion (Blu-ray standard):
            R = Y + 1.5748 * (Cr - 128)
            G = Y - 0.1873 * (Cb - 128) - 0.4681 * (Cr - 128)
            B = Y + 1.8556 * (Cb - 128)

        Returns:
            256x4 numpy array of RGBA values
        """
        rgba = np.zeros((256, 4), dtype=np.uint8)

        for i, entry in enumerate(palette):
            if i >= 256:
                break

            # Index 0xFF is always fully transparent by spec
            if i == 0xFF:
                rgba[i] = [0, 0, 0, 0]
                continue

            # Transparent entries: force to black to avoid scaling artifacts
            if entry.alpha < 14:
                rgba[i] = [0, 0, 0, 0]
                continue

            y_val = entry.y
            cr = entry.cr - 128
            cb = entry.cb - 128

            # BT.709 YCbCr to RGB
            r = y_val + 1.5748 * cr
            g = y_val - 0.1873 * cb - 0.4681 * cr
            b = y_val + 1.8556 * cb

            rgba[i] = [
                int(np.clip(r, 0, 255)),
                int(np.clip(g, 0, 255)),
                int(np.clip(b, 0, 255)),
                entry.alpha,
            ]

        return rgba

    def _decode_rle(
        self, data: bytes, width: int, height: int
    ) -> np.ndarray | None:
        """
        Decode PGS RLE-encoded bitmap to palette index array.

        PGS RLE encoding (per row, terminated by 0x00 0x00):

        Byte sequence          Meaning
        CC (non-zero)          1 pixel of color CC
        00 00                  End of line
        00 LL (01-3F)          LL pixels of color 0 (transparent)
        00 4L LL               ((first-0x40)<<8 + second) pixels of color 0
        00 8L CC               (first-0x80) pixels of color CC
        00 CL LL CC            ((first-0xC0)<<8 + second) pixels of color CC

        Returns:
            2D numpy array of palette indices, or None on failure
        """
        bitmap = np.zeros((height, width), dtype=np.uint8)
        pos = 0
        x = 0
        y = 0
        data_len = len(data)

        while pos < data_len and y < height:
            byte = data[pos]
            pos += 1

            if byte != 0:
                # Non-zero: single pixel of this color
                if x < width:
                    bitmap[y, x] = byte
                x += 1
            else:
                # Zero byte: check next byte for run type
                if pos >= data_len:
                    break

                byte2 = data[pos]
                pos += 1

                if byte2 == 0:
                    # 00 00: End of line
                    x = 0
                    y += 1

                elif byte2 < 0x40:
                    # 00 LL: short run of color 0 (transparent)
                    run_len = byte2
                    # Color 0 is default in the zero-initialized array
                    x += run_len

                elif byte2 < 0x80:
                    # 00 4L LL: long run of color 0
                    if pos >= data_len:
                        break
                    byte3 = data[pos]
                    pos += 1
                    run_len = ((byte2 - 0x40) << 8) | byte3
                    x += run_len

                elif byte2 < 0xC0:
                    # 00 8L CC: short run of color CC
                    if pos >= data_len:
                        break
                    color = data[pos]
                    pos += 1
                    run_len = byte2 - 0x80
                    if run_len > 0 and x < width:
                        end_x = min(x + run_len, width)
                        bitmap[y, x:end_x] = color
                    x += run_len

                else:
                    # 00 CL LL CC: long run of color CC
                    if pos + 1 >= data_len:
                        break
                    byte3 = data[pos]
                    color = data[pos + 1]
                    pos += 2
                    run_len = ((byte2 - 0xC0) << 8) | byte3
                    if run_len > 0 and x < width:
                        end_x = min(x + run_len, width)
                        bitmap[y, x:end_x] = color
                    x += run_len

        return bitmap

    def _apply_palette(
        self, bitmap: np.ndarray, rgba_palette: np.ndarray
    ) -> np.ndarray:
        """
        Apply RGBA palette to indexed bitmap.

        Uses numpy fancy indexing for fast palette lookup.

        Args:
            bitmap: 2D array of palette indices (H x W)
            rgba_palette: 256x4 RGBA palette array

        Returns:
            RGBA image array (H x W x 4)
        """
        return rgba_palette[bitmap]

    def _find_end_time(
        self, display_sets: list[DisplaySet], current_idx: int
    ) -> float:
        """
        Find end time for a display set.

        PGS has no explicit end time. The end is determined by:
        1. Next display set's PTS (which either clears or replaces)
        2. If last display set: start + 5000ms default

        This matches BDSup2Sub++ and SubtitleEdit behavior.
        """
        current_pts = display_sets[current_idx].pts_ms

        # Look for next display set (any type — clear, replace, or update)
        for i in range(current_idx + 1, len(display_sets)):
            next_pts = display_sets[i].pts_ms
            if next_pts > current_pts:
                return next_pts

        # Last display set: default 5 second duration
        return current_pts + 5000.0
