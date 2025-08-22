
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
        self.resize(920, 560)

        self.tabs = QtWidgets.QTabWidget()
        btn_save = QtWidgets.QPushButton("Save")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_reload = QtWidgets.QPushButton("Reload")

        btn_save.clicked.connect(self._on_save)
        btn_cancel.clicked.connect(self.reject)
        btn_reload.clicked.connect(self._on_reload)

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
        self._build_matching_tab()
        self._build_chapters_tab()
        self._build_logging_tab()
        self._build_appearance_tab()

    # ---- Tabs ----

    def _build_storage_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Storage & Tools")
        form = QtWidgets.QFormLayout(page)

        self.output = QtWidgets.QLineEdit(CONFIG.get("output_folder",""))
        self.temp = QtWidgets.QLineEdit(CONFIG.get("temp_root",""))

        self.ffmpeg = QtWidgets.QLineEdit(CONFIG.get("ffmpeg_path",""))
        self.ffprobe = QtWidgets.QLineEdit(CONFIG.get("ffprobe_path",""))
        self.mkvmerge = QtWidgets.QLineEdit(CONFIG.get("mkvmerge_path",""))
        self.mkvextract = QtWidgets.QLineEdit(CONFIG.get("mkvextract_path",""))
        self.videodiff = QtWidgets.QLineEdit(CONFIG.get("videodiff_path",""))

        def row(label, w, pick_dirs=False):
            hb = QtWidgets.QHBoxLayout()
            hb.addWidget(w, 1)
            btn = QtWidgets.QPushButton("…")
            def choose():
                if pick_dirs:
                    d = QtWidgets.QFileDialog.getExistingDirectory(self, f"Choose {label}")
                    if d: w.setText(d)
                else:
                    f, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Choose {label}")
                    if f: w.setText(f)
            btn.clicked.connect(choose)
            hb.addWidget(btn)
            form.addRow(label, hb)

        row("Output folder", self.output, pick_dirs=True)
        row("Temp work", self.temp, pick_dirs=True)
        row("ffmpeg", self.ffmpeg, pick_dirs=False)
        row("ffprobe", self.ffprobe, pick_dirs=False)
        row("mkvmerge", self.mkvmerge, pick_dirs=False)
        row("mkvextract", self.mkvextract, pick_dirs=False)
        row("videodiff", self.videodiff, pick_dirs=False)

    def _build_analysis_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Workflow & Analysis")
        form = QtWidgets.QFormLayout(page)

        self.workflow = QtWidgets.QComboBox()
        self.workflow.addItems(["Analyze Only", "Analyze & Merge"])
        self.workflow.setCurrentText(CONFIG.get("workflow","Analyze & Merge"))

        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["Audio Correlation", "VideoDiff"])
        self.mode.setCurrentText(CONFIG.get("analysis_mode", "Audio Correlation"))

        self.chunks = QtWidgets.QSpinBox(); self.chunks.setRange(1, 50); self.chunks.setValue(int(CONFIG.get("scan_chunk_count",5)))
        self.chunk_dur = QtWidgets.QSpinBox(); self.chunk_dur.setRange(2, 120); self.chunk_dur.setValue(int(CONFIG.get("scan_chunk_duration",10)))
        self.min_match = QtWidgets.QDoubleSpinBox(); self.min_match.setRange(0.0, 1.0); self.min_match.setSingleStep(0.01); self.min_match.setValue(float(CONFIG.get("min_match_pct",0.45)))
        self.vd_min = QtWidgets.QDoubleSpinBox(); self.vd_min.setRange(0.0, 1000.0); self.vd_min.setValue(float(CONFIG.get("videodiff_error_min",0.0)))
        self.vd_max = QtWidgets.QDoubleSpinBox(); self.vd_max.setRange(0.0, 1000.0); self.vd_max.setValue(float(CONFIG.get("videodiff_error_max",1.0)))

        form.addRow("Workflow", self.workflow)
        form.addRow("Analysis mode", self.mode)
        form.addRow("Scan chunks", self.chunks)
        form.addRow("Chunk duration (s)", self.chunk_dur)
        form.addRow("Min match % (0-1)", self.min_match)
        form.addRow("VideoDiff: min err", self.vd_min)
        form.addRow("VideoDiff: max err", self.vd_max)

    def _build_matching_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Matching & Preferences")
        v = QtWidgets.QVBoxLayout(page)

        self.prefer_sec = QtWidgets.QCheckBox("Prefer Japanese audio for Secondary")
        self.prefer_sec.setChecked(bool(CONFIG.get("match_jpn_secondary", False)))
        self.prefer_ter = QtWidgets.QCheckBox("Prefer Japanese audio for Tertiary")
        self.prefer_ter.setChecked(bool(CONFIG.get("match_jpn_tertiary", False)))

        self.rm_norm = QtWidgets.QCheckBox("Remove dialog normalization gain")
        self.rm_norm.setChecked(bool(CONFIG.get("apply_dialog_norm_gain", False)))

        self.first_sub = QtWidgets.QCheckBox("Set first subtitle track as default")
        self.first_sub.setChecked(bool(CONFIG.get("first_sub_default", False)))

        for w in (self.prefer_sec, self.prefer_ter, self.rm_norm, self.first_sub):
            v.addWidget(w)
        v.addStretch(1)

    def _build_chapters_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Chapters")
        form = QtWidgets.QFormLayout(page)

        self.rename = QtWidgets.QCheckBox("Rename chapters to match (anime) episode")
        self.rename.setChecked(bool(CONFIG.get("rename_chapters", False)))
        self.shift = QtWidgets.QCheckBox("Shift chapters with detected delay")
        self.shift.setChecked(bool(CONFIG.get("shift_chapters", False)))
        self.snap = QtWidgets.QCheckBox("Snap chapter start to keyframe")
        self.snap.setChecked(bool(CONFIG.get("snap_chapters", False)))
        self.snap_mode = QtWidgets.QComboBox(); self.snap_mode.addItems(["nearest", "back"]); self.snap_mode.setCurrentText(CONFIG.get("snap_mode","nearest"))
        self.snap_thresh = QtWidgets.QSpinBox(); self.snap_thresh.setRange(0, 5000); self.snap_thresh.setValue(int(CONFIG.get("snap_distance_ms",400)))

        form.addRow(self.rename)
        form.addRow(self.shift)
        form.addRow(self.snap)
        form.addRow("Snap mode", self.snap_mode)
        form.addRow("Max snap distance (ms)", self.snap_thresh)

    def _build_logging_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Logging")
        form = QtWidgets.QFormLayout(page)

        self.compact = QtWidgets.QCheckBox("Compact controls"); self.compact.setChecked(bool(CONFIG.get("log_compact", True)))
        self.tail = QtWidgets.QSpinBox(); self.tail.setRange(0, 100000); self.tail.setValue(int(CONFIG.get("log_tail_lines",2000)))
        self.err_tail = QtWidgets.QSpinBox(); self.err_tail.setRange(0, 100000); self.err_tail.setValue(int(CONFIG.get("log_error_tail",50)))
        self.prog_step = QtWidgets.QSpinBox(); self.prog_step.setRange(1, 1000); self.prog_step.setValue(int(CONFIG.get("log_progress_step",20)))
        self.pretty = QtWidgets.QCheckBox("Show pretty mkvmerge tokens"); self.pretty.setChecked(bool(CONFIG.get("log_show_options_pretty", False)))
        self.json = QtWidgets.QCheckBox("Show raw mkvmerge JSON"); self.json.setChecked(bool(CONFIG.get("log_show_options_json", False)))
        self.auto = QtWidgets.QCheckBox("Autoscroll log"); self.auto.setChecked(bool(CONFIG.get("log_autoscroll", True)))

        form.addRow(self.compact)
        form.addRow("Keep last N log lines", self.tail)
        form.addRow("Keep last N error lines", self.err_tail)
        form.addRow("Progress log step", self.prog_step)
        form.addRow(self.pretty)
        form.addRow(self.json)
        form.addRow(self.auto)

    def _build_appearance_tab(self):
        page = QtWidgets.QWidget(); self.tabs.addTab(page, "Appearance")
        form = QtWidgets.QFormLayout(page)

        self.font_family = QtWidgets.QLineEdit(CONFIG.get("ui_font_family",""))
        self.font_size = QtWidgets.QSpinBox(); self.font_size.setRange(6, 48); self.font_size.setValue(int(CONFIG.get("ui_font_size_pt",10)))
        self.row_spacing = QtWidgets.QSpinBox(); self.row_spacing.setRange(0, 40); self.row_spacing.setValue(int(CONFIG.get("row_spacing_px",8)))
        self.input_height = QtWidgets.QSpinBox(); self.input_height.setRange(16, 80); self.input_height.setValue(int(CONFIG.get("input_height_px",32)))

        form.addRow("Font family", self.font_family)
        form.addRow("Font size (pt)", self.font_size)
        form.addRow("Row spacing (px)", self.row_spacing)
        form.addRow("Input height (px)", self.input_height)

    # ---- Actions ----

    def _on_reload(self):
        load_settings()
        self.accept()

    def _on_save(self):
        CONFIG["output_folder"] = self.output.text().strip()
        CONFIG["temp_root"] = self.temp.text().strip()
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

        CONFIG["rename_chapters"] = bool(self.rename.isChecked())
        CONFIG["shift_chapters"] = bool(self.shift.isChecked())
        CONFIG["snap_chapters"] = bool(self.snap.isChecked())
        CONFIG["snap_mode"] = self.snap_mode.currentText()
        CONFIG["snap_distance_ms"] = int(self.snap_thresh.value())

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
