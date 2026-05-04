# vsg_core/chapters/process.py
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree as ET

from ..io.runner import CommandRunner
from .keyframes import probe_keyframes_ns

if TYPE_CHECKING:
    from vsg_core.models import AppSettings


def _parse_ns(t: str) -> int:
    hh, mm, rest = t.strip().split(":")
    ss, frac = ([*rest.split("."), "0"])[:2]
    frac = (frac + "000000000")[:9]
    return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1_000_000_000 + int(frac)


def _fmt_ns(ns: int) -> str:
    ns = max(0, ns)
    frac = ns % 1_000_000_000
    total_s = ns // 1_000_000_000
    hh = total_s // 3600
    mm = (total_s % 3600) // 60
    ss = total_s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{frac:09d}"


def _fmt_ns_for_log(ns: int) -> str:
    """
    Format nanoseconds as HH:MM:SS.mmm.uuu.nnn for maximum clarity.
    Example: 00:01:31.074.316.666
    Shows: hours:minutes:seconds.milliseconds.microseconds.nanoseconds
    """
    ns = max(0, ns)
    total_ns = ns

    # Extract each component
    total_us = total_ns // 1_000
    remaining_ns = total_ns % 1_000

    total_ms = total_us // 1_000
    remaining_us = total_us % 1_000

    total_s = total_ms // 1_000
    remaining_ms = total_ms % 1_000

    hh = total_s // 3600
    mm = (total_s % 3600) // 60
    ss = total_s % 60

    # Format as HH:MM:SS.mmm.uuu.nnn
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{remaining_ms:03d}.{remaining_us:03d}.{remaining_ns:03d}"


def _fmt_delta_for_log(delta_ns: int) -> str:
    """
    Formats a time delta for logging with unit-adaptive display.

    Returns:
        - "0ns" if zero
        - "+123ns" or "-123ns" if < 1 microsecond
        - "+123.456µs" or "-123.456µs" if < 1 millisecond
        - "+123.456ms" or "-123.456ms" if >= 1 millisecond
    """
    abs_delta = abs(delta_ns)
    sign = "+" if delta_ns > 0 else "-"

    if abs_delta == 0:
        return "0ns"
    elif abs_delta < 1_000:  # Less than 1 microsecond
        return f"{sign}{abs_delta}ns"
    elif abs_delta < 1_000_000:  # Less than 1 millisecond
        us_value = abs_delta / 1_000.0
        return f"{sign}{us_value:.3f}µs"
    else:  # 1 millisecond or more
        ms_value = abs_delta / 1_000_000.0
        return f"{sign}{ms_value:.3f}ms"


def _get_xpath_and_nsmap(root: ET.Element) -> (dict, str):
    """Detects if a namespace is used and returns the appropriate xpath prefix and nsmap."""
    if root.nsmap and None in root.nsmap:
        ns_uri = root.nsmap[None]
        return {"def": ns_uri}, "def:"
    return None, ""


def _normalize_and_dedupe_chapters(
    root: ET.Element, runner: CommandRunner, nsmap: dict, prefix: str
):
    parent_map = {c: p for p in root.iter() for c in p}

    all_atoms = root.xpath(f"//{prefix}ChapterAtom", namespaces=nsmap)
    chapters = []
    for i, atom in enumerate(all_atoms):
        st_el = atom.find(f"{prefix}ChapterTimeStart", namespaces=nsmap)
        if st_el is not None and st_el.text:
            name_node = atom.find(f".//{prefix}ChapterString", namespaces=nsmap)
            name = name_node.text if name_node is not None else f"Chapter Atom {i + 1}"
            chapters.append(
                {"atom": atom, "start_ns": _parse_ns(st_el.text), "name": name}
            )

    chapters.sort(key=lambda x: x["start_ns"])

    unique_chapters = []
    seen_start_times = set()
    for chap in chapters:
        start_time = chap["start_ns"]
        if start_time not in seen_start_times:
            unique_chapters.append(chap)
            seen_start_times.add(start_time)
        else:
            runner._log_message(
                f"  - Removed duplicate chapter '{chap['name']}' found at timestamp {_fmt_ns_for_log(start_time)}"
            )
            parent = parent_map.get(chap["atom"])
            if parent is not None:
                try:
                    parent.remove(chap["atom"])
                except ValueError:
                    pass

    for i, chap in enumerate(unique_chapters):
        atom = chap["atom"]
        st_ns = chap["start_ns"]
        en_el = atom.find(f"{prefix}ChapterTimeEnd", namespaces=nsmap)
        next_start_ns = (
            unique_chapters[i + 1]["start_ns"] if i + 1 < len(unique_chapters) else None
        )

        original_en_text = en_el.text if en_el is not None and en_el.text else None

        desired_en_ns = 0
        reason = ""

        if next_start_ns is not None:
            desired_en_ns = next_start_ns
            reason = " (to create seamless chapters)"
        else:
            original_en_ns = _parse_ns(original_en_text) if original_en_text else st_ns
            desired_en_ns = max(st_ns + 1_000_000_000, original_en_ns)

        if en_el is None:
            en_el = ET.SubElement(
                atom,
                f"{prefix.rstrip(':')}ChapterTimeEnd" if prefix else "ChapterTimeEnd",
            )

        new_text = _fmt_ns(desired_en_ns)
        if en_el.text != new_text:
            original_display = (
                _fmt_ns_for_log(_parse_ns(original_en_text))
                if original_en_text
                else "None"
            )
            runner._log_message(
                f"  - Normalized '{chap['name']}' end time: ({original_display} -> {_fmt_ns_for_log(desired_en_ns)}){reason}"
            )
            en_el.text = new_text


def _extract_language_from_display(display_node: ET.Element, nsmap: dict, prefix: str):
    """Extract both language fields from a ChapterDisplay node, returning tuple (chapter_lang, ietf_lang)."""
    try:
        # Extract ChapterLanguage (legacy 3-letter code)
        lang_node = display_node.find(f"{prefix}ChapterLanguage", namespaces=nsmap)
        chapter_lang = (
            lang_node.text.strip()
            if lang_node is not None and lang_node.text
            else "und"
        )

        # Extract ChapLanguageIETF (newer IETF format) - may not exist
        ietf_node = display_node.find(f"{prefix}ChapLanguageIETF", namespaces=nsmap)
        ietf_lang = (
            ietf_node.text.strip() if ietf_node is not None and ietf_node.text else None
        )

        # If no IETF language, derive it from the 3-letter code or use 'und'
        if ietf_lang is None:
            # Simple mapping for common cases
            lang_map = {
                "eng": "en",
                "jpn": "ja",
                "spa": "es",
                "fra": "fr",
                "deu": "de",
                "ita": "it",
                "por": "pt",
                "rus": "ru",
                "kor": "ko",
                "zho": "zh",
            }
            ietf_lang = lang_map.get(chapter_lang, "und")

        # Always return a tuple of exactly 2 strings
        return chapter_lang, ietf_lang

    except Exception:
        # Fallback on any error - always return a tuple
        return "und", "und"


def _create_chapter_display(
    atom: ET.Element,
    chapter_name: str,
    language: str,
    ietf_language: str,
    nsmap: dict,
    prefix: str,
):
    """Create a new ChapterDisplay element with proper namespace handling and both language fields."""
    # Create the display element with proper namespace
    if prefix:
        # Strip the colon from prefix for element creation
        prefix_clean = prefix.rstrip(":")
        display_elem = ET.SubElement(atom, f"{prefix_clean}ChapterDisplay")
        string_elem = ET.SubElement(display_elem, f"{prefix_clean}ChapterString")
        lang_elem = ET.SubElement(display_elem, f"{prefix_clean}ChapterLanguage")
        ietf_elem = ET.SubElement(display_elem, f"{prefix_clean}ChapLanguageIETF")
    else:
        display_elem = ET.SubElement(atom, "ChapterDisplay")
        string_elem = ET.SubElement(display_elem, "ChapterString")
        lang_elem = ET.SubElement(display_elem, "ChapterLanguage")
        ietf_elem = ET.SubElement(display_elem, "ChapLanguageIETF")

    string_elem.text = chapter_name
    lang_elem.text = language
    ietf_elem.text = ietf_language


def process_chapters(
    ref_mkv: str,
    temp_dir: Path,
    runner: CommandRunner,
    tool_paths: dict,
    settings: AppSettings,
    shift_ms: int,
    *,
    keyframe_ref_mkv: str | None = None,
    donor_offset_ns: int = 0,
    pin_first_to_zero: bool = False,
    pin_telemetry: dict[str, Any] | None = None,
) -> str | None:
    """
    Extract, shift, snap, normalize, and rewrite chapters.

    Args:
        ref_mkv: File to read chapters from (mkvextract source).
        temp_dir: Where to write the output XML.
        runner: For shelling out and logging.
        tool_paths: Resolved tool paths for the runner.
        settings: AppSettings (snap behavior, rename, language config).
        shift_ms: Integer-ms shift applied AFTER snap. Represents the
            global container shift (matches what mkvmerge applies to the
            video as ``--sync 0:N``). Must be integer ms for correct
            keyframe alignment in the container.
        keyframe_ref_mkv: File to probe keyframes from. Defaults to
            ``ref_mkv`` for back-compat. When chapters come from a donor
            source, pass Source 1 here so chapters snap to the actual
            video's keyframes (donor-shifted into Source 1 video time
            via ``donor_offset_ns`` first).
        donor_offset_ns: Nanosecond shift applied BEFORE snap, used to
            convert donor-source chapter timestamps into Source 1 video
            time. Carries the full sub-ms precision of the source-delay
            value so we don't lose accuracy at this stage. Defaults to
            0 (Source 1 is the chapter source \u2014 no donor shift).
        pin_first_to_zero: When True AND the donor's chronologically-
            first chapter was originally at 00:00:00, force it back to
            0 after donor offset (before snap and global shift). This
            preserves the "chapter 1 marks the start of the file"
            convention when a positive donor offset would otherwise
            push it past 0. Negative offsets that drive it below 0 are
            already clamped by ``_fmt_ns``. Donors that authored chapter
            1 at non-zero (rare/atypical) keep their authored value.
            Snap runs after the pin so it sees the final intended
            value; global shift is applied normally on top. Defaults
            to False (existing Source 1 behavior preserved).
        pin_telemetry: Optional mutable dict; if provided AND the pin
            actually fired, populated with ``{"fired": True,
            "from_ns": <value before pin>}``. Lets the caller surface
            the event as a structured audit warning (since pin firing
            is rare and worth flagging for the user to verify).
    """
    xml_content = runner.run(["mkvextract", str(ref_mkv), "chapters", "-"], tool_paths)
    if not xml_content or not xml_content.strip():
        runner._log_message("No chapters found in reference file.")
        return None

    keyframe_source = keyframe_ref_mkv or ref_mkv

    try:
        if xml_content.startswith("\ufeff"):
            xml_content = xml_content[1:]

        parser = ET.XMLParser(remove_blank_text=True, recover=True)
        root = ET.fromstring(xml_content.encode("utf-8"), parser)

        # Detect namespace and get the correct prefix for XPath queries
        nsmap, prefix = _get_xpath_and_nsmap(root)

        # Donor mode "chapter 1 = file start" preservation: capture the
        # chronologically-first ChapterAtom and whether it was originally
        # at exactly 00:00:00. Used later to undo a positive shift that
        # would otherwise push it past 0. Done BEFORE any shifts so we
        # know the donor's authored intent.
        first_atom_orig_zero: ET.Element | None = None
        if pin_first_to_zero:
            atoms_pre = root.xpath(f"//{prefix}ChapterAtom", namespaces=nsmap)
            best_atom = None
            best_ns: int | None = None
            for atom in atoms_pre:
                st_el = atom.find(f"{prefix}ChapterTimeStart", namespaces=nsmap)
                if st_el is None or not st_el.text:
                    continue
                cur_ns = _parse_ns(st_el.text)
                if best_ns is None or cur_ns < best_ns:
                    best_ns = cur_ns
                    best_atom = atom
            if best_atom is not None and best_ns == 0:
                first_atom_orig_zero = best_atom

        # Donor \u2192 Source 1 video-time shift (applied BEFORE snap so we
        # snap against the keyframe-ref file's keyframes). Sub-ms
        # precision is preserved in nanoseconds; snap will absorb residuals.
        if donor_offset_ns != 0:
            runner._log_message(
                f"[Chapters] Donor offset: shifting timestamps by "
                f"{_fmt_delta_for_log(donor_offset_ns)} "
                f"(donor \u2192 Source 1 video time)."
            )
            for tag_name in ["ChapterTimeStart", "ChapterTimeEnd"]:
                for node in root.xpath(f"//{prefix}{tag_name}", namespaces=nsmap):
                    if node is not None and node.text:
                        node.text = _fmt_ns(_parse_ns(node.text) + donor_offset_ns)

        # Pin first-in-order chapter back to 0 if (a) it was originally
        # at 0 in the donor and (b) the donor offset has pushed it past 0.
        # Negative offsets are already clamped to 0 by ``_fmt_ns``, so
        # this only fires for positive donor offsets. Runs BEFORE snap so
        # snap operates on the final intended values (the start-of-stream
        # keyframe at 0 is guaranteed in MKV/H.264, so snap will keep
        # chapter 1 at 0 cleanly). Runs BEFORE global shift so the
        # result still ends at +global_shift in the container, matching
        # where Source 1's video begins in positive_only mode.
        if first_atom_orig_zero is not None:
            first_start = first_atom_orig_zero.find(
                f"{prefix}ChapterTimeStart", namespaces=nsmap
            )
            if first_start is not None and first_start.text:
                current_ns = _parse_ns(first_start.text)
                if current_ns != 0:
                    runner._log_message(
                        f"[Chapters] Pinning first-in-order chapter from "
                        f"{_fmt_ns_for_log(current_ns)} back to "
                        f"00:00:00.000 (was originally at 0 in donor; "
                        f"chapter 1 marks file start)."
                    )
                    first_start.text = _fmt_ns(0)
                    if pin_telemetry is not None:
                        pin_telemetry["fired"] = True
                        pin_telemetry["from_ns"] = current_ns

        # IMPORTANT: Snap FIRST (in video time), THEN shift to container time
        # This ensures chapters land on actual keyframes in the final muxed file
        # (Video gets container delay, so keyframe at video_time X = container_time X + shift)
        if settings.snap_chapters:
            keyframes_ns = probe_keyframes_ns(keyframe_source, runner, tool_paths)
            if keyframes_ns:
                _snap_chapter_times_inplace(
                    root, keyframes_ns, settings, runner, nsmap, prefix
                )
            else:
                runner._log_message(
                    "[Chapters] Snap skipped: could not load keyframes."
                )

        # Now shift all timestamps to container time
        # Must match video container delay exactly (integer ms) for correct keyframe alignment
        shift_ns = shift_ms * 1_000_000
        if shift_ns != 0:
            runner._log_message(f"[Chapters] Shifting all timestamps by +{shift_ms}ms.")
            for tag_name in ["ChapterTimeStart", "ChapterTimeEnd"]:
                for node in root.xpath(f"//{prefix}{tag_name}", namespaces=nsmap):
                    if node is not None and node.text:
                        node.text = _fmt_ns(_parse_ns(node.text) + shift_ns)

        runner._log_message("[Chapters] Normalizing chapter data...")
        _normalize_and_dedupe_chapters(root, runner, nsmap, prefix)

        if settings.rename_chapters:
            runner._log_message('[Chapters] Renaming chapters to "Chapter NN"...')

            # Use consistent namespace-aware XPath query
            final_chapter_atoms = root.xpath(f"//{prefix}ChapterAtom", namespaces=nsmap)

            for i, atom in enumerate(final_chapter_atoms, 1):
                # Find the first ChapterDisplay and extract both language fields
                original_lang = "und"  # Default fallback for ChapterLanguage
                original_ietf = "und"  # Default fallback for ChapLanguageIETF

                display_node = atom.find(f"{prefix}ChapterDisplay", namespaces=nsmap)
                if display_node is not None:
                    try:
                        original_lang, original_ietf = _extract_language_from_display(
                            display_node, nsmap, prefix
                        )
                    except ValueError as e:
                        runner._log_message(
                            f"  - Warning: Could not extract language from chapter {i}: {e}. Using defaults."
                        )
                        original_lang, original_ietf = "und", "und"
                    # Remove the old display node
                    atom.remove(display_node)

                # Create new display with both preserved language fields
                _create_chapter_display(
                    atom,
                    f"Chapter {i:02d}",
                    original_lang,
                    original_ietf,
                    nsmap,
                    prefix,
                )

                runner._log_message(
                    f"  - Renamed chapter {i} (language: {original_lang}, IETF: {original_ietf})"
                )

        out_path = temp_dir / f"{Path(ref_mkv).stem}_chapters_modified.xml"
        tree = ET.ElementTree(root)
        tree.write(
            str(out_path), encoding="UTF-8", xml_declaration=True, pretty_print=True
        )
        runner._log_message(f"Chapters XML written to: {out_path}")
        return str(out_path)

    except Exception as e:
        runner._log_message(f"[ERROR] Chapter processing failed: {e}")
        return None


def _snap_chapter_times_inplace(
    root,
    keyframes_ns: list[int],
    settings: AppSettings,
    runner: CommandRunner,
    nsmap: dict,
    prefix: str,
):
    import bisect

    # snap_mode is a string literal type
    mode = settings.snap_mode
    threshold_ms = settings.snap_threshold_ms
    starts_only = settings.snap_starts_only
    threshold_ns = threshold_ms * 1_000_000
    moved, on_kf, too_far = 0, 0, 0

    runner._log_message(
        f"[Chapters] Snapping with mode={mode}, threshold={threshold_ms}ms..."
    )

    def pick_candidate(ts_ns: int) -> int:
        if not keyframes_ns:
            return ts_ns
        i = bisect.bisect_right(keyframes_ns, ts_ns)
        prev_kf = keyframes_ns[i - 1] if i > 0 else keyframes_ns[0]
        if mode == "previous":
            return prev_kf
        else:
            next_kf = keyframes_ns[i] if i < len(keyframes_ns) else keyframes_ns[-1]
            return prev_kf if abs(ts_ns - prev_kf) <= abs(ts_ns - next_kf) else next_kf

    # Use consistent namespace-aware XPath query
    chapter_atoms = root.xpath(f"//{prefix}ChapterAtom", namespaces=nsmap)
    for i, atom in enumerate(chapter_atoms):
        tags_to_snap = (
            ["ChapterTimeStart"]
            if starts_only
            else ["ChapterTimeStart", "ChapterTimeEnd"]
        )

        chapter_name_node = atom.find(f".//{prefix}ChapterString", namespaces=nsmap)
        chapter_name = (
            chapter_name_node.text
            if chapter_name_node is not None
            else f"Chapter Atom {i + 1}"
        )

        for tag in tags_to_snap:
            node = atom.find(f"{prefix}{tag}", namespaces=nsmap)
            if node is not None and node.text:
                original_ns = _parse_ns(node.text)
                candidate_ns = pick_candidate(original_ns)
                delta_ns = candidate_ns - original_ns  # Keep sign for direction
                abs_delta_ns = abs(delta_ns)

                if abs_delta_ns == 0:
                    if tag == "ChapterTimeStart":
                        on_kf += 1
                    runner._log_message(
                        f"  - Kept '{chapter_name}' ({_fmt_ns_for_log(original_ns)}) - already on keyframe."
                    )
                elif abs_delta_ns <= threshold_ns:
                    node.text = _fmt_ns(candidate_ns)
                    if tag == "ChapterTimeStart":
                        moved += 1
                    delta_str = _fmt_delta_for_log(delta_ns)
                    runner._log_message(
                        f"  - Snapped '{chapter_name}' ({_fmt_ns_for_log(original_ns)}) -> {_fmt_ns_for_log(candidate_ns)} (moved by {delta_str})"
                    )
                else:
                    if tag == "ChapterTimeStart":
                        too_far += 1
                    delta_str = _fmt_delta_for_log(delta_ns)
                    runner._log_message(
                        f"  - Skipped '{chapter_name}' ({_fmt_ns_for_log(original_ns)}) - nearest keyframe is {delta_str} away (exceeds threshold)."
                    )

    runner._log_message(
        f"[Chapters] Snap complete: {moved} moved, {on_kf} on keyframe, {too_far} skipped."
    )
