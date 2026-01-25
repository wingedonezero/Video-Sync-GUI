//! Chapter extraction from MKV files.
//!
//! Uses mkvextract to extract chapter XML from Matroska containers.

use std::path::Path;
use std::process::Command;

use super::types::{
    Chapter, ChapterDisplay, ChapterError, ChapterLanguage, ChapterList,
    parse_timestamp,
};

/// Extract chapters from an MKV file.
///
/// # Arguments
///
/// * `source_path` - Path to the MKV file
///
/// # Returns
///
/// `ChapterList` containing all chapters, or `ChapterError::NoChapters` if none found.
pub fn extract_chapters(source_path: &Path) -> Result<ChapterList, ChapterError> {
    // Run mkvextract to get chapter XML
    let output = Command::new("mkvextract")
        .arg(source_path)
        .arg("chapters")
        .arg("-") // Output to stdout
        .output()
        .map_err(|e| ChapterError::ToolExecutionFailed {
            tool: "mkvextract".to_string(),
            message: format!("Failed to execute: {}", e),
        })?;

    if !output.status.success() {
        // mkvextract returns exit code 1 for warnings but may still output data
        if output.status.code() != Some(1) || output.stdout.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(ChapterError::ToolExecutionFailed {
                tool: "mkvextract".to_string(),
                message: format!("Exit code {}: {}", output.status, stderr),
            });
        }
    }

    let xml_content = String::from_utf8_lossy(&output.stdout);
    let xml_content = xml_content.trim();

    if xml_content.is_empty() {
        return Err(ChapterError::NoChapters);
    }

    // Remove BOM if present
    let xml_content = xml_content.strip_prefix('\u{feff}').unwrap_or(xml_content);

    parse_chapter_xml(xml_content)
}

/// Parse Matroska chapter XML into a ChapterList.
///
/// This handles both namespaced and non-namespaced XML formats.
pub fn parse_chapter_xml(xml: &str) -> Result<ChapterList, ChapterError> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(true);

    let mut chapters = Vec::new();
    let mut current_chapter: Option<ChapterBuilder> = None;
    let mut current_display: Option<DisplayBuilder> = None;
    let mut in_chapter_atom = false;
    let mut in_chapter_display = false;
    let mut current_element = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => {
                let name = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                current_element = name.clone();

                match name.as_str() {
                    "ChapterAtom" => {
                        in_chapter_atom = true;
                        current_chapter = Some(ChapterBuilder::new());
                    }
                    "ChapterDisplay" if in_chapter_atom => {
                        in_chapter_display = true;
                        current_display = Some(DisplayBuilder::new());
                    }
                    _ => {}
                }
            }
            Ok(Event::End(e)) => {
                let name = String::from_utf8_lossy(e.local_name().as_ref()).to_string();

                match name.as_str() {
                    "ChapterAtom" => {
                        if let Some(builder) = current_chapter.take() {
                            if let Some(chapter) = builder.build() {
                                chapters.push(chapter);
                            }
                        }
                        in_chapter_atom = false;
                    }
                    "ChapterDisplay" => {
                        if let (Some(ref mut chapter), Some(display)) =
                            (&mut current_chapter, current_display.take())
                        {
                            if let Some(d) = display.build() {
                                chapter.displays.push(d);
                            }
                        }
                        in_chapter_display = false;
                    }
                    _ => {}
                }
                current_element.clear();
            }
            Ok(Event::Text(e)) => {
                let text = e.unescape().unwrap_or_default().to_string();

                if in_chapter_display {
                    if let Some(ref mut display) = current_display {
                        match current_element.as_str() {
                            "ChapterString" => display.name = Some(text),
                            "ChapterLanguage" => display.language = Some(text),
                            "ChapLanguageIETF" => display.ietf = Some(text),
                            _ => {}
                        }
                    }
                } else if in_chapter_atom {
                    if let Some(ref mut chapter) = current_chapter {
                        match current_element.as_str() {
                            "ChapterUID" => {
                                chapter.uid = text.parse().ok();
                            }
                            "ChapterTimeStart" => {
                                chapter.start_ns = parse_timestamp(&text).ok();
                            }
                            "ChapterTimeEnd" => {
                                chapter.end_ns = parse_timestamp(&text).ok();
                            }
                            "ChapterFlagHidden" => {
                                chapter.hidden = text == "1";
                            }
                            "ChapterFlagEnabled" => {
                                chapter.enabled = text != "0";
                            }
                            _ => {}
                        }
                    }
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => {
                return Err(ChapterError::ParseError(format!(
                    "XML parse error at position {}: {}",
                    reader.buffer_position(),
                    e
                )));
            }
            _ => {}
        }
    }

    if chapters.is_empty() {
        return Err(ChapterError::NoChapters);
    }

    Ok(ChapterList::from_chapters(chapters))
}

/// Builder for constructing a Chapter during parsing.
#[derive(Default)]
struct ChapterBuilder {
    uid: Option<u64>,
    start_ns: Option<i64>,
    end_ns: Option<i64>,
    displays: Vec<ChapterDisplay>,
    hidden: bool,
    enabled: bool,
}

impl ChapterBuilder {
    fn new() -> Self {
        Self {
            enabled: true,
            ..Default::default()
        }
    }

    fn build(self) -> Option<Chapter> {
        // Must have a start time
        let start_ns = self.start_ns?;

        Some(Chapter {
            uid: self.uid,
            start_ns,
            end_ns: self.end_ns,
            displays: if self.displays.is_empty() {
                vec![ChapterDisplay::with_name("Unnamed Chapter")]
            } else {
                self.displays
            },
            hidden: self.hidden,
            enabled: self.enabled,
        })
    }
}

/// Builder for constructing a ChapterDisplay during parsing.
#[derive(Default)]
struct DisplayBuilder {
    name: Option<String>,
    language: Option<String>,
    ietf: Option<String>,
}

impl DisplayBuilder {
    fn new() -> Self {
        Self::default()
    }

    fn build(self) -> Option<ChapterDisplay> {
        let name = self.name.unwrap_or_else(|| "Unnamed".to_string());
        let language = if let Some(lang) = self.language {
            if let Some(ietf) = self.ietf {
                ChapterLanguage::with_ietf(lang, ietf)
            } else {
                ChapterLanguage::new(lang)
            }
        } else {
            ChapterLanguage::undefined()
        };

        Some(ChapterDisplay { name, language })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_chapters() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE Chapters SYSTEM "matroskachapters.dtd">
<Chapters>
  <EditionEntry>
    <ChapterAtom>
      <ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>
      <ChapterTimeEnd>00:05:00.000000000</ChapterTimeEnd>
      <ChapterDisplay>
        <ChapterString>Opening</ChapterString>
        <ChapterLanguage>eng</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
    <ChapterAtom>
      <ChapterTimeStart>00:05:00.000000000</ChapterTimeStart>
      <ChapterDisplay>
        <ChapterString>Part A</ChapterString>
        <ChapterLanguage>eng</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
  </EditionEntry>
</Chapters>"#;

        let result = parse_chapter_xml(xml).unwrap();
        assert_eq!(result.len(), 2);
        assert_eq!(result.chapters[0].name(), "Opening");
        assert_eq!(result.chapters[0].start_ns, 0);
        assert_eq!(result.chapters[0].end_ns, Some(300_000_000_000));
        assert_eq!(result.chapters[1].name(), "Part A");
        assert_eq!(result.chapters[1].start_ns, 300_000_000_000);
    }

    #[test]
    fn test_parse_no_chapters() {
        let xml = r#"<?xml version="1.0"?>
<Chapters>
  <EditionEntry>
  </EditionEntry>
</Chapters>"#;

        let result = parse_chapter_xml(xml);
        assert!(matches!(result, Err(ChapterError::NoChapters)));
    }
}
