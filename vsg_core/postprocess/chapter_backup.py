# vsg_core/postprocess/chapter_backup.py
from pathlib import Path

from lxml import etree as ET

from ..io.runner import CommandRunner


def extract_chapters_xml(
    mkv_path: Path, runner: CommandRunner, tool_paths: dict
) -> str | None:
    """Extract chapters XML from MKV file, return XML content or None if no chapters."""
    try:
        xml_content = runner.run(
            ["mkvextract", str(mkv_path), "chapters", "-"], tool_paths
        )
        if (
            xml_content
            and xml_content.strip()
            and "No chapters found" not in xml_content
        ):
            return xml_content
        return None
    except Exception as e:
        runner._log_message(f"[WARNING] Failed to extract chapters: {e}")
        return None


def merge_chapter_languages(
    original_xml: str, normalized_xml: str, runner: CommandRunner
) -> str:
    """Update timestamps in original chapters XML using timestamps from normalized XML."""
    try:
        # Clean the XML content first
        if original_xml.startswith("\ufeff"):
            original_xml = original_xml[1:]
        if normalized_xml.startswith("\ufeff"):
            normalized_xml = normalized_xml[1:]

        # Parse both XML documents
        parser = ET.XMLParser(remove_blank_text=True, recover=True)
        original_root = ET.fromstring(original_xml.encode("utf-8"), parser)
        normalized_root = ET.fromstring(normalized_xml.encode("utf-8"), parser)

        # Extract timestamps from normalized chapters (by order)
        normalized_timestamps = []
        for atom in normalized_root.xpath("//ChapterAtom"):
            start_elem = atom.find("ChapterTimeStart")
            end_elem = atom.find("ChapterTimeEnd")
            start_time = (
                start_elem.text if start_elem is not None and start_elem.text else None
            )
            end_time = end_elem.text if end_elem is not None and end_elem.text else None
            normalized_timestamps.append((start_time, end_time))

        # Update timestamps in original chapters (keeping all other data intact)
        original_atoms = original_root.xpath("//ChapterAtom")
        for i, atom in enumerate(original_atoms):
            if i < len(normalized_timestamps):
                new_start, new_end = normalized_timestamps[i]

                # Update ChapterTimeStart
                if new_start:
                    start_elem = atom.find("ChapterTimeStart")
                    if start_elem is not None:
                        start_elem.text = new_start

                # Update ChapterTimeEnd
                if new_end:
                    end_elem = atom.find("ChapterTimeEnd")
                    if end_elem is not None:
                        end_elem.text = new_end

        # Generate XML with proper declaration and DOCTYPE
        xml_content = ET.tostring(original_root, encoding="unicode", pretty_print=True)

        # Add the XML declaration and DOCTYPE comment that mkvpropedit expects
        final_xml = '<?xml version="1.0"?>\n'
        final_xml += '<!-- <!DOCTYPE Chapters SYSTEM "matroskachapters.dtd"> -->\n'
        final_xml += xml_content

        return final_xml

    except Exception as e:
        runner._log_message(
            f"[WARNING] Failed to update chapter timestamps: {e}. Using original chapters as-is."
        )
        return original_xml


def inject_chapters(
    mkv_path: Path, chapters_xml: str, runner: CommandRunner, tool_paths: dict
):
    """Inject chapters XML back into MKV file."""
    try:
        temp_chapters_path = mkv_path.parent / "restored_chapters.xml"
        temp_chapters_path.write_text(chapters_xml, encoding="utf-8")

        # Debug: Log the first few lines of the XML to see what we're generating
        xml_lines = chapters_xml.split("\n")[:5]
        runner._log_message(f"[DEBUG] Generated XML preview: {xml_lines}")

        # Use mkvpropedit to inject chapters
        cmd = ["mkvpropedit", str(mkv_path), "--chapters", str(temp_chapters_path)]
        result = runner.run(cmd, tool_paths)

        # Clean up temp file
        temp_chapters_path.unlink(missing_ok=True)

        if result is not None:
            runner._log_message("[Finalize] Chapter languages restored successfully.")
        else:
            runner._log_message("[WARNING] Failed to restore chapter languages.")

    except Exception as e:
        runner._log_message(f"[WARNING] Failed to inject chapters: {e}")
