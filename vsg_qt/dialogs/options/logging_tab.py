# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QSpinBox

class LoggingTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_compact = QCheckBox("Use compact logging")
        self.log_autoscroll = QCheckBox("Auto-scroll log view during jobs")
        self.log_progress_step = QSpinBox(); self.log_progress_step.setRange(1, 100); self.log_progress_step.setSuffix("%")
        self.log_error_tail = QSpinBox(); self.log_error_tail.setRange(0, 1000); self.log_error_tail.setSuffix(" lines")
        self.log_show_options_pretty = QCheckBox("Show mkvmerge options in log (pretty text)")
        self.log_show_options_json = QCheckBox("Show mkvmerge options in log (raw JSON)")

        form = QFormLayout(self)
        form.addRow(self.log_compact)
        form.addRow(self.log_autoscroll)
        form.addRow("Progress Step:", self.log_progress_step)
        form.addRow("Error Tail:", self.log_error_tail)
        form.addRow(self.log_show_options_pretty)
        form.addRow(self.log_show_options_json)

    def load_from(self, cfg):
        self.log_compact.setChecked(bool(cfg.get("log_compact")))
        self.log_autoscroll.setChecked(bool(cfg.get("log_autoscroll")))
        self.log_progress_step.setValue(int(cfg.get("log_progress_step")))
        self.log_error_tail.setValue(int(cfg.get("log_error_tail")))
        self.log_show_options_pretty.setChecked(bool(cfg.get("log_show_options_pretty")))
        self.log_show_options_json.setChecked(bool(cfg.get("log_show_options_json")))

    def store_into(self, cfg):
        self.log_compact.setChecked(self.log_compact.isChecked())
        cfg.set("log_compact", self.log_compact.isChecked())
        cfg.set("log_autoscroll", self.log_autoscroll.isChecked())
        cfg.set("log_progress_step", self.log_progress_step.value())
        cfg.set("log_error_tail", self.log_error_tail.value())
        cfg.set("log_show_options_pretty", self.log_show_options_pretty.isChecked())
        cfg.set("log_show_options_json", self.log_show_options_json.isChecked())
