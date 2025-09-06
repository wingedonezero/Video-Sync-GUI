# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from ..io.runner import CommandRunner
from .keyframes import probe_keyframes_ns

def _parse_ns(t: str) -> int:
    hh, mm, rest = t.strip().split(':')
    ss, frac = (rest.split('.') + ['0'])[:2]
    frac = (frac + '000000000')[:9]
    return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1_000_000_000 + int(frac)

def _fmt_ns(ns: int) -> str:
    ns = max(0, ns)
    frac = ns % 1_000_000_000
    total_s = ns // 1_000_000_000
    hh = total_s // 3600
    mm = (total_s % 3600) // 60
    ss = total_s % 60
    return f'{hh:02d}:{mm:02d}:{ss:02d}.{frac:09d}'

def _normalize_chapter_end_times(root: ET.Element, runner: CommandRunner):
    atoms = root.findall('.//ChapterAtom')
    chapters = []
    for atom in atoms:
        st_el = atom.find('ChapterTimeStart')
        if st_el is not None and st_el.text:
            chapters.append({'atom': atom, 'start_ns': _parse_ns(st_el.text)})
    chapters.sort(key=lambda x: x['start_ns'])
    fixed_count = 0
    for i, chap in enumerate(chapters):
        atom = chap['atom']
        st_ns = chap['start_ns']
        en_el = atom.find('ChapterTimeEnd')
        next_start_ns = chapters[i + 1]['start_ns'] if i + 1 < len(chapters) else None
        desired_en_ns = _parse_ns(en_el.text) if en_el is not None and en_el.text else st_ns + 1_000_000
        if next_start_ns is not None:
            desired_en_ns = min(desired_en_ns, next_start_ns)
        desired_en_ns = max(desired_en_ns, st_ns + 1)
        if en_el is None:
            en_el = ET.SubElement(atom, 'ChapterTimeEnd')
        new_text = _fmt_ns(desired_en_ns)
        if en_el.text != new_text:
            en_el.text = new_text
            fixed_count += 1
    if fixed_count > 0:
        runner._log_message(f'[Chapters] Normalized {fixed_count} chapter end times.')

def process_chapters(ref_mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, config: dict, shift_ms: int) -> Optional[str]:
    xml_content = runner.run(['mkvextract', str(ref_mkv), 'chapters', '-'], tool_paths)
    if not xml_content or not xml_content.strip():
        runner._log_message('No chapters found in reference file.')
        return None
    try:
        if xml_content.startswith('\ufeff'):
            xml_content = xml_content[1:]
        root = ET.fromstring(xml_content)
        if config.get('rename_chapters', False):
            for i, atom in enumerate(root.findall('.//ChapterAtom'), 1):
                disp = atom.find('ChapterDisplay')
                if disp is not None:
                    atom.remove(disp)
                new_disp = ET.SubElement(atom, 'ChapterDisplay')
                ET.SubElement(new_disp, 'ChapterString').text = f'Chapter {i:02d}'
                ET.SubElement(new_disp, 'ChapterLanguage').text = 'und'
            runner._log_message('[Chapters] Renamed chapters to "Chapter NN".')
        shift_ns = shift_ms * 1_000_000
        if shift_ns != 0:
            for atom in root.findall('.//ChapterAtom'):
                for tag in ('ChapterTimeStart', 'ChapterTimeEnd'):
                    node = atom.find(tag)
                    if node is not None and node.text:
                        node.text = _fmt_ns(_parse_ns(node.text) + shift_ns)
            runner._log_message(f'[Chapters] Shifted all timestamps by +{shift_ms} ms.')
        if config.get('snap_chapters', False):
            keyframes_ns = probe_keyframes_ns(ref_mkv, runner, tool_paths)
            if keyframes_ns:
                _snap_chapter_times_inplace(root, keyframes_ns, config, runner)
            else:
                runner._log_message('[Chapters] Snap skipped: could not load keyframes.')
        _normalize_chapter_end_times(root, runner)
        out_path = temp_dir / f'{Path(ref_mkv).stem}_chapters_modified.xml'
        ET.ElementTree(root).write(out_path, encoding='UTF-8', xml_declaration=True)
        runner._log_message(f'Chapters XML written to: {out_path}')
        return str(out_path)
    except Exception as e:
        runner._log_message(f'[ERROR] Chapter processing failed: {e}')
        return None

def _snap_chapter_times_inplace(root, keyframes_ns: list[int], config: dict, runner: CommandRunner):
    import bisect
    mode = config.get('snap_mode', 'previous')
    threshold_ms = config.get('snap_threshold_ms', 250)
    starts_only = config.get('snap_starts_only', True)
    threshold_ns = threshold_ms * 1_000_000
    changed_count, moved, on_kf, too_far = 0, 0, 0, 0

    def pick_candidate(ts_ns: int) -> int:
        if not keyframes_ns: return ts_ns
        i = bisect.bisect_right(keyframes_ns, ts_ns)
        prev_kf = keyframes_ns[i - 1] if i > 0 else keyframes_ns[0]
        if mode == 'previous':
            return prev_kf
        else:
            next_kf = keyframes_ns[i] if i < len(keyframes_ns) else keyframes_ns[-1]
            return prev_kf if abs(ts_ns - prev_kf) <= abs(ts_ns - next_kf) else next_kf

    for atom in root.findall('.//ChapterAtom'):
        tags = ['ChapterTimeStart'] if starts_only else ['ChapterTimeStart', 'ChapterTimeEnd']
        for tag in tags:
            node = atom.find(tag)
            if node is not None and node.text:
                original_ns = _parse_ns(node.text)
                candidate_ns = pick_candidate(original_ns)
                delta_ns = abs(original_ns - candidate_ns)
                if delta_ns == 0:
                    if tag == 'ChapterTimeStart': on_kf += 1
                elif delta_ns <= threshold_ns:
                    node.text = _fmt_ns(candidate_ns); changed_count += 1
                    if tag == 'ChapterTimeStart': moved += 1
                else:
                    if tag == 'ChapterTimeStart': too_far += 1
    runner._log_message(f'[Chapters] Snap result: moved={moved}, on_kf={on_kf}, too_far={too_far} (kfs={len(keyframes_ns)}, mode={mode}, thr={threshold_ms}ms, starts_only={starts_only})')
