from __future__ import annotations
import dearpygui.dearpygui as dpg
from vsg.settings_core import CONFIG, save_settings, load_settings, on_change, adopt_into_app, apply_and_notify

def _set(tag, value):
    if dpg.does_item_exist(tag):
        try: dpg.set_value(tag, value)
        except Exception: pass

def _refresh_from_config():
    # Storage
    _set('op_out', CONFIG.get('output_folder',''))
    _set('op_temp', CONFIG.get('temp_root',''))
    _set('op_ffmpeg', CONFIG.get('ffmpeg_path',''))
    _set('op_ffprobe', CONFIG.get('ffprobe_path',''))
    _set('op_mkvmerge', CONFIG.get('mkvmerge_path',''))
    _set('op_mkvextract', CONFIG.get('mkvextract_path',''))
    _set('op_vdiff', CONFIG.get('videodiff_path',''))
    # Analysis
    _set('op_scan_cnt', int(CONFIG.get('scan_chunk_count',10)))
    _set('op_scan_dur', int(CONFIG.get('scan_chunk_duration',15)))
    _set('op_min_match', float(CONFIG.get('min_match_pct',5.0)))
    _set('analysis_mode_combo', CONFIG.get('analysis_mode','Audio Correlation'))
    _set('workflow_combo_pref', CONFIG.get('workflow','Analyze & Merge'))
    # VideoDiff
    _set('vd_err_min', float(CONFIG.get('videodiff_error_min',0.0)))
    _set('vd_err_max', float(CONFIG.get('videodiff_error_max',100.0)))
    # Global
    _set('op_jpn_sec', bool(CONFIG.get('match_jpn_secondary', True)))
    _set('op_jpn_ter', bool(CONFIG.get('match_jpn_tertiary', True)))
    _set('op_rm_dn', bool(CONFIG.get('apply_dialog_norm_gain', False)))
    _set('op_snap', bool(CONFIG.get('snap_chapters', False)))
    _set('op_snap_ms', int(CONFIG.get('snap_threshold_ms', 250)))
    _set('op_snap_starts', bool(CONFIG.get('snap_starts_only', True)))
    # Appearance
    _set('op_font_file', CONFIG.get('ui_font_path',''))
    _set('op_font_size', int(CONFIG.get('ui_font_size',18)))
    _set('op_line_h', int(CONFIG.get('input_line_height',40)))
    _set('op_row_gap', int(CONFIG.get('row_gap',8)))
    _set('op_compact', bool(CONFIG.get('ui_compact_controls', False)))

    # Toggle AC vs VideoDiff groups
    mode = CONFIG.get('analysis_mode','Audio Correlation')
    dpg.configure_item('ac_group', show=(mode=='Audio Correlation'))
    dpg.configure_item('vd_group', show=(mode=='VideoDiff'))

def _do_live_load():
    conf = load_settings()
    adopt_into_app(conf)     # triggers appearance listener
    _refresh_from_config()   # update controls immediately

def build_options_modal():
    if dpg.does_item_exist('options_modal'):
        dpg.delete_item('options_modal')
    with dpg.window(modal=True, label='Preferences', tag='options_modal', width=880, height=560, pos=(120, 60)):
        with dpg.tab_bar():
            with dpg.tab(label='Storage'):
                dpg.add_text('Output folder'); dpg.add_input_text(tag='op_out', width=560, callback=lambda s,a: on_change(s,a,user_data='output_folder'))
                dpg.add_text('Temp folder'); dpg.add_input_text(tag='op_temp', width=560, callback=lambda s,a: on_change(s,a,user_data='temp_root'))
                dpg.add_separator()
                dpg.add_text('Tool paths (leave blank to use PATH)')
                for label, tag, key in [('FFmpeg','op_ffmpeg','ffmpeg_path'),('FFprobe','op_ffprobe','ffprobe_path'),
                                        ('mkvmerge','op_mkvmerge','mkvmerge_path'),('mkvextract','op_mkvextract','mkvextract_path'),
                                        ('VideoDiff','op_vdiff','videodiff_path')]:
                    dpg.add_text(label); dpg.add_input_text(tag=tag, width=560, callback=lambda s,a,u=key: on_change(s,a,user_data=u))

            with dpg.tab(label='Analysis'):
                dpg.add_text('Workflow')
                dpg.add_combo(tag='workflow_combo_pref', items=['Analyze Only','Analyze & Merge'],
                              default_value=CONFIG.get('workflow','Analyze & Merge'),
                              callback=lambda s,a: on_change(s,a,user_data='workflow'))
                dpg.add_text('Mode')
                dpg.add_combo(tag='analysis_mode_combo', items=['Audio Correlation','VideoDiff'],
                              default_value=CONFIG.get('analysis_mode','Audio Correlation'),
                              callback=lambda s,a: on_change(s,a,user_data='analysis_mode'))
                dpg.add_separator()
                with dpg.group(tag='ac_group', show=(CONFIG.get('analysis_mode','Audio Correlation')=='Audio Correlation')):
                    dpg.add_text('Audio correlation parameters')
                    dpg.add_text('Scan chunk count'); dpg.add_input_int(tag='op_scan_cnt', step=1, min_value=1, max_value=200,
                        default_value=int(CONFIG.get('scan_chunk_count',10)), callback=lambda s,a: on_change(s,a,user_data='scan_chunk_count'))
                    dpg.add_text('Chunk duration (s)'); dpg.add_input_int(tag='op_scan_dur', step=1, min_value=1, max_value=3600,
                        default_value=int(CONFIG.get('scan_chunk_duration',15)), callback=lambda s,a: on_change(s,a,user_data='scan_chunk_duration'))
                    dpg.add_text('Minimum match %'); dpg.add_input_float(tag='op_min_match', step=0.5, min_value=0.0, max_value=100.0,
                        default_value=float(CONFIG.get('min_match_pct',5.0)), callback=lambda s,a: on_change(s,a,user_data='min_match_pct'))
                with dpg.group(tag='vd_group', show=(CONFIG.get('analysis_mode','Audio Correlation')=='VideoDiff')):
                    dpg.add_text('VideoDiff parameters')
                    dpg.add_text('Min error'); dpg.add_input_float(tag='vd_err_min', step=0.01, min_value=0.0, max_value=10000.0,
                        default_value=float(CONFIG.get('videodiff_error_min',0.0)), callback=lambda s,a: on_change(s,a,user_data='videodiff_error_min'))
                    dpg.add_text('Max error'); dpg.add_input_float(tag='vd_err_max', step=0.01, min_value=0.0, max_value=10000.0,
                        default_value=float(CONFIG.get('videodiff_error_max',100.0)), callback=lambda s,a: on_change(s,a,user_data='videodiff_error_max'))

            with dpg.tab(label='Global'):
                dpg.add_text('Audio/Chapters')
                dpg.add_checkbox(tag='op_jpn_sec', label='Prefer JPN audio on Secondary', default_value=bool(CONFIG.get('match_jpn_secondary',True)),
                                 callback=lambda s,a: on_change(s,a,user_data='match_jpn_secondary'))
                dpg.add_checkbox(tag='op_jpn_ter', label='Prefer JPN audio on Tertiary', default_value=bool(CONFIG.get('match_jpn_tertiary',True)),
                                 callback=lambda s,a: on_change(s,a,user_data='match_jpn_tertiary'))
                dpg.add_checkbox(tag='op_rm_dn', label='Remove dialog normalization (AC-3/eAC-3)',
                                 default_value=bool(CONFIG.get('apply_dialog_norm_gain',False)),
                                 callback=lambda s,a: on_change(s,a,user_data='apply_dialog_norm_gain'))
                dpg.add_separator()
                dpg.add_text('Snapping')
                dpg.add_checkbox(tag='op_snap', label='Snap chapters to keyframes', default_value=bool(CONFIG.get('snap_chapters',False)),
                                 callback=lambda s,a: on_change(s,a,user_data='snap_chapters'))
                dpg.add_input_int(tag='op_snap_ms', default_value=int(CONFIG.get('snap_threshold_ms',250)),
                                  step=5, min_value=0, max_value=10000, callback=lambda s,a: on_change(s,a,user_data='snap_threshold_ms'))
                dpg.add_checkbox(tag='op_snap_starts', label='Starts only', default_value=bool(CONFIG.get('snap_starts_only',True)),
                                 callback=lambda s,a: on_change(s,a,user_data='snap_starts_only'))
                dpg.add_separator()
                dpg.add_text('Appearance')
                dpg.add_input_text(tag='op_font_file', width=560, hint='UI font file (leave blank to auto-pick)',
                                   default_value=CONFIG.get('ui_font_path',''),
                                   callback=lambda s,a: on_change(s,a,user_data='ui_font_path'))
                dpg.add_input_int(tag='op_font_size', default_value=int(CONFIG.get('ui_font_size',18)), step=1, min_value=8, max_value=48,
                                  callback=lambda s,a: on_change(s,a,user_data='ui_font_size'))
                dpg.add_input_int(tag='op_line_h', default_value=int(CONFIG.get('input_line_height',40)), step=1, min_value=20, max_value=72,
                                  callback=lambda s,a: on_change(s,a,user_data='input_line_height'))
                dpg.add_input_int(tag='op_row_gap', default_value=int(CONFIG.get('row_gap',8)), step=1, min_value=0, max_value=32,
                                  callback=lambda s,a: on_change(s,a,user_data='row_gap'))
                dpg.add_checkbox(tag='op_compact', label='Compact controls', default_value=bool(CONFIG.get('ui_compact_controls',False)),
                                 callback=lambda s,a: on_change(s,a,user_data='ui_compact_controls'))

            with dpg.tab(label='Save / Load'):
                dpg.add_button(label='Save', callback=lambda: apply_and_notify())
                dpg.add_button(label='Load', callback=_do_live_load)

def show_options_modal():
    build_options_modal()
    _refresh_from_config()
    dpg.configure_item('options_modal', show=True)
