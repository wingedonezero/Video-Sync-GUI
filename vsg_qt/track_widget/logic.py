# vsg_qt/track_widget/logic.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QWidgetAction
from .helpers import compose_label_text, build_summary_text

class TrackWidgetLogic:
    """
    Attaches behavior to the TrackWidget view.
    The view is a TrackWidget (from ui.py) exposing the controls as attributes.
    """
    def __init__(self, view):
        self.v = view
        self._menu = None
        self._in_apply = False  # reentrancy guard
        self._install_menu()
        self.refresh_badges()
        self.refresh_summary()

    # ----- Menu -----
    def _install_menu(self):
        if self._menu is not None:
            return

        v = self.v
        self._menu = QMenu(v)
        container = v._build_menu_form()
        act = QWidgetAction(self._menu)
        act.setDefaultWidget(container)
        self._menu.addAction(act)
        v.btn.setMenu(self._menu)

    def apply_state_from_menu(self):
        if self._in_apply:
            return
        self._in_apply = True
        try:
            self.refresh_badges()
            self.refresh_summary()
        finally:
            self._in_apply = False

    # ----- UI refresh -----
    def refresh_badges(self):
        self.v.label.setText(compose_label_text(self.v))

    def refresh_summary(self):
        txt = build_summary_text(self.v)
        if txt:
            self.v.summary.setText(txt)
            self.v.summary.setVisible(True)
        else:
            self.v.summary.clear()
            self.v.summary.setVisible(False)

    # ----- Public helpers used by TrackWidget -----
    def get_config(self) -> dict:
        v = self.v
        config = {
            'is_default': v.cb_default.isChecked(),
            'is_forced_display': v.cb_forced.isChecked(),
            'apply_track_name': v.cb_name.isChecked(),
            'convert_to_ass': v.cb_convert.isChecked(),
            'rescale': v.cb_rescale.isChecked(),
            'size_multiplier': v.size_multiplier.value() if v.track_type == 'subtitles' else 1.0
        }

        if hasattr(v, 'sync_to_combo') and v.sync_to_combo.isVisible():
            config['sync_to'] = v.sync_to_combo.currentData()

        return config
