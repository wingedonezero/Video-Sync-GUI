//! Config manager for loading, saving, and atomic updates.
//!
//! Key features:
//! - Atomic writes (write to temp file, then rename)
//! - Section-level updates (only modified section is changed)
//! - Validation on load (removes invalid keys)
//! - Preserves comments and formatting with toml_edit

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use thiserror::Error;
use toml_edit::{DocumentMut, Item};

use super::settings::{ConfigSection, Settings};

/// Errors that can occur during config operations.
#[derive(Error, Debug)]
pub enum ConfigError {
    #[error("Failed to read config file: {0}")]
    ReadError(#[from] io::Error),

    #[error("Failed to parse config: {0}")]
    ParseError(#[from] toml::de::Error),

    #[error("Failed to serialize config: {0}")]
    SerializeError(#[from] toml::ser::Error),

    #[error("Failed to parse config for editing: {0}")]
    EditParseError(#[from] toml_edit::TomlError),

    #[error("Config file not found: {0}")]
    NotFound(PathBuf),
}

/// Result type for config operations.
pub type ConfigResult<T> = Result<T, ConfigError>;

/// Manages application configuration.
///
/// Handles loading, saving, and atomic section-level updates.
pub struct ConfigManager {
    /// Path to the config file.
    config_path: PathBuf,
    /// Current settings loaded in memory.
    settings: Settings,
}

impl ConfigManager {
    /// Create a new config manager with the given config file path.
    ///
    /// Does not load the config - call `load()` or `load_or_create()` after.
    pub fn new(config_path: impl Into<PathBuf>) -> Self {
        Self {
            config_path: config_path.into(),
            settings: Settings::default(),
        }
    }

    /// Get the config file path.
    pub fn path(&self) -> &Path {
        &self.config_path
    }

    /// Get a reference to the current settings.
    pub fn settings(&self) -> &Settings {
        &self.settings
    }

    /// Get a mutable reference to the current settings.
    ///
    /// Note: Changes made here are only in memory until `save()` or
    /// `update_section()` is called.
    pub fn settings_mut(&mut self) -> &mut Settings {
        &mut self.settings
    }

    /// Load config from file.
    ///
    /// Returns error if file doesn't exist.
    pub fn load(&mut self) -> ConfigResult<()> {
        if !self.config_path.exists() {
            return Err(ConfigError::NotFound(self.config_path.clone()));
        }

        let content = fs::read_to_string(&self.config_path)?;
        self.settings = self.parse_and_validate(&content)?;
        Ok(())
    }

    /// Load config from file, creating with defaults if it doesn't exist.
    ///
    /// Also validates and cleans up the config, saving if changes were made.
    pub fn load_or_create(&mut self) -> ConfigResult<()> {
        if self.config_path.exists() {
            let content = fs::read_to_string(&self.config_path)?;
            let (settings, was_modified) = self.parse_validate_and_clean(&content)?;
            self.settings = settings;

            // Save back if we had to clean anything up
            if was_modified {
                self.save()?;
            }
        } else {
            // Create parent directories if needed
            if let Some(parent) = self.config_path.parent() {
                fs::create_dir_all(parent)?;
            }

            self.settings = Settings::default();
            self.save()?;
        }
        Ok(())
    }

    /// Ensure all configured directories exist.
    ///
    /// Creates output, temp, and logs directories if they don't exist.
    /// Should be called after `load_or_create()`.
    pub fn ensure_dirs_exist(&self) -> ConfigResult<()> {
        let dirs = [
            &self.settings.paths.output_folder,
            &self.settings.paths.temp_root,
            &self.settings.paths.logs_folder,
        ];

        for dir in dirs {
            let path = PathBuf::from(dir);
            if !path.exists() {
                fs::create_dir_all(&path)?;
            }
        }

        Ok(())
    }

    /// Get the logs folder path.
    pub fn logs_folder(&self) -> PathBuf {
        PathBuf::from(&self.settings.paths.logs_folder)
    }

    /// Parse and validate config content.
    fn parse_and_validate(&self, content: &str) -> ConfigResult<Settings> {
        let settings: Settings = toml::from_str(content)?;
        Ok(settings)
    }

    /// Parse, validate, and clean up config content.
    ///
    /// Returns the settings and whether any modifications were made.
    fn parse_validate_and_clean(&self, content: &str) -> ConfigResult<(Settings, bool)> {
        // Parse into a document for editing
        let doc: DocumentMut = content.parse()?;

        // Parse into settings (this applies defaults for missing fields)
        let settings: Settings = toml::from_str(content)?;

        // Check if we need to clean up unknown keys
        let valid_sections = ["paths", "logging", "analysis", "chapters", "postprocess"];
        let mut has_unknown = false;

        for (key, _) in doc.iter() {
            if !valid_sections.contains(&key) {
                has_unknown = true;
                break;
            }
        }

        // If the content re-serializes differently, we had missing defaults
        let reserialized = toml::to_string_pretty(&settings)?;
        let was_modified = has_unknown || content.trim() != reserialized.trim();

        Ok((settings, was_modified))
    }

    /// Save the entire config atomically.
    ///
    /// Writes to a temp file first, then renames to ensure atomic write.
    pub fn save(&self) -> ConfigResult<()> {
        let content = self.generate_config_with_comments()?;
        self.atomic_write(&content)?;
        Ok(())
    }

    /// Update a specific section atomically.
    ///
    /// This re-reads the file from disk, updates only the specified section,
    /// and writes back atomically. This prevents in-memory corruption from
    /// affecting other sections.
    pub fn update_section(&mut self, section: ConfigSection) -> ConfigResult<()> {
        // Re-read current file from disk (get fresh state)
        let current_content = if self.config_path.exists() {
            fs::read_to_string(&self.config_path)?
        } else {
            String::new()
        };

        // Parse as editable document
        let mut doc: DocumentMut = if current_content.is_empty() {
            DocumentMut::new()
        } else {
            current_content.parse()?
        };

        // Serialize just the section we want to update
        let section_toml = match section {
            ConfigSection::Paths => toml::to_string_pretty(&self.settings.paths)?,
            ConfigSection::Logging => toml::to_string_pretty(&self.settings.logging)?,
            ConfigSection::Analysis => toml::to_string_pretty(&self.settings.analysis)?,
            ConfigSection::Chapters => toml::to_string_pretty(&self.settings.chapters)?,
            ConfigSection::Postprocess => toml::to_string_pretty(&self.settings.postprocess)?,
            ConfigSection::Subtitle => toml::to_string_pretty(&self.settings.subtitle)?,
        };

        // Parse the section as a table
        let section_doc: DocumentMut = section_toml.parse()?;
        let section_table = section_doc.as_table().clone();

        // Update just that section in the document
        let table_name = section.table_name();
        doc[table_name] = Item::Table(section_table);

        // Write atomically
        self.atomic_write(&doc.to_string())?;

        Ok(())
    }

    /// Generate config content with helpful comments.
    fn generate_config_with_comments(&self) -> ConfigResult<String> {
        let mut output = String::new();

        output.push_str("# Video Sync GUI Configuration\n");
        output.push_str(
            "# This file is auto-generated. Comments may be preserved on section updates.\n\n",
        );

        // Paths section
        output.push_str("# Output and working directories\n");
        output.push_str(&toml::to_string_pretty(&toml::toml! {
            [paths]
        })?);
        let paths_content = toml::to_string_pretty(&self.settings.paths)?;
        // Remove the implicit table header since we already added it
        for line in paths_content.lines() {
            output.push_str(line);
            output.push('\n');
        }
        output.push('\n');

        // Logging section
        output.push_str("# Logging configuration\n");
        output.push_str("[logging]\n");
        let logging_content = toml::to_string_pretty(&self.settings.logging)?;
        for line in logging_content.lines() {
            output.push_str(line);
            output.push('\n');
        }
        output.push('\n');

        // Analysis section
        output.push_str("# Audio/video analysis settings\n");
        output.push_str("[analysis]\n");
        let analysis_content = toml::to_string_pretty(&self.settings.analysis)?;
        for line in analysis_content.lines() {
            output.push_str(line);
            output.push('\n');
        }
        output.push('\n');

        // Chapters section
        output.push_str("# Chapter handling\n");
        output.push_str("[chapters]\n");
        let chapters_content = toml::to_string_pretty(&self.settings.chapters)?;
        for line in chapters_content.lines() {
            output.push_str(line);
            output.push('\n');
        }
        output.push('\n');

        // Postprocess section
        output.push_str("# Post-processing options\n");
        output.push_str("[postprocess]\n");
        let postprocess_content = toml::to_string_pretty(&self.settings.postprocess)?;
        for line in postprocess_content.lines() {
            output.push_str(line);
            output.push('\n');
        }

        Ok(output)
    }

    /// Write content to config file atomically.
    ///
    /// Writes to a temp file first, then renames.
    fn atomic_write(&self, content: &str) -> io::Result<()> {
        // Create parent directory if needed
        if let Some(parent) = self.config_path.parent() {
            fs::create_dir_all(parent)?;
        }

        // Write to temp file in same directory (for atomic rename)
        let temp_path = self.config_path.with_extension("toml.tmp");

        {
            let mut file = fs::File::create(&temp_path)?;
            file.write_all(content.as_bytes())?;
            file.sync_all()?; // Ensure data is flushed to disk
        }

        // Atomic rename
        fs::rename(&temp_path, &self.config_path)?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn load_or_create_creates_default() {
        let dir = tempdir().unwrap();
        let config_path = dir.path().join(".config").join("settings.toml");

        let mut manager = ConfigManager::new(&config_path);
        manager.load_or_create().unwrap();

        assert!(config_path.exists());
        let content = fs::read_to_string(&config_path).unwrap();
        assert!(content.contains("[paths]"));
        assert!(content.contains("[logging]"));
    }

    #[test]
    fn load_or_create_preserves_existing() {
        let dir = tempdir().unwrap();
        let config_path = dir.path().join("settings.toml");

        // Create a config with custom value
        fs::write(
            &config_path,
            "[paths]\noutput_folder = \"my_custom_folder\"\n",
        )
        .unwrap();

        let mut manager = ConfigManager::new(&config_path);
        manager.load_or_create().unwrap();

        assert_eq!(manager.settings().paths.output_folder, "my_custom_folder");
    }

    #[test]
    fn update_section_only_changes_target() {
        let dir = tempdir().unwrap();
        let config_path = dir.path().join("settings.toml");

        // Create initial config
        let mut manager = ConfigManager::new(&config_path);
        manager.load_or_create().unwrap();

        // Modify logging in memory
        manager.settings_mut().logging.compact = false;

        // Update only logging section
        manager.update_section(ConfigSection::Logging).unwrap();

        // Re-read and verify
        let content = fs::read_to_string(&config_path).unwrap();
        assert!(content.contains("compact = false"));
        // Paths should still have defaults
        assert!(content.contains("[paths]"));
    }

    #[test]
    fn atomic_write_creates_no_temp_on_success() {
        let dir = tempdir().unwrap();
        let config_path = dir.path().join("settings.toml");

        let mut manager = ConfigManager::new(&config_path);
        manager.load_or_create().unwrap();

        // Temp file should not exist after successful write
        let temp_path = config_path.with_extension("toml.tmp");
        assert!(!temp_path.exists());
    }
}
