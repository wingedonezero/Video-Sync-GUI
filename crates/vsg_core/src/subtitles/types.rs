//! Core subtitle types.
//!
//! All timing values are stored as `f64` milliseconds for sub-millisecond precision.
//! Rounding to centiseconds (ASS) or milliseconds (SRT) happens only at write time.

use std::path::PathBuf;

/// Supported subtitle formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SubtitleFormat {
    /// Advanced SubStation Alpha (.ass, .ssa)
    #[default]
    Ass,
    /// SubRip (.srt)
    Srt,
    /// WebVTT (.vtt)
    WebVtt,
}

impl SubtitleFormat {
    /// Detect format from file extension.
    pub fn from_extension(path: &std::path::Path) -> Option<Self> {
        let ext = path.extension()?.to_str()?.to_lowercase();
        match ext.as_str() {
            "ass" | "ssa" => Some(Self::Ass),
            "srt" => Some(Self::Srt),
            "vtt" => Some(Self::WebVtt),
            _ => None,
        }
    }

    /// Get the typical file extension for this format.
    pub fn extension(&self) -> &'static str {
        match self {
            Self::Ass => "ass",
            Self::Srt => "srt",
            Self::WebVtt => "vtt",
        }
    }
}

/// Main subtitle data container.
///
/// Holds all subtitle events, styles, and metadata.
/// Format-agnostic internally - format only matters at parse/write time.
#[derive(Debug, Clone, Default)]
pub struct SubtitleData {
    /// Subtitle events (dialogue lines).
    pub events: Vec<SubtitleEvent>,
    /// ASS styles (empty for SRT).
    pub styles: Vec<SubtitleStyle>,
    /// Document-level metadata.
    pub metadata: SubtitleMetadata,
    /// Original format (for round-trip preservation).
    pub format: SubtitleFormat,
    /// Source file path (if loaded from file).
    pub source_path: Option<PathBuf>,
}

impl SubtitleData {
    /// Create empty subtitle data.
    pub fn new() -> Self {
        Self::default()
    }

    /// Create with specified format.
    pub fn with_format(format: SubtitleFormat) -> Self {
        Self {
            format,
            ..Default::default()
        }
    }

    /// Number of dialogue events (excluding comments).
    pub fn dialogue_count(&self) -> usize {
        self.events.iter().filter(|e| !e.is_comment).count()
    }

    /// Total duration in milliseconds (end of last event).
    pub fn duration_ms(&self) -> f64 {
        self.events
            .iter()
            .map(|e| e.end_ms)
            .fold(0.0, f64::max)
    }

    /// Get style by name.
    pub fn get_style(&self, name: &str) -> Option<&SubtitleStyle> {
        self.styles.iter().find(|s| s.name == name)
    }

    /// Get mutable style by name.
    pub fn get_style_mut(&mut self, name: &str) -> Option<&mut SubtitleStyle> {
        self.styles.iter_mut().find(|s| s.name == name)
    }

    /// Add or update a style.
    pub fn set_style(&mut self, style: SubtitleStyle) {
        if let Some(existing) = self.get_style_mut(&style.name) {
            *existing = style;
        } else {
            self.styles.push(style);
        }
    }

    /// Shift all events by a time offset.
    ///
    /// Positive offset = move forward in time.
    /// Negative offset = move backward in time.
    /// Times are clamped to 0 (no negative times).
    pub fn shift_all(&mut self, offset_ms: f64) {
        for event in &mut self.events {
            event.start_ms = (event.start_ms + offset_ms).max(0.0);
            event.end_ms = (event.end_ms + offset_ms).max(0.0);
        }
    }

    /// Sort events by start time.
    pub fn sort_by_time(&mut self) {
        self.events.sort_by(|a, b| {
            a.start_ms
                .partial_cmp(&b.start_ms)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    }
}

/// A single subtitle event (dialogue line or comment).
#[derive(Debug, Clone)]
pub struct SubtitleEvent {
    /// Start time in milliseconds (f64 for precision).
    pub start_ms: f64,
    /// End time in milliseconds (f64 for precision).
    pub end_ms: f64,
    /// Text content (may contain formatting tags).
    pub text: String,
    /// Style name (ASS only, None for SRT).
    pub style: Option<String>,
    /// Layer number (ASS only, 0 for SRT).
    pub layer: i32,
    /// Whether this is a comment line.
    pub is_comment: bool,
    /// Actor/speaker name (ASS only).
    pub actor: Option<String>,
    /// Margin left override (ASS only).
    pub margin_l: Option<i32>,
    /// Margin right override (ASS only).
    pub margin_r: Option<i32>,
    /// Margin vertical override (ASS only).
    pub margin_v: Option<i32>,
    /// Effect field (ASS only).
    pub effect: Option<String>,
    /// Per-event sync tracking data.
    pub sync_data: Option<SyncEventData>,
}

impl Default for SubtitleEvent {
    fn default() -> Self {
        Self {
            start_ms: 0.0,
            end_ms: 0.0,
            text: String::new(),
            style: None,
            layer: 0,
            is_comment: false,
            actor: None,
            margin_l: None,
            margin_r: None,
            margin_v: None,
            effect: None,
            sync_data: None,
        }
    }
}

impl SubtitleEvent {
    /// Create a new dialogue event.
    pub fn new(start_ms: f64, end_ms: f64, text: impl Into<String>) -> Self {
        Self {
            start_ms,
            end_ms,
            text: text.into(),
            ..Default::default()
        }
    }

    /// Create with style.
    pub fn with_style(mut self, style: impl Into<String>) -> Self {
        self.style = Some(style.into());
        self
    }

    /// Duration in milliseconds.
    pub fn duration_ms(&self) -> f64 {
        self.end_ms - self.start_ms
    }

    /// Shift this event by an offset.
    pub fn shift(&mut self, offset_ms: f64) {
        self.start_ms = (self.start_ms + offset_ms).max(0.0);
        self.end_ms = (self.end_ms + offset_ms).max(0.0);
    }
}

/// Per-event sync tracking data.
///
/// Records what adjustments were made during sync for debugging/auditing.
#[derive(Debug, Clone, Default)]
pub struct SyncEventData {
    /// Original start time before sync.
    pub original_start_ms: f64,
    /// Original end time before sync.
    pub original_end_ms: f64,
    /// Start time adjustment applied.
    pub start_adjustment_ms: f64,
    /// End time adjustment applied.
    pub end_adjustment_ms: f64,
    /// Whether event was snapped to frame boundary.
    pub snapped_to_frame: bool,
    /// Frame number snapped to (if applicable).
    pub snapped_frame: Option<u32>,
}

/// ASS style definition.
///
/// Contains all 23 fields from the ASS specification.
#[derive(Debug, Clone)]
pub struct SubtitleStyle {
    /// Style name (required).
    pub name: String,
    /// Font name.
    pub fontname: String,
    /// Font size.
    pub fontsize: f64,
    /// Primary color (ABGR format as u32, or hex string).
    pub primary_color: AssColor,
    /// Secondary color (ABGR).
    pub secondary_color: AssColor,
    /// Outline color (ABGR).
    pub outline_color: AssColor,
    /// Back/shadow color (ABGR).
    pub back_color: AssColor,
    /// Bold (-1 = true, 0 = false).
    pub bold: bool,
    /// Italic (-1 = true, 0 = false).
    pub italic: bool,
    /// Underline (-1 = true, 0 = false).
    pub underline: bool,
    /// Strikeout (-1 = true, 0 = false).
    pub strikeout: bool,
    /// Horizontal scale (100 = normal).
    pub scale_x: f64,
    /// Vertical scale (100 = normal).
    pub scale_y: f64,
    /// Spacing between characters.
    pub spacing: f64,
    /// Rotation angle in degrees.
    pub angle: f64,
    /// Border style (1 = outline + shadow, 3 = opaque box).
    pub border_style: i32,
    /// Outline width.
    pub outline: f64,
    /// Shadow depth.
    pub shadow: f64,
    /// Alignment (numpad style: 1-9).
    pub alignment: i32,
    /// Left margin.
    pub margin_l: i32,
    /// Right margin.
    pub margin_r: i32,
    /// Vertical margin.
    pub margin_v: i32,
    /// Encoding (0 = ANSI, 1 = default, etc.).
    pub encoding: i32,
}

impl Default for SubtitleStyle {
    fn default() -> Self {
        Self {
            name: "Default".to_string(),
            fontname: "Arial".to_string(),
            fontsize: 20.0,
            primary_color: AssColor::from_rgb(255, 255, 255), // White
            secondary_color: AssColor::from_rgb(255, 0, 0),   // Red
            outline_color: AssColor::from_rgb(0, 0, 0),       // Black
            back_color: AssColor::from_rgb(0, 0, 0),          // Black
            bold: false,
            italic: false,
            underline: false,
            strikeout: false,
            scale_x: 100.0,
            scale_y: 100.0,
            spacing: 0.0,
            angle: 0.0,
            border_style: 1,
            outline: 2.0,
            shadow: 2.0,
            alignment: 2, // Bottom center
            margin_l: 10,
            margin_r: 10,
            margin_v: 10,
            encoding: 1,
        }
    }
}

impl SubtitleStyle {
    /// Create a new style with the given name.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            ..Default::default()
        }
    }
}

/// ASS color in ABGR format.
///
/// ASS uses &HAABBGGRR format (alpha, blue, green, red).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AssColor {
    /// Red component (0-255).
    pub r: u8,
    /// Green component (0-255).
    pub g: u8,
    /// Blue component (0-255).
    pub b: u8,
    /// Alpha component (0-255, 0 = opaque, 255 = transparent).
    pub a: u8,
}

impl Default for AssColor {
    fn default() -> Self {
        Self::from_rgb(255, 255, 255) // White, opaque
    }
}

impl AssColor {
    /// Create from RGB values (alpha = 0, opaque).
    pub fn from_rgb(r: u8, g: u8, b: u8) -> Self {
        Self { r, g, b, a: 0 }
    }

    /// Create from RGBA values.
    pub fn from_rgba(r: u8, g: u8, b: u8, a: u8) -> Self {
        Self { r, g, b, a }
    }

    /// Parse from ASS color string (&HAABBGGRR or &HBBGGRR).
    pub fn from_ass_string(s: &str) -> Option<Self> {
        let s = s.trim().trim_start_matches('&').trim_start_matches('H');
        let value = u32::from_str_radix(s, 16).ok()?;

        if s.len() <= 6 {
            // &HBBGGRR format (no alpha)
            Some(Self {
                r: (value & 0xFF) as u8,
                g: ((value >> 8) & 0xFF) as u8,
                b: ((value >> 16) & 0xFF) as u8,
                a: 0,
            })
        } else {
            // &HAABBGGRR format
            Some(Self {
                r: (value & 0xFF) as u8,
                g: ((value >> 8) & 0xFF) as u8,
                b: ((value >> 16) & 0xFF) as u8,
                a: ((value >> 24) & 0xFF) as u8,
            })
        }
    }

    /// Convert to ASS color string (&HAABBGGRR).
    pub fn to_ass_string(&self) -> String {
        format!(
            "&H{:02X}{:02X}{:02X}{:02X}",
            self.a, self.b, self.g, self.r
        )
    }
}

/// Document-level metadata.
#[derive(Debug, Clone, Default)]
pub struct SubtitleMetadata {
    /// Title from [Script Info].
    pub title: Option<String>,
    /// Original script author.
    pub original_script: Option<String>,
    /// Translation author.
    pub translation: Option<String>,
    /// Timing author.
    pub timing: Option<String>,
    /// Play resolution X (ASS).
    pub play_res_x: Option<i32>,
    /// Play resolution Y (ASS).
    pub play_res_y: Option<i32>,
    /// Script type (e.g., "v4.00+").
    pub script_type: Option<String>,
    /// Wrap style (ASS).
    pub wrap_style: Option<i32>,
    /// Scaled border and shadow (ASS).
    pub scaled_border_and_shadow: Option<bool>,
    /// YCbCr matrix (ASS 4.0+).
    pub ycbcr_matrix: Option<String>,
    /// Additional custom fields.
    pub custom: std::collections::HashMap<String, String>,
}

/// Rounding mode for time values when writing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RoundingMode {
    /// Round down (floor) - most conservative, may cut off start.
    Floor,
    /// Round to nearest - balanced approach.
    #[default]
    Round,
    /// Round up (ceil) - ensures subtitle appears, may show early.
    Ceil,
}

impl RoundingMode {
    /// Apply rounding to a millisecond value.
    ///
    /// For ASS: rounds to centiseconds (10ms precision).
    /// For SRT: rounds to milliseconds (already ms).
    pub fn apply_ass(&self, ms: f64) -> f64 {
        let cs = ms / 10.0; // Convert to centiseconds
        let rounded = match self {
            Self::Floor => cs.floor(),
            Self::Round => cs.round(),
            Self::Ceil => cs.ceil(),
        };
        rounded * 10.0 // Back to milliseconds
    }

    /// Apply rounding for SRT (millisecond precision).
    pub fn apply_srt(&self, ms: f64) -> f64 {
        match self {
            Self::Floor => ms.floor(),
            Self::Round => ms.round(),
            Self::Ceil => ms.ceil(),
        }
    }
}

/// Options for writing subtitle files.
#[derive(Debug, Clone)]
pub struct WriteOptions {
    /// Rounding mode for time values.
    pub rounding: RoundingMode,
    /// Whether to preserve original formatting tags.
    pub preserve_formatting: bool,
    /// Whether to include sync metadata as comments.
    pub include_sync_comments: bool,
}

impl Default for WriteOptions {
    fn default() -> Self {
        Self {
            rounding: RoundingMode::Round,
            preserve_formatting: true,
            include_sync_comments: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_subtitle_format_detection() {
        use std::path::Path;
        assert_eq!(
            SubtitleFormat::from_extension(Path::new("test.ass")),
            Some(SubtitleFormat::Ass)
        );
        assert_eq!(
            SubtitleFormat::from_extension(Path::new("test.srt")),
            Some(SubtitleFormat::Srt)
        );
        assert_eq!(
            SubtitleFormat::from_extension(Path::new("test.vtt")),
            Some(SubtitleFormat::WebVtt)
        );
        assert_eq!(
            SubtitleFormat::from_extension(Path::new("test.txt")),
            None
        );
    }

    #[test]
    fn test_ass_color_parsing() {
        // Standard format with alpha
        let color = AssColor::from_ass_string("&H00FFFFFF").unwrap();
        assert_eq!(color.r, 255);
        assert_eq!(color.g, 255);
        assert_eq!(color.b, 255);
        assert_eq!(color.a, 0);

        // Without alpha prefix
        let color = AssColor::from_ass_string("&HFFFFFF").unwrap();
        assert_eq!(color.r, 255);
        assert_eq!(color.g, 255);
        assert_eq!(color.b, 255);

        // Round-trip
        let original = AssColor::from_rgba(255, 128, 64, 32);
        let string = original.to_ass_string();
        let parsed = AssColor::from_ass_string(&string).unwrap();
        assert_eq!(original, parsed);
    }

    #[test]
    fn test_subtitle_event_shift() {
        let mut event = SubtitleEvent::new(1000.0, 2000.0, "Test");
        event.shift(500.0);
        assert_eq!(event.start_ms, 1500.0);
        assert_eq!(event.end_ms, 2500.0);

        // Negative shift clamped to 0
        event.shift(-2000.0);
        assert_eq!(event.start_ms, 0.0);
        assert_eq!(event.end_ms, 500.0);
    }

    #[test]
    fn test_rounding_modes() {
        // ASS rounding (centiseconds)
        assert_eq!(RoundingMode::Floor.apply_ass(1234.5), 1230.0);
        assert_eq!(RoundingMode::Round.apply_ass(1234.5), 1230.0);
        assert_eq!(RoundingMode::Round.apply_ass(1235.0), 1240.0);
        assert_eq!(RoundingMode::Ceil.apply_ass(1234.5), 1240.0);

        // SRT rounding (milliseconds)
        assert_eq!(RoundingMode::Floor.apply_srt(1234.5), 1234.0);
        assert_eq!(RoundingMode::Round.apply_srt(1234.5), 1235.0);
        assert_eq!(RoundingMode::Ceil.apply_srt(1234.5), 1235.0);
    }
}
