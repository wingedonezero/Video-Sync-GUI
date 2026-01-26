//! Chapter XML parsing and serialization.
//!
//! Handles Matroska chapter XML format (as used by mkvextract/mkvmerge).

use std::path::Path;

use super::types::{
    parse_timestamp_ns, ChapterData, ChapterEntry, ChapterError, ChapterName, ChapterResult,
};

/// Parse chapter XML from a file.
pub fn parse_chapter_file(path: &Path) -> ChapterResult<ChapterData> {
    let content = std::fs::read_to_string(path)?;
    parse_chapter_xml(&content)
}

/// Parse chapter XML string into ChapterData.
///
/// Handles the Matroska chapter XML format:
/// ```xml
/// <?xml version="1.0"?>
/// <Chapters>
///   <EditionEntry>
///     <EditionFlagDefault>1</EditionFlagDefault>
///     <EditionUID>12345</EditionUID>
///     <ChapterAtom>
///       <ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>
///       <ChapterTimeEnd>00:05:00.000000000</ChapterTimeEnd>
///       <ChapterDisplay>
///         <ChapterString>Chapter 1</ChapterString>
///         <ChapterLanguage>eng</ChapterLanguage>
///       </ChapterDisplay>
///     </ChapterAtom>
///   </EditionEntry>
/// </Chapters>
/// ```
pub fn parse_chapter_xml(xml: &str) -> ChapterResult<ChapterData> {
    let doc = roxmltree::Document::parse(xml)
        .map_err(|e| ChapterError::MalformedXml(format!("XML parse error: {}", e)))?;

    let root = doc.root_element();
    if root.tag_name().name() != "Chapters" {
        return Err(ChapterError::MalformedXml(
            "Root element must be <Chapters>".to_string(),
        ));
    }

    let mut data = ChapterData::new();

    // Find EditionEntry (we take the first one)
    if let Some(edition) = root
        .children()
        .find(|n| n.is_element() && n.tag_name().name() == "EditionEntry")
    {
        // Parse edition attributes
        for child in edition.children().filter(|n| n.is_element()) {
            match child.tag_name().name() {
                "EditionUID" => {
                    if let Some(text) = child.text() {
                        data.edition_uid = text.trim().parse().ok();
                    }
                }
                "EditionFlagDefault" => {
                    if let Some(text) = child.text() {
                        data.edition_default = text.trim() == "1";
                    }
                }
                "EditionFlagHidden" => {
                    if let Some(text) = child.text() {
                        data.edition_hidden = text.trim() == "1";
                    }
                }
                "ChapterAtom" => {
                    if let Some(chapter) = parse_chapter_atom(&child) {
                        data.add_chapter(chapter);
                    }
                }
                _ => {}
            }
        }
    }

    // Sort chapters by start time
    data.sort_by_time();

    Ok(data)
}

/// Parse a single ChapterAtom element.
fn parse_chapter_atom(atom: &roxmltree::Node) -> Option<ChapterEntry> {
    let mut start_ns: Option<u64> = None;
    let mut end_ns: Option<u64> = None;
    let mut names: Vec<ChapterName> = Vec::new();
    let mut uid: Option<u64> = None;
    let mut hidden = false;
    let mut enabled = true;

    for child in atom.children().filter(|n| n.is_element()) {
        match child.tag_name().name() {
            "ChapterTimeStart" => {
                if let Some(text) = child.text() {
                    start_ns = parse_timestamp_ns(text.trim());
                }
            }
            "ChapterTimeEnd" => {
                if let Some(text) = child.text() {
                    end_ns = parse_timestamp_ns(text.trim());
                }
            }
            "ChapterUID" => {
                if let Some(text) = child.text() {
                    uid = text.trim().parse().ok();
                }
            }
            "ChapterFlagHidden" => {
                if let Some(text) = child.text() {
                    hidden = text.trim() == "1";
                }
            }
            "ChapterFlagEnabled" => {
                if let Some(text) = child.text() {
                    enabled = text.trim() == "1";
                }
            }
            "ChapterDisplay" => {
                if let Some(name) = parse_chapter_display(&child) {
                    names.push(name);
                }
            }
            _ => {}
        }
    }

    // ChapterTimeStart is required
    let start_ns = start_ns?;

    Some(ChapterEntry {
        start_ns,
        end_ns,
        names,
        uid,
        hidden,
        enabled,
    })
}

/// Parse a ChapterDisplay element.
fn parse_chapter_display(display: &roxmltree::Node) -> Option<ChapterName> {
    let mut name: Option<String> = None;
    let mut language = "und".to_string(); // Default to undefined

    for child in display.children().filter(|n| n.is_element()) {
        match child.tag_name().name() {
            "ChapterString" => {
                name = child.text().map(|s| s.to_string());
            }
            "ChapterLanguage" | "ChapLanguageIETF" => {
                if let Some(text) = child.text() {
                    language = text.trim().to_string();
                }
            }
            _ => {}
        }
    }

    name.map(|n| ChapterName { name: n, language })
}

/// Serialize ChapterData to Matroska XML format.
pub fn serialize_chapter_xml(data: &ChapterData) -> String {
    let mut xml = String::new();
    xml.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    // Note: We skip the DOCTYPE declaration as mkvmerge doesn't require it
    xml.push_str("<Chapters>\n");
    xml.push_str("  <EditionEntry>\n");

    // Edition flags
    if data.edition_default {
        xml.push_str("    <EditionFlagDefault>1</EditionFlagDefault>\n");
    }
    if data.edition_hidden {
        xml.push_str("    <EditionFlagHidden>1</EditionFlagHidden>\n");
    }
    if let Some(uid) = data.edition_uid {
        xml.push_str(&format!("    <EditionUID>{}</EditionUID>\n", uid));
    }

    // Chapter atoms
    for chapter in &data.chapters {
        xml.push_str("    <ChapterAtom>\n");

        // Timing
        xml.push_str(&format!(
            "      <ChapterTimeStart>{}</ChapterTimeStart>\n",
            chapter.format_start_time()
        ));
        if let Some(end) = chapter.format_end_time() {
            xml.push_str(&format!("      <ChapterTimeEnd>{}</ChapterTimeEnd>\n", end));
        }

        // UID
        if let Some(uid) = chapter.uid {
            xml.push_str(&format!("      <ChapterUID>{}</ChapterUID>\n", uid));
        }

        // Flags
        if chapter.hidden {
            xml.push_str("      <ChapterFlagHidden>1</ChapterFlagHidden>\n");
        }
        if !chapter.enabled {
            xml.push_str("      <ChapterFlagEnabled>0</ChapterFlagEnabled>\n");
        }

        // Display names
        for name in &chapter.names {
            xml.push_str("      <ChapterDisplay>\n");
            xml.push_str(&format!(
                "        <ChapterString>{}</ChapterString>\n",
                escape_xml(&name.name)
            ));
            xml.push_str(&format!(
                "        <ChapterLanguage>{}</ChapterLanguage>\n",
                name.language
            ));
            xml.push_str("      </ChapterDisplay>\n");
        }

        xml.push_str("    </ChapterAtom>\n");
    }

    xml.push_str("  </EditionEntry>\n");
    xml.push_str("</Chapters>\n");

    xml
}

/// Write chapter data to a file.
pub fn write_chapter_file(data: &ChapterData, path: &Path) -> ChapterResult<()> {
    let xml = serialize_chapter_xml(data);
    std::fs::write(path, xml)?;
    Ok(())
}

/// Escape special XML characters.
fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_XML: &str = r#"<?xml version="1.0"?>
<Chapters>
  <EditionEntry>
    <EditionFlagDefault>1</EditionFlagDefault>
    <EditionUID>12345</EditionUID>
    <ChapterAtom>
      <ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>
      <ChapterTimeEnd>00:05:00.000000000</ChapterTimeEnd>
      <ChapterUID>1</ChapterUID>
      <ChapterDisplay>
        <ChapterString>Chapter 1</ChapterString>
        <ChapterLanguage>eng</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
    <ChapterAtom>
      <ChapterTimeStart>00:05:00.000000000</ChapterTimeStart>
      <ChapterUID>2</ChapterUID>
      <ChapterDisplay>
        <ChapterString>Chapter 2</ChapterString>
        <ChapterLanguage>eng</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
  </EditionEntry>
</Chapters>"#;

    #[test]
    fn parse_sample_xml() {
        let data = parse_chapter_xml(SAMPLE_XML).unwrap();
        assert_eq!(data.len(), 2);
        assert!(data.edition_default);
        assert_eq!(data.edition_uid, Some(12345));

        let ch1 = &data.chapters[0];
        assert_eq!(ch1.start_ns, 0);
        assert_eq!(ch1.end_ns, Some(300_000_000_000)); // 5 minutes
        assert_eq!(ch1.display_name(), Some("Chapter 1"));

        let ch2 = &data.chapters[1];
        assert_eq!(ch2.start_ns, 300_000_000_000);
        assert_eq!(ch2.display_name(), Some("Chapter 2"));
    }

    #[test]
    fn roundtrip_serialization() {
        let data = parse_chapter_xml(SAMPLE_XML).unwrap();
        let serialized = serialize_chapter_xml(&data);
        let reparsed = parse_chapter_xml(&serialized).unwrap();

        assert_eq!(data.len(), reparsed.len());
        assert_eq!(data.edition_default, reparsed.edition_default);
        assert_eq!(data.chapters[0].start_ns, reparsed.chapters[0].start_ns);
        assert_eq!(
            data.chapters[0].display_name(),
            reparsed.chapters[0].display_name()
        );
    }

    #[test]
    fn escape_special_characters() {
        let mut data = ChapterData::new();
        data.add_chapter(
            ChapterEntry::new(0).with_name("Test & <Chapter>", "eng"),
        );

        let xml = serialize_chapter_xml(&data);
        assert!(xml.contains("Test &amp; &lt;Chapter&gt;"));
    }
}
