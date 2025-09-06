# vsg_qt/tabs/storage.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QFormLayout, QLineEdit, QPushButton, QFileDialog, QHBoxLayout
from .base import TabBase, register_tab

@register_tab
class StorageTab(TabBase):
    title = "Storage"

    def build(self, parent=None) -> QWidget:
        w = QWidget(parent)
        self.le_output = QLineEdit()
        self.btn_output = QPushButton("Browse…")
        self.btn_output.clicked.connect(self._browse_output)

        out_row = QWidget()
        out_l = QHBoxLayout(out_row); out_l.setContentsMargins(0,0,0,0)
        out_l.addWidget(self.le_output, 1); out_l.addWidget(self.btn_output)

        self.le_temp = QLineEdit()
        self.btn_temp = QPushButton("Browse…")
        self.btn_temp.clicked.connect(self._browse_temp)

        tmp_row = QWidget()
        tmp_l = QHBoxLayout(tmp_row); tmp_l.setContentsMargins(0,0,0,0)
        tmp_l.addWidget(self.le_temp, 1); tmp_l.addWidget(self.btn_temp)

        self.le_vdiff = QLineEdit()
        self.btn_vdiff = QPushButton("Browse…")
        self.btn_vdiff.clicked.connect(self._browse_vdiff)

        vd_row = QWidget()
        vd_l = QHBoxLayout(vd_row); vd_l.setContentsMargins(0,0,0,0)
        vd_l.addWidget(self.le_vdiff, 1); vd_l.addWidget(self.btn_vdiff)

        form = QFormLayout(w)
        form.addRow("Output Directory:", out_row)
        form.addRow("Temporary Directory:", tmp_row)
        form.addRow("VideoDiff Path (optional):", vd_row)
        return w

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self.widget(), "Select Output Directory", self.le_output.text())
        if path: self.le_output.setText(path)

    def _browse_temp(self):
        path = QFileDialog.getExistingDirectory(self.widget(), "Select Temporary Directory", self.le_temp.text())
        if path: self.le_temp.setText(path)

    def _browse_vdiff(self):
        path, _ = QFileDialog.getOpenFileName(self.widget(), "Select VideoDiff Executable", self.le_vdiff.text())
        if path: self.le_vdiff.setText(path)

    def load(self):
        self.le_output.setText(self.config.get('output_folder', ''))
        self.le_temp.setText(self.config.get('temp_root', ''))
        self.le_vdiff.setText(self.config.get('videodiff_path', ''))

    def save(self):
        self.config.set('output_folder', self.le_output.text())
        self.config.set('temp_root', self.le_temp.text())
        self.config.set('videodiff_path', self.le_vdiff.text())
