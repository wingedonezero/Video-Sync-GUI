# vsg_core/subtitles/builders/ass.py
# -*- coding: utf-8 -*-
"""
ASS (Advanced SubStation Alpha) file builder with positioning support.
Generates ASS files that preserve subtitle positioning from image-based formats.
"""

from __future__ import annotations
from pathlib import Path
from typing import List
import pysubs2
from pysubs2 import SSAFile, SSAEvent, SSAStyle, Alignment


class ASSBuilder:
    """Builds ASS subtitle files with positioning."""

    def __init__(self, frame_width: int = 720, frame_height: int = 480):
        """
        Initialize ASS builder.

        Args:
            frame_width: Video frame width (for positioning calculations)
            frame_height: Video frame height (for positioning calculations)
        """
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.subs = SSAFile()

        # Set script info
        self.subs.info['PlayResX'] = str(frame_width)
        self.subs.info['PlayResY'] = str(frame_height)
        self.subs.info['ScriptType'] = 'v4.00+'

        # Create default style
        default_style = SSAStyle(
            fontname='Arial',
            fontsize=20,
            primarycolor=pysubs2.Color(255, 255, 255, 0),     # White
            secondarycolor=pysubs2.Color(255, 0, 0, 0),       # Red
            outlinecolor=pysubs2.Color(0, 0, 0, 0),           # Black outline
            backcolor=pysubs2.Color(0, 0, 0, 128),            # Semi-transparent black
            bold=False,
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100.0,
            scaley=100.0,
            spacing=0.0,
            angle=0.0,
            borderstyle=1,
            outline=2.0,
            shadow=2.0,
            alignment=Alignment.BOTTOM_CENTER,
            marginl=10,
            marginr=10,
            marginv=10,
            encoding=1
        )

        self.subs.styles['Default'] = default_style

    def add_event(
        self,
        start_ms: int,
        end_ms: int,
        text: str,
        x: int,
        y: int,
        width: int,
        height: int,
        preserve_position: bool = True
    ) -> None:
        """
        Add a subtitle event with positioning.

        Args:
            start_ms: Start time in milliseconds
            end_ms: End time in milliseconds
            text: Subtitle text
            x: X position of subtitle
            y: Y position of subtitle
            width: Width of subtitle
            height: Height of subtitle
            preserve_position: If True, use \\pos tag for exact positioning
        """
        if not text or not text.strip():
            return

        # Calculate alignment based on position
        alignment = self._calculate_alignment(x, y, width, height)

        # Calculate position for \pos tag
        if preserve_position:
            # Calculate center point of subtitle
            pos_x = x + (width // 2)
            pos_y = y + (height // 2)

            # Apply positioning tag
            text_with_pos = f"{{\\pos({pos_x},{pos_y})}}{text}"
        else:
            text_with_pos = text

        # Create event
        event = SSAEvent(
            start=start_ms,
            end=end_ms,
            text=text_with_pos,
            style='Default'
        )

        self.subs.events.append(event)

    def _calculate_alignment(self, x: int, y: int, width: int, height: int) -> Alignment:
        """
        Calculate alignment tag based on position.

        Returns alignment (1-9, numpad style):
        7 8 9
        4 5 6
        1 2 3
        """
        # Calculate center point
        center_x = x + (width // 2)
        center_y = y + (height // 2)

        # Determine horizontal alignment
        if center_x < self.frame_width * 0.33:
            h_align = 0  # Left (1, 4, 7)
        elif center_x < self.frame_width * 0.67:
            h_align = 1  # Center (2, 5, 8)
        else:
            h_align = 2  # Right (3, 6, 9)

        # Determine vertical alignment
        if center_y < self.frame_height * 0.33:
            v_align = 2  # Top (7, 8, 9)
        elif center_y < self.frame_height * 0.67:
            v_align = 1  # Middle (4, 5, 6)
        else:
            v_align = 0  # Bottom (1, 2, 3)

        # Calculate alignment number (1-9)
        alignment_num = 1 + h_align + (v_align * 3)

        # Convert to pysubs2 Alignment enum
        # Note: pysubs2 uses LEFT/CENTER/RIGHT for middle row, not CENTER_LEFT/etc
        alignment_map = {
            1: Alignment.BOTTOM_LEFT,
            2: Alignment.BOTTOM_CENTER,
            3: Alignment.BOTTOM_RIGHT,
            4: Alignment.LEFT,        # Middle left
            5: Alignment.CENTER,      # Middle center
            6: Alignment.RIGHT,       # Middle right
            7: Alignment.TOP_LEFT,
            8: Alignment.TOP_CENTER,
            9: Alignment.TOP_RIGHT,
        }

        return alignment_map.get(alignment_num, Alignment.BOTTOM_CENTER)

    def save(self, output_path: str) -> None:
        """
        Save ASS file to disk.

        Args:
            output_path: Path to save ASS file
        """
        self.subs.save(output_path)

    def get_subs(self) -> SSAFile:
        """Get the SSAFile object for further processing."""
        return self.subs
