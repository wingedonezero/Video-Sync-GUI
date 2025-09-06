# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QLabel

class AnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.analysis_mode = QComboBox(); self.analysis_mode.addItems(["Audio Correlation", "VideoDiff"])

        self.scan_chunk_count = QSpinBox(); self.scan_chunk_count.setRange(1,100)
        self.scan_chunk_duration = QSpinBox(); self.scan_chunk_duration.setRange(1,120)

        self.min_match_pct = QDoubleSpinBox(); self.min_match_pct.setRange(0.1,100.0); self.min_match_pct.setDecimals(1); self.min_match_pct.setSingleStep(1.0)
        self.videodiff_error_min = QDoubleSpinBox(); self.videodiff_error_min.setRange(0.0,500.0); self.videodiff_error_min.setDecimals(2)
        self.videodiff_error_max = QDoubleSpinBox(); self.videodiff_error_max.setRange(0.0,500.0); self.videodiff_error_max.setDecimals(2)

        self.analysis_lang_ref = QLineEdit(); self.analysis_lang_ref.setPlaceholderText("Blank = first available")
        self.analysis_lang_sec = QLineEdit(); self.analysis_lang_sec.setPlaceholderText("Blank = first available")
        self.analysis_lang_ter = QLineEdit(); self.analysis_lang_ter.setPlaceholderText("Blank = first available")

        form = QFormLayout(self)
        form.addRow("Analysis Mode:", self.analysis_mode)
        form.addRow("Audio: Scan Chunks:", self.scan_chunk_count)
        form.addRow("Audio: Chunk Duration (s):", self.scan_chunk_duration)
        form.addRow("Audio: Minimum Match %:", self.min_match_pct)
        form.addRow("VideoDiff: Min Allowed Error:", self.videodiff_error_min)
        form.addRow("VideoDiff: Max Allowed Error:", self.videodiff_error_max)
        form.addRow(QLabel("<b>Analysis Audio Track Selection</b>"))
        form.addRow("REF Language:", self.analysis_lang_ref)
        form.addRow("SEC Language:", self.analysis_lang_sec)
        form.addRow("TER Language:", self.analysis_lang_ter)

    def load_from(self, cfg):
        self.analysis_mode.setCurrentText(cfg.get("analysis_mode"))
        self.scan_chunk_count.setValue(int(cfg.get("scan_chunk_count")))
        self.scan_chunk_duration.setValue(int(cfg.get("scan_chunk_duration")))
        self.min_match_pct.setValue(float(cfg.get("min_match_pct")))
        self.videodiff_error_min.setValue(float(cfg.get("videodiff_error_min")))
        self.videodiff_error_max.setValue(float(cfg.get("videodiff_error_max")))
        self.analysis_lang_ref.setText(cfg.get("analysis_lang_ref") or "")
        self.analysis_lang_sec.setText(cfg.get("analysis_lang_sec") or "")
        self.analysis_lang_ter.setText(cfg.get("analysis_lang_ter") or "")

    def store_into(self, cfg):
        cfg.set("analysis_mode", self.analysis_mode.currentText())
        cfg.set("scan_chunk_count", self.scan_chunk_count.value())
        cfg.set("scan_chunk_duration", self.scan_chunk_duration.value())
        cfg.set("min_match_pct", self.min_match_pct.value())
        cfg.set("videodiff_error_min", self.videodiff_error_min.value())
        cfg.set("videodiff_error_max", self.videodiff_error_max.value())
        cfg.set("analysis_lang_ref", self.analysis_lang_ref.text())
        cfg.set("analysis_lang_sec", self.analysis_lang_sec.text())
        cfg.set("analysis_lang_ter", self.analysis_lang_ter.text())
