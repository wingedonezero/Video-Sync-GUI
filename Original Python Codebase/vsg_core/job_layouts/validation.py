# vsg_core/job_layouts/validation.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Tuple

class LayoutValidator:
    """Validates that loaded layout data is well-formed."""

    def validate(self, layout_data: Dict) -> Tuple[bool, str]:
        """Validates the structure and content of a layout data dictionary."""
        if not isinstance(layout_data, dict):
            return False, "Layout data is not a dictionary."

        required_fields = [
            'job_id', 'sources', 'enhanced_layout',
            'track_signature', 'structure_signature'
        ]
        for field in required_fields:
            if field not in layout_data:
                return False, f"Missing required field: {field}"

        if not isinstance(layout_data['enhanced_layout'], list):
            return False, "Enhanced layout must be a list."

        for i, item in enumerate(layout_data['enhanced_layout']):
            item_required = ['source', 'id', 'type', 'user_order_index']
            for field in item_required:
                if field not in item:
                    return False, f"Layout item {i} missing required field: {field}"

        return True, "Valid"
