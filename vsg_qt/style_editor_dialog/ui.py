# vsg_qt/style_editor_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPixmap, QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QWidget, QTableWidget, QAbstractItemView, QGroupBox, QFormLayout,
    QComboBox, QLineEdit, QDoubleSpinBox, QCheckBox, QScrollArea, QSpinBox
)
from .logic import StyleEditorLogic
from .player_thread import PlayerThread
from .video_widget import VideoWidget

class StyleEditorDialog(QDialog):
    def __init__(self, video_path: str, subtitle_path: str, fonts_dir: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Subtitle Style Editor")
        self.setMinimumSize(1400, 800)
        self.duration_seconds = 0.0
        self.is_seeking = False
        self.style_widgets: Dict[str, QWidget] = {}
        self._build_ui()
        self._logic = StyleEditorLogic(self, subtitle_path)
        self._logic.populate_initial_state()
        self.player_thread = PlayerThread(video_path, subtitle_path, self.video_frame.winId(), fonts_dir=fonts_dir, parent=self)
        self._connect_signals()
        self.player_thread.start()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        left_pane = QVBoxLayout()
        self.video_frame = VideoWidget()
        left_pane.addWidget(self.video_frame, 1)
        playback_controls = QHBoxLayout()
        self.play_pause_btn = QPushButton("Pause")
        self.seek_slider = QSlider(Qt.Horizontal)
        playback_controls.addWidget(self.play_pause_btn)
        playback_controls.addWidget(self.seek_slider)
        left_pane.addLayout(playback_controls)
        self.events_table = QTableWidget()
        self.events_table.setColumnCount(5)
        self.events_table.setHorizontalHeaderLabels(["#", "Start", "End", "Style", "Text"])
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        left_pane.addWidget(self.events_table)
        right_pane_group = QGroupBox("Style Controls")
        right_pane_layout = QVBoxLayout(right_pane_group)

        # Top row with Style Selector and Reset button
        top_row = QHBoxLayout()
        self.style_selector = QComboBox()
        self.reset_style_btn = QPushButton("Reset Style")
        top_row.addWidget(self.style_selector, 1)
        top_row.addWidget(self.reset_style_btn)
        right_pane_layout.addLayout(top_row)

        # Second row with Strip Tags and new Resample button
        actions_row = QHBoxLayout()
        self.strip_tags_btn = QPushButton("Strip Tags from Line(s)")
        self.resample_btn = QPushButton("Resample...") # NEW: Add Resample button
        actions_row.addWidget(self.strip_tags_btn)
        actions_row.addWidget(self.resample_btn)
        actions_row.addStretch()
        right_pane_layout.addLayout(actions_row)

        self.tag_warning_label = QLabel()
        self.tag_warning_label.setStyleSheet("color: #E0A800; font-weight: bold;")
        self.tag_warning_label.setVisible(False)
        self.tag_warning_label.setWordWrap(True)
        right_pane_layout.addWidget(self.tag_warning_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        # ... (all style_widgets are created here as before)
        self.style_widgets['fontname'] = QLineEdit()
        self.style_widgets['fontsize'] = QDoubleSpinBox(); self.style_widgets['fontsize'].setRange(1, 500)
        self.style_widgets['primarycolor'] = QPushButton("Pick...")
        self.style_widgets['secondarycolor'] = QPushButton("Pick...")
        self.style_widgets['outlinecolor'] = QPushButton("Pick...")
        self.style_widgets['backcolor'] = QPushButton("Pick...")
        self.style_widgets['bold'] = QCheckBox()
        self.style_widgets['italic'] = QCheckBox()
        self.style_widgets['underline'] = QCheckBox()
        self.style_widgets['strikeout'] = QCheckBox()
        self.style_widgets['outline'] = QDoubleSpinBox(); self.style_widgets['outline'].setRange(0, 20)
        self.style_widgets['shadow'] = QDoubleSpinBox(); self.style_widgets['shadow'].setRange(0, 20)
        self.style_widgets['marginl'] = QSpinBox(); self.style_widgets['marginl'].setRange(0, 9999)
        self.style_widgets['marginr'] = QSpinBox(); self.style_widgets['marginr'].setRange(0, 9999)
        self.style_widgets['marginv'] = QSpinBox(); self.style_widgets['marginv'].setRange(0, 9999)
        form_layout.addRow("Font Name:", self.style_widgets['fontname'])
        form_layout.addRow("Font Size:", self.style_widgets['fontsize'])
        form_layout.addRow("Primary Color:", self.style_widgets['primarycolor'])
        form_layout.addRow("Secondary Color:", self.style_widgets['secondarycolor'])
        form_layout.addRow("Outline Color:", self.style_widgets['outlinecolor'])
        form_layout.addRow("Shadow Color:", self.style_widgets['backcolor'])
        form_layout.addRow("Bold:", self.style_widgets['bold'])
        form_layout.addRow("Italic:", self.style_widgets['italic'])
        form_layout.addRow("Underline:", self.style_widgets['underline'])
        form_layout.addRow("Strikeout:", self.style_widgets['strikeout'])
        form_layout.addRow("Outline:", self.style_widgets['outline'])
        form_layout.addRow("Shadow:", self.style_widgets['shadow'])
        form_layout.addRow("Margin Left:", self.style_widgets['marginl'])
        form_layout.addRow("Margin Right:", self.style_widgets['marginr'])
        form_layout.addRow("Margin Vertical:", self.style_widgets['marginv'])
        scroll_area.setWidget(form_widget)
        right_pane_layout.addWidget(scroll_area)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        right_pane_layout.addWidget(button_box)
        main_layout.addLayout(left_pane, 2)
        main_layout.addWidget(right_pane_group, 1)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    def _connect_signals(self):
        # ... (player and playback signals are the same)
        self.player_thread.new_frame.connect(self.update_video_frame)
        self.player_thread.duration_changed.connect(self.setup_seek_slider)
        self.player_thread.time_changed.connect(self.update_slider_position)
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        self.seek_slider.sliderPressed.connect(self.handle_slider_press)
        self.seek_slider.sliderReleased.connect(self.handle_slider_release)
        self.events_table.itemSelectionChanged.connect(self.handle_event_selection_changed)

        self.reset_style_btn.clicked.connect(self._logic.reset_current_style)
        self.style_selector.currentTextChanged.connect(self._logic.on_style_selected)
        self.strip_tags_btn.clicked.connect(self._logic.strip_tags_from_selected)

        # NEW: Connect the resample button
        self.resample_btn.clicked.connect(self._logic.open_resample_dialog)

        # ... (style widget connections are the same)
        for widget in self.style_widgets.values():
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._logic.update_current_style)
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                widget.editingFinished.connect(self._logic.update_current_style)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._logic.update_current_style)
        self.style_widgets['primarycolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['primarycolor'], "primarycolor"))
        self.style_widgets['secondarycolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['secondarycolor'], "secondarycolor"))
        self.style_widgets['outlinecolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['outlinecolor'], "outlinecolor"))
        self.style_widgets['backcolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['backcolor'], "backcolor"))

    # ... (rest of the file is unchanged)
    def update_video_frame(self, image: QImage, timestamp: float):
        pixmap = QPixmap.fromImage(image)
        self.video_frame.set_pixmap(pixmap)
    def setup_seek_slider(self, duration: float):
        self.duration_seconds = duration; self.seek_slider.setRange(0, int(self.duration_seconds * 1000))
    def update_slider_position(self, time_ms: int):
        if not self.is_seeking: self.seek_slider.setValue(time_ms)
    def toggle_playback(self): self.player_thread.toggle_pause()
    def handle_slider_press(self): self.is_seeking = True
    def handle_slider_release(self):
        self.is_seeking = False
        self._logic.update_current_style()
        self.player_thread.seek(self.seek_slider.value())
    def handle_event_selection_changed(self):
        selected_items = self.events_table.selectedItems()
        if not selected_items: return
        self._logic.update_current_style()
        self._logic.on_event_selected()
        row = selected_items[0].row()
        start_time_ms_str = self.events_table.item(row, 1).text()
        try: self.player_thread.seek(int(start_time_ms_str))
        except (ValueError, TypeError): pass
    def closeEvent(self, event): self.player_thread.stop(); super().closeEvent(event)
