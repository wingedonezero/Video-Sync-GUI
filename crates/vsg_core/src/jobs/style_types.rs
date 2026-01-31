//! Style-related types for subtitle track configuration.
//!
//! These types provide typed structures for ASS subtitle style modifications,
//! replacing untyped `HashMap<String, serde_json::Value>` fields.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// Style patches for multiple ASS styles.
///
/// Maps style name (e.g., "Default", "Signs") to property overrides.
/// Only styles with changes need to be included.
///
/// # Example
///
/// ```
/// use vsg_core::jobs::StylePatches;
///
/// let json = r#"{
///     "Default": { "fontsize": 48, "bold": true },
///     "Signs": { "fontsize": 36 }
/// }"#;
///
/// let patches: StylePatches = serde_json::from_str(json).unwrap();
/// assert!(patches.contains_key("Default"));
/// ```
pub type StylePatches = HashMap<String, StylePatch>;

/// Individual ASS style property overrides.
///
/// All fields are optional - only set fields are applied to the style.
/// Property names match ASS format (lowercase with underscores).
///
/// # Color Format
///
/// Colors use Qt hex format `#AARRGGBB` (e.g., `#FFFF0000` for red).
/// These are converted to ASS format `&HAABBGGRR` at apply time.
///
/// # Boolean Properties
///
/// ASS uses -1 for true and 0 for false for bold/italic/underline/strike_out.
/// This struct uses Rust bools for ergonomics; conversion happens at apply time.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct StylePatch {
    // === Font properties ===
    /// Font name (e.g., "Arial", "Noto Sans").
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fontname: Option<String>,

    /// Font size in points.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fontsize: Option<f32>,

    /// Bold text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bold: Option<bool>,

    /// Italic text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub italic: Option<bool>,

    /// Underlined text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub underline: Option<bool>,

    /// Strikeout text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub strike_out: Option<bool>,

    // === Color properties (Qt hex format #AARRGGBB) ===
    /// Primary (fill) color.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub primary_color: Option<String>,

    /// Secondary (karaoke) color.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub secondary_color: Option<String>,

    /// Outline (border) color.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outline_color: Option<String>,

    /// Shadow/background color.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub back_color: Option<String>,

    // === Size/scale properties ===
    /// Outline width in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outline: Option<f32>,

    /// Shadow depth in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shadow: Option<f32>,

    /// Horizontal scaling percentage (100.0 = normal).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scale_x: Option<f32>,

    /// Vertical scaling percentage (100.0 = normal).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scale_y: Option<f32>,

    /// Extra character spacing in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub spacing: Option<f32>,

    /// Text rotation angle in degrees.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub angle: Option<f32>,

    // === Layout properties ===
    /// Text alignment (numpad style: 1-9, default 2 = bottom center).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub alignment: Option<i32>,

    /// Left margin in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub margin_l: Option<i32>,

    /// Right margin in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub margin_r: Option<i32>,

    /// Vertical margin in pixels.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub margin_v: Option<i32>,

    /// Border style (1 = outline+shadow, 3 = opaque box).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub border_style: Option<i32>,

    // === Other ===
    /// Character set encoding (default 1 = default).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub encoding: Option<i32>,
}

impl StylePatch {
    /// Create an empty style patch.
    pub fn new() -> Self {
        Self::default()
    }

    /// Check if this patch has any properties set.
    pub fn is_empty(&self) -> bool {
        self.fontname.is_none()
            && self.fontsize.is_none()
            && self.bold.is_none()
            && self.italic.is_none()
            && self.underline.is_none()
            && self.strike_out.is_none()
            && self.primary_color.is_none()
            && self.secondary_color.is_none()
            && self.outline_color.is_none()
            && self.back_color.is_none()
            && self.outline.is_none()
            && self.shadow.is_none()
            && self.scale_x.is_none()
            && self.scale_y.is_none()
            && self.spacing.is_none()
            && self.angle.is_none()
            && self.alignment.is_none()
            && self.margin_l.is_none()
            && self.margin_r.is_none()
            && self.margin_v.is_none()
            && self.border_style.is_none()
            && self.encoding.is_none()
    }

    /// Count how many properties are set.
    pub fn property_count(&self) -> usize {
        let mut count = 0;
        if self.fontname.is_some() { count += 1; }
        if self.fontsize.is_some() { count += 1; }
        if self.bold.is_some() { count += 1; }
        if self.italic.is_some() { count += 1; }
        if self.underline.is_some() { count += 1; }
        if self.strike_out.is_some() { count += 1; }
        if self.primary_color.is_some() { count += 1; }
        if self.secondary_color.is_some() { count += 1; }
        if self.outline_color.is_some() { count += 1; }
        if self.back_color.is_some() { count += 1; }
        if self.outline.is_some() { count += 1; }
        if self.shadow.is_some() { count += 1; }
        if self.scale_x.is_some() { count += 1; }
        if self.scale_y.is_some() { count += 1; }
        if self.spacing.is_some() { count += 1; }
        if self.angle.is_some() { count += 1; }
        if self.alignment.is_some() { count += 1; }
        if self.margin_l.is_some() { count += 1; }
        if self.margin_r.is_some() { count += 1; }
        if self.margin_v.is_some() { count += 1; }
        if self.border_style.is_some() { count += 1; }
        if self.encoding.is_some() { count += 1; }
        count
    }
}

/// Font replacement mappings.
///
/// Maps original font names to replacement font names.
/// Used to substitute fonts that may not be available on the target system.
///
/// # Example
///
/// ```
/// use vsg_core::jobs::FontReplacements;
///
/// let mut replacements = FontReplacements::new();
/// replacements.add("MS Gothic", "Noto Sans JP");
/// replacements.add("Arial", "Helvetica");
///
/// assert_eq!(replacements.get("MS Gothic"), Some(&"Noto Sans JP".to_string()));
/// ```
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct FontReplacements(pub HashMap<String, String>);

impl FontReplacements {
    /// Create empty font replacements.
    pub fn new() -> Self {
        Self(HashMap::new())
    }

    /// Add a font replacement mapping.
    pub fn add(&mut self, old_font: impl Into<String>, new_font: impl Into<String>) {
        self.0.insert(old_font.into(), new_font.into());
    }

    /// Get the replacement for a font, if any.
    pub fn get(&self, old_font: &str) -> Option<&String> {
        self.0.get(old_font)
    }

    /// Check if there are any replacements.
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Get the number of replacements.
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Iterate over all replacements.
    pub fn iter(&self) -> impl Iterator<Item = (&String, &String)> {
        self.0.iter()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn style_patch_empty_by_default() {
        let patch = StylePatch::new();
        assert!(patch.is_empty());
        assert_eq!(patch.property_count(), 0);
    }

    #[test]
    fn style_patch_counts_properties() {
        let patch = StylePatch {
            fontsize: Some(48.0),
            bold: Some(true),
            primary_color: Some("#FFFF0000".to_string()),
            ..Default::default()
        };
        assert!(!patch.is_empty());
        assert_eq!(patch.property_count(), 3);
    }

    #[test]
    fn style_patch_serializes() {
        let patch = StylePatch {
            fontsize: Some(48.0),
            bold: Some(true),
            ..Default::default()
        };

        let json = serde_json::to_string(&patch).unwrap();
        assert!(json.contains("\"fontsize\":48.0"));
        assert!(json.contains("\"bold\":true"));
        // Empty fields should be skipped
        assert!(!json.contains("fontname"));
    }

    #[test]
    fn style_patches_deserialize() {
        let json = r#"{
            "Default": { "fontsize": 48, "bold": true },
            "Signs": { "fontsize": 36, "alignment": 8 }
        }"#;

        let patches: StylePatches = serde_json::from_str(json).unwrap();
        assert_eq!(patches.len(), 2);

        let default = patches.get("Default").unwrap();
        assert_eq!(default.fontsize, Some(48.0));
        assert_eq!(default.bold, Some(true));

        let signs = patches.get("Signs").unwrap();
        assert_eq!(signs.fontsize, Some(36.0));
        assert_eq!(signs.alignment, Some(8));
    }

    #[test]
    fn font_replacements_basic() {
        let mut replacements = FontReplacements::new();
        assert!(replacements.is_empty());

        replacements.add("Arial", "Helvetica");
        replacements.add("MS Gothic", "Noto Sans JP");

        assert_eq!(replacements.len(), 2);
        assert_eq!(replacements.get("Arial"), Some(&"Helvetica".to_string()));
        assert_eq!(replacements.get("Unknown"), None);
    }

    #[test]
    fn font_replacements_serializes() {
        let mut replacements = FontReplacements::new();
        replacements.add("Arial", "Helvetica");

        let json = serde_json::to_string(&replacements).unwrap();
        assert!(json.contains("\"Arial\":\"Helvetica\""));

        // Round-trip
        let parsed: FontReplacements = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.get("Arial"), Some(&"Helvetica".to_string()));
    }
}
