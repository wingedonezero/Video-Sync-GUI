//! Source index newtype for type-safe source identification.

use std::fmt;

use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// Identifies a source by index (0-based internally, displayed as 1-based).
///
/// Provides type safety to prevent mixing source indices with track indices
/// or other numeric identifiers. Serializes as "Source 1", "Source 2", etc.
/// for JSON compatibility with existing layout files.
///
/// # Examples
///
/// ```
/// use vsg_core::models::SourceIndex;
///
/// let src = SourceIndex::new(0);
/// assert_eq!(src.display_name(), "Source 1");
/// assert_eq!(src.index(), 0);
///
/// let parsed = SourceIndex::from_display_name("Source 2").unwrap();
/// assert_eq!(parsed.index(), 1);
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SourceIndex(usize);

impl SourceIndex {
    /// Create a new source index (0-based).
    pub fn new(index: usize) -> Self {
        Self(index)
    }

    /// Get the underlying 0-based index.
    pub fn index(&self) -> usize {
        self.0
    }

    /// Get the 1-based display number.
    pub fn display_number(&self) -> usize {
        self.0 + 1
    }

    /// Display name ("Source 1", "Source 2", etc.)
    pub fn display_name(&self) -> String {
        format!("Source {}", self.display_number())
    }

    /// Parse from display name like "Source 1".
    ///
    /// Returns None if the string doesn't match the expected format.
    pub fn from_display_name(s: &str) -> Option<Self> {
        s.strip_prefix("Source ")
            .and_then(|n| n.parse::<usize>().ok())
            .filter(|&n| n >= 1)
            .map(|n| Self(n - 1))
    }

    /// Create SourceIndex for Source 1 (index 0).
    pub const fn source1() -> Self {
        Self(0)
    }

    /// Create SourceIndex for Source 2 (index 1).
    pub const fn source2() -> Self {
        Self(1)
    }
}

impl fmt::Display for SourceIndex {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.display_name())
    }
}

impl Default for SourceIndex {
    fn default() -> Self {
        Self::source1()
    }
}

// Serialize as "Source 1", "Source 2", etc. for JSON compatibility
impl Serialize for SourceIndex {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.display_name())
    }
}

impl<'de> Deserialize<'de> for SourceIndex {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        Self::from_display_name(&s).ok_or_else(|| {
            serde::de::Error::custom(format!(
                "invalid source format '{}', expected 'Source N' where N >= 1",
                s
            ))
        })
    }
}

/// Reference to a source, which can be either an indexed source or a special source.
///
/// This is used for track references where the source might not be from the
/// standard indexed sources (e.g., external files).
///
/// # Examples
///
/// ```
/// use vsg_core::models::{SourceIndex, SourceRef};
///
/// let indexed = SourceRef::Index(SourceIndex::source1());
/// assert!(!indexed.is_external());
/// assert_eq!(indexed.as_index(), Some(SourceIndex::source1()));
///
/// let external = SourceRef::External;
/// assert!(external.is_external());
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SourceRef {
    /// A regular indexed source (Source 1, Source 2, etc.)
    Index(SourceIndex),
    /// An external file (not from the sources HashMap).
    External,
}

impl SourceRef {
    /// Check if this is an external source reference.
    pub fn is_external(&self) -> bool {
        matches!(self, Self::External)
    }

    /// Get the source index if this is an indexed source.
    pub fn as_index(&self) -> Option<SourceIndex> {
        match self {
            Self::Index(idx) => Some(*idx),
            Self::External => None,
        }
    }

    /// Create a SourceRef from a display string like "Source 1" or "External".
    pub fn from_display_name(s: &str) -> Option<Self> {
        if s.eq_ignore_ascii_case("External") {
            Some(Self::External)
        } else {
            SourceIndex::from_display_name(s).map(Self::Index)
        }
    }

    /// Get the display name.
    pub fn display_name(&self) -> String {
        match self {
            Self::Index(idx) => idx.display_name(),
            Self::External => "External".to_string(),
        }
    }
}

impl Default for SourceRef {
    fn default() -> Self {
        Self::Index(SourceIndex::source1())
    }
}

impl fmt::Display for SourceRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.display_name())
    }
}

impl From<SourceIndex> for SourceRef {
    fn from(idx: SourceIndex) -> Self {
        Self::Index(idx)
    }
}

impl Serialize for SourceRef {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.display_name())
    }
}

impl<'de> Deserialize<'de> for SourceRef {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        Self::from_display_name(&s).ok_or_else(|| {
            serde::de::Error::custom(format!(
                "invalid source reference '{}', expected 'Source N' or 'External'",
                s
            ))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_index_display_name() {
        assert_eq!(SourceIndex::new(0).display_name(), "Source 1");
        assert_eq!(SourceIndex::new(1).display_name(), "Source 2");
        assert_eq!(SourceIndex::new(99).display_name(), "Source 100");
    }

    #[test]
    fn source_index_from_display_name() {
        assert_eq!(SourceIndex::from_display_name("Source 1"), Some(SourceIndex::new(0)));
        assert_eq!(SourceIndex::from_display_name("Source 2"), Some(SourceIndex::new(1)));
        assert_eq!(SourceIndex::from_display_name("Source 100"), Some(SourceIndex::new(99)));
        assert_eq!(SourceIndex::from_display_name("Source 0"), None);
        assert_eq!(SourceIndex::from_display_name("Invalid"), None);
        assert_eq!(SourceIndex::from_display_name("Source"), None);
        assert_eq!(SourceIndex::from_display_name("Source abc"), None);
    }

    #[test]
    fn source_index_constants() {
        assert_eq!(SourceIndex::source1().index(), 0);
        assert_eq!(SourceIndex::source2().index(), 1);
    }

    #[test]
    fn source_index_serialization() {
        let src = SourceIndex::new(2);
        let json = serde_json::to_string(&src).unwrap();
        assert_eq!(json, "\"Source 3\"");

        let parsed: SourceIndex = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, src);
    }

    #[test]
    fn source_index_hashmap_key() {
        use std::collections::HashMap;
        let mut map: HashMap<SourceIndex, i64> = HashMap::new();
        map.insert(SourceIndex::source1(), 100);
        map.insert(SourceIndex::source2(), -200);

        assert_eq!(map.get(&SourceIndex::new(0)), Some(&100));
        assert_eq!(map.get(&SourceIndex::new(1)), Some(&-200));
    }

    #[test]
    fn source_ref_indexed() {
        let indexed = SourceRef::Index(SourceIndex::source1());
        assert!(!indexed.is_external());
        assert_eq!(indexed.as_index(), Some(SourceIndex::source1()));
        assert_eq!(indexed.display_name(), "Source 1");
    }

    #[test]
    fn source_ref_external() {
        let external = SourceRef::External;
        assert!(external.is_external());
        assert_eq!(external.as_index(), None);
        assert_eq!(external.display_name(), "External");
    }

    #[test]
    fn source_ref_from_display_name() {
        assert_eq!(
            SourceRef::from_display_name("Source 1"),
            Some(SourceRef::Index(SourceIndex::source1()))
        );
        assert_eq!(
            SourceRef::from_display_name("External"),
            Some(SourceRef::External)
        );
        assert_eq!(
            SourceRef::from_display_name("external"),
            Some(SourceRef::External)
        );
        assert_eq!(SourceRef::from_display_name("Unknown"), None);
    }

    #[test]
    fn source_ref_serialization() {
        let indexed = SourceRef::Index(SourceIndex::source2());
        let json = serde_json::to_string(&indexed).unwrap();
        assert_eq!(json, "\"Source 2\"");

        let external = SourceRef::External;
        let json = serde_json::to_string(&external).unwrap();
        assert_eq!(json, "\"External\"");

        // Round-trip
        let parsed: SourceRef = serde_json::from_str("\"Source 3\"").unwrap();
        assert_eq!(parsed, SourceRef::Index(SourceIndex::new(2)));

        let parsed: SourceRef = serde_json::from_str("\"External\"").unwrap();
        assert_eq!(parsed, SourceRef::External);
    }

    #[test]
    fn source_ref_from_source_index() {
        let idx = SourceIndex::source1();
        let source_ref: SourceRef = idx.into();
        assert_eq!(source_ref, SourceRef::Index(idx));
    }
}
