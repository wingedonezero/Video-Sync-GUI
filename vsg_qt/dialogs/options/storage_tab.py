# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout
from .base import make_dir_input, make_file_input, get_text, set_text

class StorageTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.output_folder = make_dir_input()
        self.temp_root = make_dir_input()
        self.videodiff_path = make_file_input()

        form = QFormLayout(self)
        form.addRow("Output Directory:", self.output_folder)
        form.addRow("Temporary Directory:", self.temp_root)
        form.addRow("VideoDiff Path (optional):", self.videodiff_path)

    def load_from(self, cfg):
        set_text(self.output_folder, cfg.get("output_folder"))
        set_text(self.temp_root, cfg.get("temp_root"))
        set_text(self.videodiff_path, cfg.get("videodiff_path"))

    def store_into(self, cfg):
        cfg.set("output_folder", get_text(self.output_folder))
        cfg.set("temp_root", get_text(self.temp_root))
        cfg.set("videodiff_path", get_text(self.videodiff_path))
