# Moved from video_sync_gui.py — mux.tokens (Phase C, move-only)
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import json, re, os, math
from vsg.logbus import _log

def _tokens_for_track(track: Dict[str, Any], group: str, delays_ms: Dict[str, int], default_flag: Optional[bool]=None):
    toks: List[str] = []
    name = track.get('name', '')
    lang = track.get('lang', '')
    ttype = track.get('type', '')
    src = str(track.get('src', ''))
    grp = group if group in {'ref', 'sec', 'ter'} else None
    if not grp:
        if 'ter_track_' in src:
            grp = 'ter'
        elif 'sec_track_' in src:
            grp = 'sec'
        else:
            grp = 'ref'
    delay = 0
    if grp == 'sec':
        delay = int(delays_ms.get('secondary_ms', 0) or 0)
    elif grp == 'ter':
        delay = int(delays_ms.get('tertiary_ms', 0) or 0)
    else:
        delay = 0
    delay += int(delays_ms.get('_global_shift', 0) or 0)
    toks += ['--track-name', f"0:{name or ''}"]
    if lang:
        toks += ['--language', f'0:{lang}']
    toks += ['--sync', f'0:{delay}']
    if default_flag is not None:
        toks += ['--default-track-flag', f"0:{('yes' if default_flag else 'no')}"]
    return toks



def build_mkvmerge_tokens(plan_json, output_file, chapters_xml_path, attachments, track_order_str=None):
    """Return JSON array-of-strings for mkvmerge @opts.json; each input wrapped in parentheses;
       add --compression 0:none for each input; optional dialnorm removal; explicit --track-order.
       Set languages for all tracks; compute default flags:
         - Video: first/only video = yes
         - Audio: first audio = yes; others = no
         - Subtitles: Signs/Songs = yes; else if NO English audio -> first subtitle = yes; others = no
    """
    tokens: List[str] = ['--output', str(output_file)]
    if chapters_xml_path:
        tokens += ['--chapters', str(chapters_xml_path)]
    delays = plan_json.get('delays', {})
    plan = list(plan_json.get('plan', []))
    audio_langs = [(t.get('lang') or '').lower() for t in plan if t.get('type') == 'audio']
    has_english_audio = any((l in ('en', 'eng') for l in audio_langs))
    video_indices = [i for i, t in enumerate(plan) if t.get('type') == 'video']
    audio_indices = [i for i, t in enumerate(plan) if t.get('type') == 'audio']
    sub_indices = [i for i, t in enumerate(plan) if t.get('type') == 'subtitles']
    first_video_idx = video_indices[0] if video_indices else None
    first_audio_idx = audio_indices[0] if audio_indices else None
    default_sub_idx = None
    if CONFIG.get('first_sub_default', True):


