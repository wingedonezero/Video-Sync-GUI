# vsg_core/postprocess/auditors/chapters.py
# -*- coding: utf-8 -*-
import re
from typing import Dict, Optional
from pathlib import Path
from lxml import etree as ET

from .base import BaseAuditor


class ChaptersAuditor(BaseAuditor):
    """Verifies chapters were preserved and processed correctly."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict, final_ffprobe_data=None) -> int:
        """
        Audits chapters:
        - If chapters were processed: verifies final matches processed version
        - If chapters weren't processed: verifies final matches source
        Returns the number of issues found.
        """
        issues = 0

        # Check if SOURCE has chapters
        source1_file = self.ctx.sources.get("Source 1")
        if not source1_file:
            self.log("✅ No Source 1 file to check for chapters.")
            return 0

        source_chapters_xml = self._extract_chapters(source1_file)
        source_has_chapters = bool(source_chapters_xml)

        # Check if FINAL has chapters
        final_chapters_xml = self._extract_chapters(final_mkv_path)
        final_has_chapters = bool(final_chapters_xml)

        # Determine what we should compare against
        if self.ctx.chapters_xml:
            # Chapters were PROCESSED - compare final vs processed
            self.log(f"  → Chapter processing was enabled")
            return self._verify_processed_chapters(final_chapters_xml)
        else:
            # Chapters were NOT processed - compare final vs source
            self.log(f"  → Chapter processing was not enabled")
            return self._verify_unprocessed_chapters(source_chapters_xml, final_chapters_xml, source_has_chapters, final_has_chapters)

    def _verify_processed_chapters(self, final_chapters_xml: Optional[str]) -> int:
        """
        Verify that the processed chapters made it into the final file.
        Compares final file chapters against ctx.chapters_xml (the processed version).
        """
        issues = 0

        # Load the processed chapters XML
        try:
            processed_xml_path = Path(self.ctx.chapters_xml)
            if not processed_xml_path.exists():
                self.log(f"[WARNING] Processed chapters XML file not found: {processed_xml_path}")
                return 1

            processed_xml_content = processed_xml_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log(f"[WARNING] Could not read processed chapters XML: {e}")
            return 1

        if not final_chapters_xml:
            self.log("[WARNING] Chapters were processed but are MISSING from the final file!")
            return 1

        # Compare processed vs final
        try:
            parser = ET.XMLParser(remove_blank_text=True, recover=True)

            processed_xml_content = processed_xml_content.lstrip('\ufeff')
            final_chapters_xml = final_chapters_xml.lstrip('\ufeff')

            processed_root = ET.fromstring(processed_xml_content.encode('utf-8'), parser)
            final_root = ET.fromstring(final_chapters_xml.encode('utf-8'), parser)

            processed_nsmap, processed_prefix = self._get_xpath_and_nsmap(processed_root)
            final_nsmap, final_prefix = self._get_xpath_and_nsmap(final_root)

            processed_atoms = processed_root.xpath(f'//{processed_prefix}ChapterAtom', namespaces=processed_nsmap)
            final_atoms = final_root.xpath(f'//{final_prefix}ChapterAtom', namespaces=final_nsmap)

            # Check 1: Count must match
            if len(processed_atoms) != len(final_atoms):
                self.log(f"[WARNING] Chapter count mismatch! Processed: {len(processed_atoms)}, Final: {len(final_atoms)}")
                return 1

            self.log(f"  ✓ Chapter count: {len(final_atoms)} chapters")

            # Check 2: Verify timestamps match (processed chapters should have been applied)
            issues += self._compare_timestamps(processed_atoms, final_atoms, processed_prefix, final_prefix, processed_nsmap, final_nsmap)

            # Check 3: If renaming was enabled, verify it was applied
            if self.ctx.settings_dict.get('rename_chapters', False):
                issues += self._verify_rename_applied(final_atoms, final_prefix, final_nsmap)

            # Check 4: Basic sanity checks
            issues += self._check_for_duplicates(final_atoms, final_prefix, final_nsmap)
            issues += self._check_timestamp_sanity(final_atoms, final_prefix, final_nsmap)

            if issues == 0:
                self.log(f"✅ Processed chapters correctly merged ({len(final_atoms)} chapter(s) verified).")

        except Exception as e:
            self.log(f"[WARNING] Could not verify processed chapters: {e}")
            issues += 1

        return issues

    def _verify_unprocessed_chapters(self, source_xml: Optional[str], final_xml: Optional[str],
                                     source_has_chapters: bool, final_has_chapters: bool) -> int:
        """
        Verify chapters when processing was NOT enabled.
        Final should match source exactly.
        """
        issues = 0

        if not source_has_chapters and not final_has_chapters:
            self.log("✅ No chapters in source or final file (as expected).")
            return 0

        if not source_has_chapters and final_has_chapters:
            chapter_count = self._count_chapters(final_xml)
            self.log(f"[INFO] Final file has {chapter_count} chapter(s) (none in source).")
            return 0

        if source_has_chapters and not final_has_chapters:
            self.log("[WARNING] Source file had chapters but they are MISSING from the final file!")
            return 1

        # Both have chapters - verify they match
        try:
            source_count = self._count_chapters(source_xml)
            final_count = self._count_chapters(final_xml)

            if source_count != final_count:
                self.log(f"[WARNING] Chapter count mismatch! Source: {source_count}, Final: {final_count}")
                issues += 1
            else:
                self.log(f"✅ Chapters preserved successfully ({final_count} chapter(s) found).")
        except Exception as e:
            self.log(f"[WARNING] Could not verify chapter count: {e}")
            issues += 1

        return issues

    def _compare_timestamps(self, processed_atoms, final_atoms, proc_prefix: str, final_prefix: str,
                           proc_nsmap: dict, final_nsmap: dict) -> int:
        """
        Compare timestamps between processed and final chapters.
        They should match exactly if processing was applied correctly.
        """
        issues = 0

        for i, (proc_atom, final_atom) in enumerate(zip(processed_atoms, final_atoms), 1):
            # Compare start times
            proc_start = proc_atom.find(f'{proc_prefix}ChapterTimeStart', namespaces=proc_nsmap)
            final_start = final_atom.find(f'{final_prefix}ChapterTimeStart', namespaces=final_nsmap)

            if proc_start is not None and final_start is not None:
                if proc_start.text != final_start.text:
                    self.log(f"[WARNING] Chapter {i} start time mismatch!")
                    self.log(f"          Processed: {proc_start.text}")
                    self.log(f"          Final:     {final_start.text}")
                    self.log(f"          → Processed chapters were not merged correctly!")
                    issues += 1

            # Compare end times
            proc_end = proc_atom.find(f'{proc_prefix}ChapterTimeEnd', namespaces=proc_nsmap)
            final_end = final_atom.find(f'{final_prefix}ChapterTimeEnd', namespaces=final_nsmap)

            if proc_end is not None and final_end is not None:
                if proc_end.text != final_end.text:
                    # End time mismatches are less critical, just log as info
                    self.log(f"[INFO] Chapter {i} end time differs (may be normalized differently)")

        if issues == 0:
            self.log(f"  ✓ All chapter timestamps match processed version")

        return issues

    def _verify_rename_applied(self, atoms, prefix: str, nsmap: dict) -> int:
        """Verify chapters were renamed to 'Chapter NN' format."""
        issues = 0
        expected_pattern = re.compile(r'^Chapter \d{2}$')

        for i, atom in enumerate(atoms, 1):
            name_node = atom.find(f'.//{prefix}ChapterString', namespaces=nsmap)
            if name_node is not None and name_node.text:
                actual_name = name_node.text
                if not expected_pattern.match(actual_name):
                    self.log(f"[WARNING] Chapter {i} was not renamed: '{actual_name}' (expected 'Chapter {i:02d}')")
                    self.log(f"          → Chapter renaming was enabled but not applied!")
                    issues += 1

        if issues == 0:
            self.log(f"  ✓ Chapter renaming applied correctly")

        return issues

    def _extract_chapters(self, file_path) -> Optional[str]:
        """Extract chapters XML from a file, return None if no chapters."""
        try:
            xml_content = self.runner.run(
                ['mkvextract', str(file_path), 'chapters', '-'],
                self.tool_paths
            )
            if xml_content and xml_content.strip() and 'No chapters found' not in xml_content:
                return xml_content
        except Exception as e:
            self.log(f"[WARNING] Could not extract chapters from {Path(file_path).name}: {e}")
        return None

    def _count_chapters(self, xml_content: str) -> int:
        """Count ChapterAtom elements in XML."""
        try:
            return len(re.findall(r'<ChapterAtom>', xml_content))
        except:
            return 0

    def _get_xpath_and_nsmap(self, root: ET.Element) -> tuple:
        """Detects if a namespace is used and returns the appropriate xpath prefix and nsmap."""
        if root.nsmap and None in root.nsmap:
            ns_uri = root.nsmap[None]
            return {'def': ns_uri}, 'def:'
        return None, ''

    def _check_for_duplicates(self, atoms, prefix: str, nsmap: dict) -> int:
        """Check for duplicate chapter start times."""
        issues = 0
        start_times = []

        for atom in atoms:
            st_el = atom.find(f'{prefix}ChapterTimeStart', namespaces=nsmap)
            if st_el is not None and st_el.text:
                start_times.append(st_el.text)

        if len(start_times) != len(set(start_times)):
            self.log("[WARNING] Found duplicate chapter start times!")
            issues += 1
        else:
            self.log("  ✓ No duplicate chapter timestamps")

        return issues

    def _check_timestamp_sanity(self, atoms, prefix: str, nsmap: dict) -> int:
        """Basic timestamp sanity checks."""
        issues = 0
        prev_start = None

        for i, atom in enumerate(atoms, 1):
            st_el = atom.find(f'{prefix}ChapterTimeStart', namespaces=nsmap)
            en_el = atom.find(f'{prefix}ChapterTimeEnd', namespaces=nsmap)

            if st_el is not None and st_el.text:
                curr_start = st_el.text

                # Check timestamps are increasing
                if prev_start and curr_start <= prev_start:
                    self.log(f"[WARNING] Chapter {i} timestamp is not in ascending order!")
                    issues += 1

                # Check start < end
                if en_el is not None and en_el.text:
                    if curr_start >= en_el.text:
                        self.log(f"[WARNING] Chapter {i} start time >= end time!")
                        issues += 1

                prev_start = curr_start

        if issues == 0:
            self.log("  ✓ Chapter timestamps are in correct order")

        return issues
