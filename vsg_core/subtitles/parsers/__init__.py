# vsg_core/subtitles/parsers/__init__.py
# -*- coding: utf-8 -*-
"""Subtitle format parsers for OCR processing."""

from .vobsub import VobSubParser, VobSubEvent

__all__ = ['VobSubParser', 'VobSubEvent']
