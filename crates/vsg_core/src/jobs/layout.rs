//! Layout management for saving and loading track configurations.
//!
//! Layouts can be saved per-job and reused for similar files.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use super::types::{ManualLayout, SavedLayoutData};

/// Generate a deterministic job ID from source file paths.
/// Uses MD5 hash of sorted source filenames (matches Python implementation).
pub fn generate_layout_id(sources: &HashMap<String, PathBuf>) -> String {
    use std::collections::BTreeMap;

    // Sort sources by key and build the hash input string
    let sorted: BTreeMap<_, _> = sources.iter().collect();
    let source_string: String = sorted
        .iter()
        .filter_map(|(key, path)| {
            path.file_name()
                .and_then(|n| n.to_str())
                .map(|name| format!("{}:{}", key, name))
        })
        .collect::<Vec<_>>()
        .join("|");

    // MD5 hash, take first 16 hex chars (matches Python)
    let digest = md5::compute(source_string.as_bytes());
    format!("{:x}", digest)[..16].to_string()
}

/// Manager for job layouts.
#[derive(Debug)]
pub struct LayoutManager {
    /// Directory where layouts are stored.
    layouts_dir: PathBuf,
}

impl LayoutManager {
    /// Create a new layout manager.
    pub fn new(layouts_dir: &Path) -> Self {
        Self {
            layouts_dir: layouts_dir.to_path_buf(),
        }
    }

    /// Ensure the layouts directory exists.
    fn ensure_dir(&self) -> Result<(), std::io::Error> {
        fs::create_dir_all(&self.layouts_dir)
    }

    /// Get the path to a layout file for a job.
    fn layout_path(&self, job_id: &str) -> PathBuf {
        self.layouts_dir.join(format!("{}.json", job_id))
    }

    /// Save a layout for a job with full metadata.
    pub fn save_layout_with_metadata(
        &self,
        job_id: &str,
        sources: &HashMap<String, PathBuf>,
        layout: &ManualLayout,
    ) -> Result<(), std::io::Error> {
        self.ensure_dir()?;

        let saved_data = SavedLayoutData::new(
            job_id.to_string(),
            sources.clone(),
            layout.clone(),
        );

        let path = self.layout_path(job_id);
        let json = serde_json::to_string_pretty(&saved_data)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        // Write atomically
        let temp_path = path.with_extension("json.tmp");
        fs::write(&temp_path, &json)?;
        fs::rename(&temp_path, &path)?;

        tracing::debug!("Saved layout for job '{}' to {}", job_id, path.display());
        Ok(())
    }

    /// Save a layout for a job (simple version without sources).
    /// Uses save_layout_with_metadata internally with empty sources.
    pub fn save_layout(&self, job_id: &str, layout: &ManualLayout) -> Result<(), std::io::Error> {
        self.save_layout_with_metadata(job_id, &HashMap::new(), layout)
    }

    /// Load the full saved layout data for a job.
    pub fn load_layout_data(&self, job_id: &str) -> Result<Option<SavedLayoutData>, std::io::Error> {
        let path = self.layout_path(job_id);

        if !path.exists() {
            return Ok(None);
        }

        let content = fs::read_to_string(&path)?;
        let saved_data: SavedLayoutData = serde_json::from_str(&content)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        Ok(Some(saved_data))
    }

    /// Load just the layout for a job (without metadata).
    pub fn load_layout(&self, job_id: &str) -> Result<Option<ManualLayout>, std::io::Error> {
        self.load_layout_data(job_id)
            .map(|opt| opt.map(|data| data.layout))
    }

    /// Check if a layout file exists for a job.
    pub fn layout_exists(&self, job_id: &str) -> bool {
        self.layout_path(job_id).exists()
    }

    /// Delete a layout for a job.
    pub fn delete_layout(&self, job_id: &str) -> Result<(), std::io::Error> {
        let path = self.layout_path(job_id);

        if path.exists() {
            fs::remove_file(&path)?;
        }

        Ok(())
    }

    /// List all saved layout job IDs.
    pub fn list_layouts(&self) -> Result<Vec<String>, std::io::Error> {
        if !self.layouts_dir.exists() {
            return Ok(Vec::new());
        }

        let mut ids = Vec::new();
        for entry in fs::read_dir(&self.layouts_dir)? {
            let entry = entry?;
            let path = entry.path();

            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                if name.ends_with(".json") && !name.ends_with(".tmp") {
                    let id = name.trim_end_matches(".json").to_string();
                    ids.push(id);
                }
            }
        }

        Ok(ids)
    }

    /// Clean up all layout files.
    pub fn cleanup_all(&self) -> Result<(), std::io::Error> {
        if self.layouts_dir.exists() {
            fs::remove_dir_all(&self.layouts_dir)?;
            tracing::info!("Cleaned up all layout files from {}", self.layouts_dir.display());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn layout_save_load() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        let mut layout = ManualLayout::new();
        layout.attachment_sources.push("Source 1".to_string());

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/path/to/file.mkv"));

        // Save with metadata
        manager.save_layout_with_metadata("test_job", &sources, &layout).unwrap();

        // Load full data
        let loaded_data = manager.load_layout_data("test_job").unwrap();
        assert!(loaded_data.is_some());
        let data = loaded_data.unwrap();
        assert_eq!(data.job_id, "test_job");
        assert_eq!(data.layout.attachment_sources, vec!["Source 1"]);
        assert!(!data.saved_timestamp.is_empty());

        // Load just layout
        let loaded_layout = manager.load_layout("test_job").unwrap();
        assert!(loaded_layout.is_some());
        assert_eq!(loaded_layout.unwrap().attachment_sources, vec!["Source 1"]);
    }

    #[test]
    fn layout_not_found() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        let result = manager.load_layout("nonexistent").unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn layout_exists_check() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        assert!(!manager.layout_exists("test_job"));

        let layout = ManualLayout::new();
        manager.save_layout("test_job", &layout).unwrap();

        assert!(manager.layout_exists("test_job"));
    }

    #[test]
    fn layout_list() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        let layout = ManualLayout::new();
        manager.save_layout("job_a", &layout).unwrap();
        manager.save_layout("job_b", &layout).unwrap();

        let ids = manager.list_layouts().unwrap();
        assert_eq!(ids.len(), 2);
        assert!(ids.contains(&"job_a".to_string()));
        assert!(ids.contains(&"job_b".to_string()));
    }

    #[test]
    fn layout_cleanup() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        let layout = ManualLayout::new();
        manager.save_layout("job_a", &layout).unwrap();
        manager.save_layout("job_b", &layout).unwrap();

        assert_eq!(manager.list_layouts().unwrap().len(), 2);

        manager.cleanup_all().unwrap();

        assert_eq!(manager.list_layouts().unwrap().len(), 0);
    }
}
