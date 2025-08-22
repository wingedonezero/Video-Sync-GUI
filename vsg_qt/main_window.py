
from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore
from vsg.settings_io import CONFIG, load_settings
from vsg_qt.appearance import apply_appearance
from vsg_qt.options_dialog import OptionsDialog

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self._app = app
        self.setWindowTitle("Video/Audio Sync & Merge — Qt")
        self.resize(1200, 720)

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        # Options row
        row_opts = QtWidgets.QHBoxLayout()
        btn_opts = QtWidgets.QPushButton("Options…")
        btn_opts.clicked.connect(self.open_options)
        row_opts.addWidget(btn_opts)
        row_opts.addStretch(1)
        v.addLayout(row_opts)

        # Inputs
        self.ref_edit, btn_r = self._path_row(v, "Reference")
        self.sec_edit, btn_s = self._path_row(v, "Secondary")
        self.ter_edit, btn_t = self._path_row(v, "Tertiary")

        v.addSpacing(6)

        # Actions row (no Workflow/Mode selectors here — moved to Options)
        actions = QtWidgets.QHBoxLayout()
        self.btn_analyze = QtWidgets.QPushButton("Analyze Only")
        self.btn_merge = QtWidgets.QPushButton("Analyze  Merge")
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.status_lbl = QtWidgets.QLabel("OK")

        self.btn_analyze.clicked.connect(self.analyze_only)
        self.btn_merge.clicked.connect(self.analyze_merge)

        actions.addWidget(self.btn_analyze)
        actions.addWidget(self.btn_merge)
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.status_lbl)
        v.addLayout(actions)

        v.addWidget(QtWidgets.QLabel("Log"))
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(max(1000, CONFIG.get("log_tail_lines", 0) or 10000))
        v.addWidget(self.log, 1)

        apply_appearance(self._app, self)

        # F9 opens preferences
        QtWidgets.QShortcut(QtGui.QKeySequence("F9"), self, activated=self.open_options)

        self._log("Settings initialized/updated with defaults.")
        self._log("Settings applied to UI.")

    def _path_row(self, vbox, label: str):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("Choose a file…")
        btn = QtWidgets.QPushButton("…")
        def pick():
            f, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Choose {label} file")
            if f:
                edit.setText(f)
        btn.clicked.connect(pick)
        row.addWidget(edit, 1); row.addWidget(btn)
        vbox.addLayout(row)
        return edit, btn

    # --- actions
    def _log(self, msg: str):
        self.log.appendPlainText(msg)
        if CONFIG.get("log_autoscroll", True):
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def open_options(self):
        dlg = OptionsDialog(self._app, self, self)
        dlg.exec()

    def analyze_only(self):
        # Wire to your real pipeline
        self._log("Analyze Only pressed. (Hook up to your pipeline)")

    def analyze_merge(self):
        self._log("Analyze+Merge pressed. (Hook up to your pipeline)")
