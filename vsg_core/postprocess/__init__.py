# vsg_core/postprocess/__init__.py
# -*- coding: utf-8 -*-

from .finalizer import finalize_merged_file, check_if_rebasing_is_needed

__all__ = [
    'finalize_merged_file',
    'check_if_rebasing_is_needed',
]
