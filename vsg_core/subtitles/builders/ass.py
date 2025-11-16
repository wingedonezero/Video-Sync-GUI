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
        preserve_position: bool = False  # Changed default to False
    ) -> None:
        """
        Add a subtitle event with positioning.

        Args:
            start_ms: Start time in milliseconds
            end_ms: End time in milliseconds
            text: Subtitle text
            x: X position of subtitle (ignored if preserve_position=False)
            y: Y position of subtitle (ignored if preserve_position=False)
            width: Width of subtitle
            height: Height of subtitle
            preserve_position: If True, use \\pos tag for exact positioning (default: False)
        """
        if not text or not text.strip():
            return

        # Most apps output to SRT with no positioning, so use default positioning
        # Custom positioning can cause issues with players and isn't always accurate
        if preserve_position:
            # Use top-left corner directly (no offset needed)
            # Alignment 7 = top left, so \pos() positions the top-left of the text
            pos_x = x
            pos_y = y

            # Apply positioning with alignment 7 (top-left)
            # This ensures \pos(x,y) places the text exactly where it was in the original
            text_with_pos = f"{{\\an7\\pos({pos_x},{pos_y})}}{text}"
        else:
            # Use default positioning (bottom center)
            text_with_pos = text

        # Create event
        event = SSAEvent(
            start=start_ms,
            end=end_ms,
            text=text_with_pos,
            style='Default'
        )

        self.subs.events.append(event)

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
