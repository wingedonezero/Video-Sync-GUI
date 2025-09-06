from __future__ import annotations

def compose_label_text(w) -> str:
    """
    Build the row label with badges. `w` is the TrackWidget instance.
    """
    base = (
        f"[{w.source}] "
        f"[{w.track_type[0].upper()}-{w.track_data.get('id')}] "
        f"{w.codec_id} "
        f"({w.track_data.get('lang', 'und')})"
    )
    name_part = f" '{w.track_data.get('name')}'" if w.track_data.get('name') else ""

    badges = []
    if w.cb_default.isChecked():
        badges.append("⭐")
    if w.track_type == 'subtitles':
        if w.cb_forced.isChecked():
            badges.append("📌")
        if w.cb_rescale.isChecked():
            badges.append("📏")
        try:
            if abs(float(w.size_multiplier.value()) - 1.0) > 1e-6:
                badges.append("🔤")
        except Exception:
            pass

    badge_str = ("  " + " ".join(badges)) if badges else ""
    return base + name_part + badge_str


def build_summary_text(w) -> str:
    """
    Compose the grey inline summary line. `w` is the TrackWidget instance.
    """
    parts = []
    if w.cb_default.isChecked():
        parts.append("⭐ Default")
    if w.track_type == 'subtitles':
        if w.cb_forced.isChecked():
            parts.append("📌 Forced Display")
        if w.cb_rescale.isChecked():
            parts.append("📏 Rescale")
        try:
            if abs(float(w.size_multiplier.value()) - 1.0) > 1e-6:
                parts.append(f"{w.size_multiplier.value():.2f}x Size")
        except Exception:
            pass
        if w.cb_convert.isChecked():
            parts.append("Convert to ASS")
    if w.cb_name.isChecked():
        parts.append("Keep Name")

    return ("└  ⚙ Options: " + ", ".join(parts)) if parts else ""
