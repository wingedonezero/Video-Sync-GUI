# vsg_core/postprocess/__init__.py
# -*- coding: utf-8 -*-

from .finalizer import finalize_merged_file, check_if_rebasing_is_needed
from .metadata_patcher import MetadataPatcher

__all__ = [
    'finalize_merged_file',
    'check_if_rebasing_is_needed',
    'MetadataPatcher',
]
