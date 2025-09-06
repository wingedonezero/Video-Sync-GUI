# vsg_qt/tabs/analysis.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QLabel
from .base import TabBase, register_tab

@register_tab
class AnalysisTab(TabBase):
    title = "Analysis"

    def build(self, parent=None) -> QWidget:
        w = QWidget(parent)
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems(["Audio Correlation", "VideoDiff"])

        self.sb_chunks = QSpinBox(); self.sb_chunks.setRange(1, 100)
        self.sb_chunk_dur = QSpinBox(); self.sb_chunk_dur.setRange(1, 120)
        self.db_min_match = QDoubleSpinBox(); self.db_min_match.setRange(0.1, 100.0); self.db_min_match.setDecimals(1); self.db_min_match.setSingleStep(1.0)

        self.db_vdiff_min = QDoubleSpinBox(); self.db_vdiff_min.setRange(0.0, 500.0); self.db_vdiff_min.setDecimals(2)
        self.db_vdiff_max = QDoubleSpinBox(); self.db_vdiff_max.setRange(0.0, 500.0); self.db_vdiff_max.setDecimals(2)

        self.le_lang_ref = QLineEdit(); self.le_lang_ref.setPlaceholderText("Blank = first available")
        self.le_lang_sec = QLineEdit(); self.le_lang_sec.setPlaceholderText("Blank = first available")
        self.le_lang_ter = QLineEdit(); self.le_lang_ter.setPlaceholderText("Blank = first available")

        form = QFormLayout(w)
        form.addRow("Analysis Mode:", self.cmb_mode)
        form.addRow("Audio: Scan Chunks:", self.sb_chunks)
        form.addRow("Audio: Chunk Duration (s):", self.sb_chunk_dur)
        form.addRow("Audio: Minimum Match %:", self.db_min_match)
        form.addRow("VideoDiff: Min Allowed Error:", self.db_vdiff_min)
        form.addRow("VideoDiff: Max Allowed Error:", self.db_vdiff_max)
        form.addRow(QLabel("<b>Analysis Audio Track Selection</b>"))
        form.addRow("REF Language:", self.le_lang_ref)
        form.addRow("SEC Language:", self.le_lang_sec)
        form.addRow("TER Language:", self.le_lang_ter)
        return w

    def load(self):
        self.cmb_mode.setCurrentText(self.config.get('analysis_mode', 'Audio Correlation'))
        self.sb_chunks.setValue(int(self.config.get('scan_chunk_count', 10)))
        self.sb_chunk_dur.setValue(int(self.config.get('scan_chunk_duration', 15)))
        self.db_min_match.setValue(float(self.config.get('min_match_pct', 5.0)))
        self.db_vdiff_min.setValue(float(self.config.get('videodiff_error_min', 0.0)))
        self.db_vdiff_max.setValue(float(self.config.get('videodiff_error_max', 100.0)))
        self.le_lang_ref.setText(self.config.get('analysis_lang_ref', ''))
        self.le_lang_sec.setText(self.config.get('analysis_lang_sec', ''))
        self.le_lang_ter.setText(self.config.get('analysis_lang_ter', ''))

    def save(self):
        self.config.set('analysis_mode', self.cmb_mode.currentText())
        self.config.set('scan_chunk_count', self.sb_chunks.value())
        self.config.set('scan_chunk_duration', self.sb_chunk_dur.value())
        self.config.set('min_match_pct', self.db_min_match.value())
        self.config.set('videodiff_error_min', self.db_vdiff_min.value())
        self.config.set('videodiff_error_max', self.db_vdiff_max.value())
        self.config.set('analysis_lang_ref', self.le_lang_ref.text())
        self.config.set('analysis_lang_sec', self.le_lang_sec.text())
        self.config.set('analysis_lang_ter', self.le_lang_ter.text())
