# vsg_core/job_layouts/persistence.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Callable

class LayoutPersistence:
    """Handles saving and loading job layouts to/from JSON files."""

    def __init__(self, layouts_dir: Path, log_callback: Callable[[str], None]):
        self.layouts_dir = layouts_dir
        self.log = log_callback
        self.layouts_dir.mkdir(parents=True, exist_ok=True)

    def save_layout(self, job_id: str, layout_data: Dict) -> bool:
        """Saves a job layout using a temporary file to prevent corruption."""
        try:
            # *** THE FIX IS HERE ***
            # Ensure the target directory exists right before saving.
            self.layouts_dir.mkdir(parents=True, exist_ok=True)

            layout_file = self.layouts_dir / f"{job_id}.json"
            temp_file = layout_file.with_suffix('.tmp')

            layout_data['saved_timestamp'] = datetime.now().isoformat()

            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(layout_data, f, indent=2, ensure_ascii=False)

            temp_file.replace(layout_file)
            return True
        except Exception as e:
            self.log(f"[LayoutPersistence] Error saving layout for {job_id}: {e}")
            return False

    def load_layout(self, job_id: str) -> Optional[Dict]:
        """Loads a job layout from a JSON file."""
        try:
            layout_file = self.layouts_dir / f"{job_id}.json"
            if not layout_file.exists():
                return None

            with open(layout_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.log(f"[LayoutPersistence] Error loading layout for {job_id}: {e}")
            return None

    def layout_exists(self, job_id: str) -> bool:
        """Checks if a layout file exists."""
        return (self.layouts_dir / f"{job_id}.json").exists()

    def delete_layout(self, job_id: str) -> bool:
        """Deletes a specific layout file."""
        try:
            layout_file = self.layouts_dir / f"{job_id}.json"
            if layout_file.exists():
                layout_file.unlink()
            return True
        except Exception as e:
            self.log(f"[LayoutPersistence] Error deleting layout {job_id}: {e}")
            return False

    def cleanup_all(self):
        """Removes all layout files and the layouts directory."""
        try:
            if self.layouts_dir.exists():
                shutil.rmtree(self.layouts_dir)
                self.log("[LayoutPersistence] Cleaned up all temporary layout files.")
        except Exception as e:
            self.log(f"[LayoutPersistence] Error during cleanup: {e}")
