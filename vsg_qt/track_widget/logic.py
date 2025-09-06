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

        # Container widget holding the options (we reuse the hidden controls directly)
        # This ensures state is single-sourced in the hidden controls.
        container = v._build_menu_form()  # returns QWidget with controls laid out
        act = QWidgetAction(self._menu)
        act.setDefaultWidget(container)
        self._menu.addAction(act)

        # Sync on show (no-op but kept for symmetry/extensibility)
        self._menu.aboutToShow.connect(self.sync_state_to_menu)

        # The controls in the menu are the SAME widgets as the hidden state.
        # Their signals are already connected in TrackWidget.ui to call
        # self.apply_state_from_menu() on change.
        v.btn.setMenu(self._menu)

    def sync_state_to_menu(self):
        """
        Copy current hidden state -> visible menu controls (they are the same widgets).
        Nothing to do since we show the same widgets; kept for symmetry/extensibility.
        """
        # No-op.
        pass

    def apply_state_from_menu(self):
        """
        Menu controls and hidden state are the same widgets now, so there is
        nothing to copy. Just refresh UI; DO NOT emit toggled here or we will
        recurse via our own signal connections.
        """
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
        self.v.label.setText(compute_label(self.v))

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
        return {
            'is_default': v.cb_default.isChecked(),
            'is_forced_display': v.cb_forced.isChecked(),
            'apply_track_name': v.cb_name.isChecked(),
            'convert_to_ass': v.cb_convert.isChecked(),
            'rescale': v.cb_rescale.isChecked(),
            'size_multiplier': v.size_multiplier.value() if v.track_type == 'subtitles' else 1.0
        }


# Small wrapper to keep helpers import-local for logic
def compute_label(v) -> str:
    return compose_label_text(v)
