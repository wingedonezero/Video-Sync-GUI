# vsg_qt/style_editor_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPixmap, QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QWidget, QTableWidget, QAbstractItemView, QGroupBox, QFormLayout,
    QComboBox, QLineEdit, QDoubleSpinBox, QCheckBox, QScrollArea, QSpinBox,
    QMenu, QToolButton
)
from .logic import StyleEditorLogic
from .player_thread import PlayerThread
from .video_widget import VideoWidget

class StyleEditorDialog(QDialog):
    def __init__(self, video_path: str, subtitle_path: str, fonts_dir: str | None,
                 existing_font_replacements: Dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Subtitle Style Editor")
        self.setMinimumSize(1400, 800)
        self.duration_seconds = 0.0
        self.is_seeking = False
        self.style_widgets: Dict[str, QWidget] = {}
        self.fonts_dir = fonts_dir  # Store for font replacement copying
        self._build_ui()
        self._logic = StyleEditorLogic(self, subtitle_path, existing_font_replacements, fonts_dir)
        self._logic.populate_initial_state()
        # Use the preview path (temp file) for the player to avoid modifying original during preview
        preview_path = self._logic.engine.get_preview_path()
        self.player_thread = PlayerThread(video_path, preview_path, self.video_frame.winId(), fonts_dir=fonts_dir, parent=self)
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
        # Prevent auto-scroll horizontally when selecting long text rows
        self.events_table.setAutoScroll(False)
        left_pane.addWidget(self.events_table)
        right_pane_group = QGroupBox("Style Controls")
        right_pane_layout = QVBoxLayout(right_pane_group)

        top_row = QHBoxLayout()
        self.style_selector = QComboBox()
        self.reset_style_btn = QPushButton("Reset Style")
        top_row.addWidget(self.style_selector, 1)
        top_row.addWidget(self.reset_style_btn)
        right_pane_layout.addLayout(top_row)

        actions_row = QHBoxLayout()
        self.strip_tags_btn = QPushButton("Strip Tags from Line(s)")
        self.resample_btn = QPushButton("Resample...")
        self.font_manager_btn = QPushButton("Font Manager...")
        self.favorites_manager_btn = QPushButton("Color Favorites...")
        actions_row.addWidget(self.strip_tags_btn)
        actions_row.addWidget(self.resample_btn)
        actions_row.addWidget(self.font_manager_btn)
        actions_row.addWidget(self.favorites_manager_btn)
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
        self.style_widgets['fontname'] = QLineEdit()
        self.style_widgets['fontsize'] = QDoubleSpinBox(); self.style_widgets['fontsize'].setRange(1, 500)

        # Color buttons with favorite support
        self.style_widgets['primarycolor'] = QPushButton("Pick...")
        self.style_widgets['secondarycolor'] = QPushButton("Pick...")
        self.style_widgets['outlinecolor'] = QPushButton("Pick...")
        self.style_widgets['backcolor'] = QPushButton("Pick...")

        # Favorite buttons for each color (save to favorites)
        self.favorite_save_btns = {}
        self.favorite_load_btns = {}
        for color_key in ['primarycolor', 'secondarycolor', 'outlinecolor', 'backcolor']:
            # Save to favorites button (star)
            save_btn = QPushButton()
            save_btn.setFixedSize(28, 28)
            save_btn.setToolTip("Save color to favorites")
            save_btn.setText("\u2606")  # Unicode star outline
            save_btn.setStyleSheet("font-size: 14px;")
            self.favorite_save_btns[color_key] = save_btn

            # Load from favorites button (dropdown)
            load_btn = QToolButton()
            load_btn.setFixedSize(28, 28)
            load_btn.setToolTip("Load color from favorites")
            load_btn.setText("\u25BC")  # Unicode down triangle
            load_btn.setPopupMode(QToolButton.InstantPopup)
            self.favorite_load_btns[color_key] = load_btn
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

        # Color rows with favorite buttons
        for color_key, label in [
            ('primarycolor', "Primary Color:"),
            ('secondarycolor', "Secondary Color:"),
            ('outlinecolor', "Outline Color:"),
            ('backcolor', "Shadow Color:")
        ]:
            color_row = QHBoxLayout()
            color_row.addWidget(self.style_widgets[color_key], 1)
            color_row.addWidget(self.favorite_save_btns[color_key])
            color_row.addWidget(self.favorite_load_btns[color_key])
            form_layout.addRow(label, color_row)
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

    def get_style_patch(self):
        """Public method to retrieve the generated patch."""
        return self._logic.generated_patch

    def get_font_replacements(self):
        """Public method to retrieve the font replacements."""
        return self._logic.get_font_replacements()

    def accept(self):
        """Save changes to original file and generate the patch before closing."""
        # Save any pending UI changes to the engine
        self._logic.update_current_style()
        # Save to the original file (not just temp)
        self._logic.engine.save_to_original()
        # Generate the patch for external use
        self._logic.generate_patch()
        super().accept()

    def _connect_signals(self):
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
        self.resample_btn.clicked.connect(self._logic.open_resample_dialog)
        self.font_manager_btn.clicked.connect(self._logic.open_font_manager)
        self.favorites_manager_btn.clicked.connect(self._logic.open_favorites_manager)

        for widget in self.style_widgets.values():
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._logic.update_current_style)
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                # Use valueChanged with lambda to trigger on arrow clicks immediately
                widget.valueChanged.connect(lambda _: self._logic.update_current_style())
            elif isinstance(widget, QCheckBox):
                # Use lambda to discard the state argument
                widget.stateChanged.connect(lambda _: self._logic.update_current_style())
        self.style_widgets['primarycolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['primarycolor'], "primarycolor"))
        self.style_widgets['secondarycolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['secondarycolor'], "secondarycolor"))
        self.style_widgets['outlinecolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['outlinecolor'], "outlinecolor"))
        self.style_widgets['backcolor'].clicked.connect(lambda: self._logic.pick_color(self.style_widgets['backcolor'], "backcolor"))

        # Favorite color buttons
        for color_key in ['primarycolor', 'secondarycolor', 'outlinecolor', 'backcolor']:
            self.favorite_save_btns[color_key].clicked.connect(
                lambda checked, k=color_key: self._logic.save_color_to_favorites(self.style_widgets[k], k)
            )
            # The load buttons use menus that are populated dynamically
            self.favorite_load_btns[color_key].clicked.connect(
                lambda checked, k=color_key: self._logic.show_favorites_menu(self.favorite_load_btns[k], self.style_widgets[k], k)
            )

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
        self.player_thread.seek(self.seek_slider.value())
    def handle_event_selection_changed(self):
        selected_items = self.events_table.selectedItems()
        if not selected_items: return
        self._logic.on_event_selected()
        row = selected_items[0].row()
        start_time_ms_str = self.events_table.item(row, 1).text()
        try: self.player_thread.seek(int(start_time_ms_str))
        except (ValueError, TypeError): pass
    def closeEvent(self, event):
        if hasattr(self, 'player_thread') and self.player_thread:
            self.player_thread.stop()
        # Note: We don't cleanup temp files here - they're cleaned at job start/end
        # This allows debugging and keeps all temp files in one place
        super().closeEvent(event)
