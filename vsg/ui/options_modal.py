from __future__ import annotations
import dearpygui.dearpygui as dpg
from vsg.settings_core import CONFIG, load_settings, save_settings, adopt_into_app, on_change, apply_and_notify

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _row_label(text: str, tip: str | None = None):
    dpg.add_text(text)
    if tip:
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(tip)

def _refresh_from_config():
    # Storage
    dpg.set_value('op_out', CONFIG.get('output_folder', ''))
    dpg.set_value('op_temp', CONFIG.get('temp_root', ''))
    dpg.set_value('op_ffmpeg', CONFIG.get('ffmpeg_path', ''))
    dpg.set_value('op_ffprobe', CONFIG.get('ffprobe_path', ''))
    dpg.set_value('op_mkvmerge', CONFIG.get('mkvmerge_path', ''))
    dpg.set_value('op_mkvextract', CONFIG.get('mkvextract_path', ''))
    dpg.set_value('op_vdiff', CONFIG.get('videodiff_path', ''))
    # Analysis
    dpg.set_value('workflow_combo_pref', CONFIG.get('workflow', 'Analyze & Merge'))
    dpg.set_value('analysis_mode_combo', CONFIG.get('analysis_mode', 'Audio Correlation'))
    dpg.set_value('op_scan_cnt', int(CONFIG.get('scan_chunk_count', 10)))
    dpg.set_value('op_scan_dur', int(CONFIG.get('scan_chunk_duration', 15)))
    dpg.set_value('op_min_match', float(CONFIG.get('min_match_pct', 5.0)))
    dpg.set_value('vd_err_min', float(CONFIG.get('videodiff_error_min', 0.0)))
    dpg.set_value('vd_err_max', float(CONFIG.get('videodiff_error_max', 100.0)))
    # Global
    dpg.set_value('op_jpn_sec', bool(CONFIG.get('match_jpn_secondary', True)))
    dpg.set_value('op_jpn_ter', bool(CONFIG.get('match_jpn_tertiary', True)))
    dpg.set_value('op_rm_dn', bool(CONFIG.get('apply_dialog_norm_gain', False)))
    dpg.set_value('op_snap', bool(CONFIG.get('snap_chapters', False)))
    dpg.set_value('op_snap_ms', int(CONFIG.get('snap_threshold_ms', 250)))
    dpg.set_value('op_snap_starts', bool(CONFIG.get('snap_starts_only', True)))
    # Appearance
    dpg.set_value('op_font_file', CONFIG.get('ui_font_path', ''))
    dpg.set_value('op_font_size', int(CONFIG.get('ui_font_size', 18)))
    dpg.set_value('op_line_h', int(CONFIG.get('input_line_height', 40)))
    dpg.set_value('op_row_gap', int(CONFIG.get('row_gap', 8)))
    dpg.set_value('op_compact', bool(CONFIG.get('ui_compact_controls', False)))
    # Toggle panes
    _toggle_mode_groups(CONFIG.get('analysis_mode', 'Audio Correlation'))

def _toggle_mode_groups(mode: str):
    dpg.configure_item('ac_group', show=(mode == 'Audio Correlation'))
    dpg.configure_item('vd_group', show=(mode == 'VideoDiff'))

def _do_live_load():
    conf = load_settings()
    if conf:
        adopt_into_app(conf)
    _refresh_from_config()

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

def build_options_modal():
    if dpg.does_item_exist('options_modal'):
        dpg.delete_item('options_modal')
    with dpg.window(modal=True, label='Preferences', tag='options_modal', width=900, height=600, pos=(120, 60)):
        with dpg.tab_bar():
            # Storage
            with dpg.tab(label='Storage'):
                _row_label('Output folder', 'Final muxed files are written here.')
                dpg.add_input_text(tag='op_out', width=600, callback=lambda s, a: on_change(s, a, 'output_folder'))
                _row_label('Temp folder', 'Temporary workspace and extracted assets.')
                dpg.add_input_text(tag='op_temp', width=600, callback=lambda s, a: on_change(s, a, 'temp_root'))
                dpg.add_separator()
                _row_label('Optional tool paths (leave blank to use PATH)', 'If empty, the app will use tools on your PATH.')
                _row_label('FFmpeg path');     dpg.add_input_text(tag='op_ffmpeg', width=600, callback=lambda s, a: on_change(s, a, 'ffmpeg_path'))
                _row_label('FFprobe path');    dpg.add_input_text(tag='op_ffprobe', width=600, callback=lambda s, a: on_change(s, a, 'ffprobe_path'))
                _row_label('mkvmerge path');   dpg.add_input_text(tag='op_mkvmerge', width=600, callback=lambda s, a: on_change(s, a, 'mkvmerge_path'))
                _row_label('mkvextract path'); dpg.add_input_text(tag='op_mkvextract', width=600, callback=lambda s, a: on_change(s, a, 'mkvextract_path'))
                _row_label('VideoDiff path');  dpg.add_input_text(tag='op_vdiff', width=600, callback=lambda s, a: on_change(s, a, 'videodiff_path'))

            # Analysis
            with dpg.tab(label='Analysis'):
                _row_label('Workflow', 'Analyze Only or Analyze & Merge.')
                dpg.add_combo(tag='workflow_combo_pref', items=['Analyze Only', 'Analyze & Merge'],
                              default_value=CONFIG.get('workflow', 'Analyze & Merge'),
                              callback=lambda s, a: on_change(s, a, 'workflow'), width=240)
                _row_label('Mode', 'Pick analysis engine: Audio Correlation or VideoDiff.')
                dpg.add_combo(tag='analysis_mode_combo', items=['Audio Correlation', 'VideoDiff'],
                              default_value=CONFIG.get('analysis_mode', 'Audio Correlation'),
                              callback=lambda s, a: (on_change(s, a, 'analysis_mode'), _toggle_mode_groups(a)), width=240)
                dpg.add_separator()
                with dpg.group(tag='ac_group', show=(CONFIG.get('analysis_mode', 'Audio Correlation') == 'Audio Correlation')):
                    _row_label('Scan chunk count', 'Number of evenly spaced samples across the timeline.')
                    dpg.add_input_int(tag='op_scan_cnt', step=1, min_value=1, max_value=500,
                                      default_value=int(CONFIG.get('scan_chunk_count', 10)),
                                      callback=lambda s, a: on_change(s, a, 'scan_chunk_count'), width=200)
                    _row_label('Chunk duration (s)', 'Seconds per sampled segment.')
                    dpg.add_input_int(tag='op_scan_dur', step=1, min_value=1, max_value=3600,
                                      default_value=int(CONFIG.get('scan_chunk_duration', 15)),
                                      callback=lambda s, a: on_change(s, a, 'scan_chunk_duration'), width=200)
                    _row_label('Minimum match %', 'Reject matches below this threshold.')
                    dpg.add_input_float(tag='op_min_match', step=0.5, min_value=0.0, max_value=100.0,
                                        default_value=float(CONFIG.get('min_match_pct', 5.0)),
                                        callback=lambda s, a: on_change(s, a, 'min_match_pct'), width=200)
                with dpg.group(tag='vd_group', show=(CONFIG.get('analysis_mode', 'Audio Correlation') == 'VideoDiff')):
                    _row_label('Min error (VideoDiff)', 'Stop if below this error.')
                    dpg.add_input_float(tag='vd_err_min', step=0.01, min_value=0.0, max_value=10000.0,
                                        default_value=float(CONFIG.get('videodiff_error_min', 0.0)),
                                        callback=lambda s, a: on_change(s, a, 'videodiff_error_min'), width=200)
                    _row_label('Max error (VideoDiff)', 'Stop if above this error.')
                    dpg.add_input_float(tag='vd_err_max', step=0.01, min_value=0.0, max_value=10000.0,
                                        default_value=float(CONFIG.get('videodiff_error_max', 100.0)),
                                        callback=lambda s, a: on_change(s, a, 'videodiff_error_max'), width=200)

            # Global
            with dpg.tab(label='Global'):
                _row_label('Audio/Chapters')
                dpg.add_checkbox(tag='op_jpn_sec', label='Prefer JPN audio on Secondary',
                                 default_value=bool(CONFIG.get('match_jpn_secondary', True)),
                                 callback=lambda s, a: on_change(s, a, 'match_jpn_secondary'))
                dpg.add_checkbox(tag='op_jpn_ter', label='Prefer JPN audio on Tertiary',
                                 default_value=bool(CONFIG.get('match_jpn_tertiary', True)),
                                 callback=lambda s, a: on_change(s, a, 'match_jpn_tertiary'))
                dpg.add_checkbox(tag='op_rm_dn', label='Remove dialog normalization (AC-3/eAC-3)',
                                 default_value=bool(CONFIG.get('apply_dialog_norm_gain', False)),
                                 callback=lambda s, a: on_change(s, a, 'apply_dialog_norm_gain'))
                dpg.add_separator()
                _row_label('Snapping')
                dpg.add_checkbox(tag='op_snap', label='Snap chapters to keyframes',
                                 default_value=bool(CONFIG.get('snap_chapters', False)),
                                 callback=lambda s, a: on_change(s, a, 'snap_chapters'))
                dpg.add_input_int(tag='op_snap_ms', default_value=int(CONFIG.get('snap_threshold_ms', 250)),
                                  step=5, min_value=0, max_value=10000,
                                  callback=lambda s, a: on_change(s, a, 'snap_threshold_ms'), width=200)
                dpg.add_checkbox(tag='op_snap_starts', label='Starts only',
                                 default_value=bool(CONFIG.get('snap_starts_only', True)),
                                 callback=lambda s, a: on_change(s, a, 'snap_starts_only'))
                dpg.add_separator()
                _row_label('Appearance')
                _row_label('UI font file (leave blank to auto-pick)')
                dpg.add_input_text(tag='op_font_file', width=600, default_value=CONFIG.get('ui_font_path', ''),
                                   callback=lambda s, a: on_change(s, a, 'ui_font_path'))
                _row_label('Font size')
                dpg.add_input_int(tag='op_font_size', step=1, min_value=8, max_value=48,
                                  default_value=int(CONFIG.get('ui_font_size', 18)),
                                  callback=lambda s, a: on_change(s, a, 'ui_font_size'), width=120)
                _row_label('Input line height')
                dpg.add_input_int(tag='op_line_h', step=1, min_value=20, max_value=72,
                                  default_value=int(CONFIG.get('input_line_height', 40)),
                                  callback=lambda s, a: on_change(s, a, 'input_line_height'), width=120)
                _row_label('Row spacing')
                dpg.add_input_int(tag='op_row_gap', step=1, min_value=0, max_value=32,
                                  default_value=int(CONFIG.get('row_gap', 8)),
                                  callback=lambda s, a: on_change(s, a, 'row_gap'), width=120)
                dpg.add_checkbox(tag='op_compact', label='Compact controls',
                                 default_value=bool(CONFIG.get('ui_compact_controls', False)),
                                 callback=lambda s, a: on_change(s, a, 'ui_compact_controls'))

            # Save / Load
            with dpg.tab(label='Save / Load'):
                _row_label('Persist or import/export all preferences.')
                dpg.add_button(label='Save', callback=lambda: apply_and_notify())
                dpg.add_button(label='Load', callback=_do_live_load)

    _refresh_from_config()

def show_options_modal():
    build_options_modal()
    dpg.configure_item('options_modal', show=True)
