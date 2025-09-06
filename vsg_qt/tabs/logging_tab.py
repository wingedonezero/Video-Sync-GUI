# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QSpinBox
from ._widgets import get_val, set_val

class LoggingTab(QWidget):
    """
    Logging/output preferences.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = {}
        form = QFormLayout(self)

        self.controls['log_compact'] = QCheckBox('Use compact logging')
        self.controls['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs')
        self.controls['log_progress_step'] = QSpinBox(); self.controls['log_progress_step'].setRange(1, 100); self.controls['log_progress_step'].setSuffix('%')
        self.controls['log_error_tail'] = QSpinBox(); self.controls['log_error_tail'].setRange(0, 1000); self.controls['log_error_tail'].setSuffix(' lines')
        self.controls['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)')
        self.controls['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)')

        form.addRow(self.controls['log_compact'])
        form.addRow(self.controls['log_autoscroll'])
        form.addRow('Progress Step:', self.controls['log_progress_step'])
        form.addRow('Error Tail:', self.controls['log_error_tail'])
        form.addRow(self.controls['log_show_options_pretty'])
        form.addRow(self.controls['log_show_options_json'])

    def load(self, cfg: dict):
        for k, w in self.controls.items():
            set_val(w, cfg.get(k))

    def dump(self) -> dict:
        return {k: get_val(w) for k, w in self.controls.items()}
