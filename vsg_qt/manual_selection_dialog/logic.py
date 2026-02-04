# vsg_qt/manual_selection_dialog/logic.py
from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.models.context_types import ManualLayoutItem

if TYPE_CHECKING:
    from vsg_qt.track_widget.ui import TrackWidget

    from .ui import ManualSelectionDialog


class ManualLogic:
    """A controller instance for the ManualSelectionDialog."""

    def __init__(self, view: ManualSelectionDialog):
        self.v = view

    def is_blocked_video(self, track_data: dict) -> bool:
        """Video is only allowed from Source 1."""
        return (
            track_data.get("type") == "video" and track_data.get("source") != "Source 1"
        )

    def prepopulate_from_layout(self, layout: list[ManualLayoutItem]) -> None:
        """Populates the final list using a previously configured layout."""
        if not layout:
            return

        pools = {}
        counters = {}
        for src_key, track_list in self.v.track_info.items():
            for t in track_list:
                key = (src_key, t["type"], counters.get((src_key, t["type"]), 0))
                pools[key] = t
                counters[(src_key, t["type"])] = (
                    counters.get((src_key, t["type"]), 0) + 1
                )

        realized_layout = []
        counters.clear()
        for prev_item in layout:
            src, ttype = prev_item.get("source"), prev_item.get("type")

            # CRITICAL FIX: Generated tracks don't exist in source files
            # They're created from other tracks, so preserve them from layout without pool matching
            if prev_item.get("is_generated"):
                # Generated tracks use their settings from the saved layout
                # Just verify the source track they reference actually exists
                source_track_id = prev_item.get("source_track_id")
                if source_track_id is not None:
                    # Find the source track in track_info to validate it exists
                    source_exists = any(
                        t.get("id") == source_track_id
                        for t in self.v.track_info.get(src, [])
                    )
                    if source_exists:
                        realized_layout.append(prev_item.copy())
                    # else: Skip this generated track - its source doesn't exist
                continue

            idx = counters.get((src, ttype), 0)
            counters[(src, ttype)] = idx + 1

            match = pools.get((src, ttype, idx))
            if match:
                new_item = match.copy()
                new_item.update(prev_item)
                realized_layout.append(new_item)

        for track_data in realized_layout:
            # CRITICAL FIX: Filter out video tracks from secondary sources
            if self.is_blocked_video(track_data):
                continue
            self.v.final_list.add_track_widget(track_data, preset=True)

    def get_final_layout_and_attachments(self) -> tuple[list[ManualLayoutItem], list[str]]:
        """Builds the layout from widgets and gets selected attachment sources."""
        widgets = []
        for i in range(self.v.final_list.count()):
            widgets.append(self.v.final_list.itemWidget(self.v.final_list.item(i)))

        self.normalize_single_default_for_type(
            widgets, "audio", force_default_if_none=True
        )
        self.normalize_single_default_for_type(
            widgets, "subtitles", force_default_if_none=False
        )
        self.normalize_forced_subtitles(widgets)

        layout = self.build_layout_from_widgets(widgets)
        attachment_sources = [
            key for key, cb in self.v.attachment_checkboxes.items() if cb.isChecked()
        ]

        return layout, attachment_sources

    def build_layout_from_widgets(self, widgets: list[TrackWidget]) -> list[ManualLayoutItem]:
        """Creates the final layout data structure from the UI widgets."""
        out = []
        for w in widgets:
            td = dict(w.track_data)
            cfg = w.logic.get_config()
            td.update(cfg)
            out.append(td)
        return out

    def normalize_single_default_for_type(
        self,
        widgets: list[TrackWidget],
        ttype: str,
        force_default_if_none: bool,
        prefer_widget=None,
    ) -> None:
        """Ensures only one 'Default' flag is set per track type."""
        first_default = None

        for w in widgets:
            if w.track_type == ttype:
                if prefer_widget and w is prefer_widget:
                    w.cb_default.setChecked(True)
                    first_default = w
                    break
                if w.cb_default.isChecked():
                    first_default = w
                    break

        if not first_default and force_default_if_none:
            for w in widgets:
                if w.track_type == ttype:
                    w.cb_default.setChecked(True)
                    first_default = w
                    break

        for w in widgets:
            if w.track_type == ttype and w is not first_default:
                w.cb_default.setChecked(False)
            w.logic.refresh_badges()

    def normalize_forced_subtitles(self, widgets: list[TrackWidget]) -> None:
        """Ensures at most one 'Forced' flag is set for subtitles."""
        first_forced = None
        for w in widgets:
            if w.track_type == "subtitles":
                if w.cb_forced.isChecked():
                    if not first_forced:
                        first_forced = w
                    else:
                        w.cb_forced.setChecked(False)
        for w in widgets:
            if w.track_type == "subtitles":
                w.logic.refresh_badges()
