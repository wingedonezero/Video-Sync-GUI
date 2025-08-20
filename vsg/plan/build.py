"""Moved implementations for plan.build (full-move RC)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import os, re, json, math, logging, subprocess, tempfile, pathlib
from pathlib import Path

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.tools import run_command, find_required_tools
def build_plan(ref_tracks, sec_tracks, ter_tracks, delays):
    plan = []
    for t in ref_tracks:
        if t['type'] == 'video':
            plan.append({'src': t['path'], 'type': 'video', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    for t in sec_tracks or []:
        if t['type'] == 'audio':
            plan.append({'src': t['path'], 'type': 'audio', 'lang': t['lang'], 'name': t['name'], 'from_group': 'sec', 'codec_id': t.get('codec_id', '')})
    for t in ref_tracks:
        if t['type'] == 'audio':
            plan.append({'src': t['path'], 'type': 'audio', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    for t in ter_tracks or []:
        if t['type'] == 'subtitles':
            plan.append({'src': t['path'], 'type': 'subtitles', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ter', 'codec_id': t.get('codec_id', '')})
    for t in sec_tracks or []:
        if t['type'] == 'subtitles':
            plan.append({'src': t['path'], 'type': 'subtitles', 'lang': t['lang'], 'name': t['name'], 'from_group': 'sec', 'codec_id': t.get('codec_id', '')})
    for t in ref_tracks:
        if t['type'] not in ('video', 'audio'):
            plan.append({'src': t['path'], 'type': t['type'], 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    return {'plan': plan, 'delays': delays}


def summarize_plan(plan_json, output_file, chapters_xml_path, attachments):
    """Return (track_order_str, lines[]) describing final output order & config."""
    lines = []
    plan = plan_json.get('plan', [])
    delays = plan_json.get('delays', {})
    lines.append('=== Merge Summary ===')
    lines.append(f'Output: {output_file}')
    lines.append(f"Chapters: {(chapters_xml_path if chapters_xml_path else '(none)')}")
    lines.append(f"Delays: secondary={delays.get('secondary_ms', 0)} ms, tertiary={delays.get('tertiary_ms', 0)} ms")
    lines.append('Inputs (grouped order):')
    for idx, trk in enumerate(plan):
        ttype = trk.get('type')
        grp = trk.get('from_group')
        lang = trk.get('lang') or 'und'
        name = (trk.get('name') or '').strip()
        codec = trk.get('codec_id') or ''
        lines.append(f"  [{idx}] {ttype:9s} | group={grp:3s} | lang={lang:3s} | name='{name}' | codec='{codec}'")
        lines.append(f"       path: {trk.get('src')}")
    if attachments:
        lines.append('Attachments:')
        for a in attachments:
            lines.append(f'  - {a}')
    else:
        lines.append('Attachments: (none)')
    track_order = ','.join((f'{i}:0' for i in range(len(plan))))
    lines.append(f'Track order: {track_order}')
    lines.append('=====================')
    return (track_order, lines)

