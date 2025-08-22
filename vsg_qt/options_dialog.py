
from __future__ import annotations
from PySide6 import QtWidgets, QtCore
from vsg.settings_io import CONFIG, load_settings, save_settings
from .appearance import apply_appearance

class OptionsDialog(QtWidgets.QDialog):
    def __init__(self, app, root, parent=None):
        super().__init__(parent)
        self._app = app
        self._root = root
        self.setWindowTitle("Preferences")
        self.resize(920, 540)

        self.tabs = QtWidgets.QTabWidget()
        btn_save = QtWidgets.QPushButton("Save")
        btn_reload = QtWidgets.QPushButton("Reload from disk")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_save.clicked.connect(self.on_save)
        btn_reload.clicked.connect(self.on_reload)
        btn_cancel.clicked.connect(self.reject)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.tabs)
        h = QtWidgets.QHBoxLayout()
        h.addStretch(1)
        h.addWidget(btn_reload)
        h.addSpacing(12)
        h.addWidget(btn_save)
        h.addWidget(btn_cancel)
        v.addLayout(h)

        self._build_storage_tab()
        self._build_analysis_tab()
        self._build_global_tab()
        self._build_logging_tab()
        self._build_appearance_tab()

    # --- helpers
    def _line(self) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.HLine)
        f.setFrameShadow(QtWidgets.QFrame.Sunken)
        return f

    def _row(self, *widgets):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w); lay.setContentsMargins(0,0,0,0)
        for x in widgets: lay.addWidget(x)
        lay.addStretch(1)
        return w

    def _label(self, text):
        l = QtWidgets.QLabel(text); l.setMinimumWidth(220)
        return l

    # --- tabs
    def _build_storage_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Storage")
        form = QtWidgets.QFormLayout(page)

        self.out_edit = QtWidgets.QLineEdit(CONFIG.get("output_folder",""))
        self.tmp_edit = QtWidgets.QLineEdit(CONFIG.get("temp_root",""))
        self.ffmpeg = QtWidgets.QLineEdit(CONFIG.get("ffmpeg_path",""))
        self.ffprobe = QtWidgets.QLineEdit(CONFIG.get("ffprobe_path",""))
        self.mkvmerge = QtWidgets.QLineEdit(CONFIG.get("mkvmerge_path",""))
        self.mkvextract = QtWidgets.QLineEdit(CONFIG.get("mkvextract_path",""))
        self.videodiff = QtWidgets.QLineEdit(CONFIG.get("videodiff_path",""))

        form.addRow("Output folder", self._row(self.out_edit, self._browse_btn(self.out_edit, dir_only=True)))
        form.addRow("Temp folder",   self._row(self.tmp_edit, self._browse_btn(self.tmp_edit, dir_only=True)))
        form.addRow(self._line())
        form.addRow("FFmpeg path",   self._row(self.ffmpeg, self._browse_btn(self.ffmpeg)))
        form.addRow("FFprobe path",  self._row(self.ffprobe, self._browse_btn(self.ffprobe)))
        form.addRow("mkvmerge path", self._row(self.mkvmerge, self._browse_btn(self.mkvmerge)))
        form.addRow("mkvextract path", self._row(self.mkvextract, self._browse_btn(self.mkvextract)))
        form.addRow("VideoDiff path", self._row(self.videodiff, self._browse_btn(self.videodiff)))

    def _browse_btn(self, target: QtWidgets.QLineEdit, dir_only=False):
        b = QtWidgets.QPushButton("…")
        def pick():
            if dir_only:
                d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
                if d: target.setText(d)
            else:
                f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose file")
                if f: target.setText(f)
        b.clicked.connect(pick); return b

    def _build_analysis_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Analysis")
        form = QtWidgets.QFormLayout(page)

        self.workflow = QtWidgets.QComboBox(); self.workflow.addItems(["Analyze Only","Analyze & Merge"])
        self.workflow.setCurrentText(CONFIG.get("workflow","Analyze & Merge"))

        self.mode = QtWidgets.QComboBox(); self.mode.addItems(["Audio Correlation","VideoDiff"])
        self.mode.setCurrentText(CONFIG.get("analysis_mode","Audio Correlation"))

        self.chunks = QtWidgets.QSpinBox(); self.chunks.setRange(1, 999); self.chunks.setValue(int(CONFIG.get("scan_chunk_count",10)))
        self.chunk_dur = QtWidgets.QSpinBox(); self.chunk_dur.setRange(1, 999); self.chunk_dur.setValue(int(CONFIG.get("scan_chunk_duration",15)))
        self.min_match = QtWidgets.QDoubleSpinBox(); self.min_match.setRange(0,100); self.min_match.setDecimals(3); self.min_match.setSingleStep(0.5)
        self.min_match.setValue(float(CONFIG.get("min_match_pct",5.0)))

        self.vd_min = QtWidgets.QDoubleSpinBox(); self.vd_min.setRange(0, 10_000); self.vd_min.setDecimals(3); self.vd_min.setValue(float(CONFIG.get("videodiff_error_min",0.0)))
        self.vd_max = QtWidgets.QDoubleSpinBox(); self.vd_max.setRange(0, 10_000); self.vd_max.setDecimals(3); self.vd_max.setValue(float(CONFIG.get("videodiff_error_max",100.0)))

        form.addRow("Workflow", self.workflow)
        form.addRow("Mode", self.mode)
        form.addRow("Scan chunk count", self.chunks)
        form.addRow("Chunk duration (s)", self.chunk_dur)
        form.addRow("Minimum match %", self.min_match)
        form.addRow(self._line())
        form.addRow("Min error (VideoDiff)", self.vd_min)
        form.addRow("Max error (VideoDiff)", self.vd_max)

    def _build_global_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Global")
        v = QtWidgets.QVBoxLayout(page)

        self.prefer_sec = QtWidgets.QCheckBox("Prefer JPN audio on Secondary")
        self.prefer_ter = QtWidgets.QCheckBox("Prefer JPN audio on Tertiary")
        self.rm_norm   = QtWidgets.QCheckBox("Remove dialog normalization (AC-3/eAC-3)")
        self.first_sub = QtWidgets.QCheckBox("Make first subtitle in final order the DEFAULT")

        self.prefer_sec.setChecked(bool(CONFIG.get("match_jpn_secondary", True)))
        self.prefer_ter.setChecked(bool(CONFIG.get("match_jpn_tertiary", True)))
        self.rm_norm.setChecked(bool(CONFIG.get("apply_dialog_norm_gain", False)))
        self.first_sub.setChecked(bool(CONFIG.get("first_sub_default", True)))

        v.addWidget(self.prefer_sec); v.addWidget(self.prefer_ter); v.addWidget(self.rm_norm); v.addWidget(self.first_sub)
        v.addWidget(self._line())

        self.snap = QtWidgets.QCheckBox("Snap chapters to keyframes")
        self.snap.setChecked(bool(CONFIG.get("snap_chapters", False)))
        self.snap_mode = QtWidgets.QComboBox(); self.snap_mode.addItems(["previous","next","nearest","none"])
        self.snap_mode.setCurrentText(CONFIG.get("snap_mode","previous"))
        self.snap_thresh = QtWidgets.QSpinBox(); self.snap_thresh.setRange(0, 10_000); self.snap_thresh.setValue(int(CONFIG.get("snap_threshold_ms",250)))
        self.snap_starts = QtWidgets.QCheckBox("Starts only"); self.snap_starts.setChecked(bool(CONFIG.get("snap_starts_only", True)))

        form2 = QtWidgets.QFormLayout()
        form2.addRow(self.snap)
        form2.addRow("Snap mode", self.snap_mode)
        form2.addRow("Max snap distance (ms)", self.snap_thresh)
        form2.addRow(self.snap_starts)
        v.addLayout(form2); v.addStretch(1)

    def _build_logging_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Logging")
        form = QtWidgets.QFormLayout(page)

        self.compact = QtWidgets.QCheckBox("Compact controls"); self.compact.setChecked(bool(CONFIG.get("log_compact", True)))
        self.tail = QtWidgets.QSpinBox(); self.tail.setRange(0, 10_000); self.tail.setValue(int(CONFIG.get("log_tail_lines",0)))
        self.err_tail = QtWidgets.QSpinBox(); self.err_tail.setRange(0,10_000); self.err_tail.setValue(int(CONFIG.get("log_error_tail",20)))
        self.prog_step = QtWidgets.QSpinBox(); self.prog_step.setRange(1,10000); self.prog_step.setValue(int(CONFIG.get("log_progress_step",20)))
        self.pretty = QtWidgets.QCheckBox("Show options (pretty)"); self.pretty.setChecked(bool(CONFIG.get("log_show_options_pretty", False)))
        self.json = QtWidgets.QCheckBox("Show options (json)"); self.json.setChecked(bool(CONFIG.get("log_show_options_json", False)))
        self.auto = QtWidgets.QCheckBox("Autoscroll"); self.auto.setChecked(bool(CONFIG.get("log_autoscroll", True)))

        form.addRow(self.compact)
        form.addRow("Tail lines", self.tail)
        form.addRow("Error tail", self.err_tail)
        form.addRow("Progress step", self.prog_step)
        form.addRow(self.pretty)
        form.addRow(self.json)
        form.addRow(self.auto)

    def _build_appearance_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Appearance")
        form = QtWidgets.QFormLayout(page)

        self.font_family = QtWidgets.QLineEdit(CONFIG.get("ui_font_family",""))
        self.font_size = QtWidgets.QSpinBox(); self.font_size.setRange(6, 72); self.font_size.setValue(int(CONFIG.get("ui_font_size_pt", 10)))
        self.row_spacing = QtWidgets.QSpinBox(); self.row_spacing.setRange(0, 40); self.row_spacing.setValue(int(CONFIG.get("row_spacing_px", 8)))
        self.input_height = QtWidgets.QSpinBox(); self.input_height.setRange(18, 80); self.input_height.setValue(int(CONFIG.get("input_height_px", 32)))

        form.addRow("Font family (leave blank for default)", self.font_family)
        form.addRow("Font size (pt)", self.font_size)
        form.addRow("Row spacing (px)", self.row_spacing)
        form.addRow("Input height (px)", self.input_height)

    # --- actions
    def on_reload(self):
        load_settings()
        self.close()             # keep it simple: close & reopen to rebind
        dlg = OptionsDialog(self._app, self._root, self.parent())
        dlg.exec()

    def on_save(self):
        # sync UI -> CONFIG
        CONFIG["output_folder"] = self.out_edit.text().strip()
        CONFIG["temp_root"] = self.tmp_edit.text().strip()
        CONFIG["ffmpeg_path"] = self.ffmpeg.text().strip()
        CONFIG["ffprobe_path"] = self.ffprobe.text().strip()
        CONFIG["mkvmerge_path"] = self.mkvmerge.text().strip()
        CONFIG["mkvextract_path"] = self.mkvextract.text().strip()
        CONFIG["videodiff_path"] = self.videodiff.text().strip()

        CONFIG["workflow"] = self.workflow.currentText()
        CONFIG["analysis_mode"] = self.mode.currentText()
        CONFIG["scan_chunk_count"] = int(self.chunks.value())
        CONFIG["scan_chunk_duration"] = int(self.chunk_dur.value())
        CONFIG["min_match_pct"] = float(self.min_match.value())
        CONFIG["videodiff_error_min"] = float(self.vd_min.value())
        CONFIG["videodiff_error_max"] = float(self.vd_max.value())

        CONFIG["match_jpn_secondary"] = bool(self.prefer_sec.isChecked())
        CONFIG["match_jpn_tertiary"] = bool(self.prefer_ter.isChecked())
        CONFIG["apply_dialog_norm_gain"] = bool(self.rm_norm.isChecked())
        CONFIG["first_sub_default"] = bool(self.first_sub.isChecked())

        CONFIG["snap_chapters"] = bool(self.snap.isChecked())
        CONFIG["snap_mode"] = self.snap_mode.currentText()
        CONFIG["snap_threshold_ms"] = int(self.snap_thresh.value())
        CONFIG["snap_starts_only"] = bool(self.snap_starts.isChecked())

        CONFIG["log_compact"] = bool(self.compact.isChecked())
        CONFIG["log_tail_lines"] = int(self.tail.value())
        CONFIG["log_error_tail"] = int(self.err_tail.value())
        CONFIG["log_progress_step"] = int(self.prog_step.value())
        CONFIG["log_show_options_pretty"] = bool(self.pretty.isChecked())
        CONFIG["log_show_options_json"] = bool(self.json.isChecked())
        CONFIG["log_autoscroll"] = bool(self.auto.isChecked())

        CONFIG["ui_font_family"] = self.font_family.text().strip()
        CONFIG["ui_font_size_pt"] = int(self.font_size.value())
        CONFIG["row_spacing_px"] = int(self.row_spacing.value())
        CONFIG["input_height_px"] = int(self.input_height.value())

        save_settings(CONFIG)
        apply_appearance(self._app, self._root, CONFIG)
        self.accept()
