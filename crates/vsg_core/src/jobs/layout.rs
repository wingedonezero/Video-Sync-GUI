//! Layout management for saving and loading track configurations.
//!
//! Layouts can be saved per-job and reused for similar files.

use std::fs;
use std::path::{Path, PathBuf};

use super::types::ManualLayout;

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
        self.layouts_dir.join(format!("{}_layout.json", job_id))
    }

    /// Save a layout for a job.
    pub fn save_layout(&self, job_id: &str, layout: &ManualLayout) -> Result<(), std::io::Error> {
        self.ensure_dir()?;

        let path = self.layout_path(job_id);
        let json = serde_json::to_string_pretty(layout)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        // Write atomically
        let temp_path = path.with_extension("json.tmp");
        fs::write(&temp_path, &json)?;
        fs::rename(&temp_path, &path)?;

        tracing::debug!("Saved layout for job '{}' to {}", job_id, path.display());
        Ok(())
    }

    /// Load a layout for a job.
    pub fn load_layout(&self, job_id: &str) -> Result<Option<ManualLayout>, std::io::Error> {
        let path = self.layout_path(job_id);

        if !path.exists() {
            return Ok(None);
        }

        let content = fs::read_to_string(&path)?;
        let layout: ManualLayout = serde_json::from_str(&content)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        Ok(Some(layout))
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
                if name.ends_with("_layout.json") {
                    let id = name.trim_end_matches("_layout.json").to_string();
                    ids.push(id);
                }
            }
        }

        Ok(ids)
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

        // Save
        manager.save_layout("test_job", &layout).unwrap();

        // Load
        let loaded = manager.load_layout("test_job").unwrap();
        assert!(loaded.is_some());
        assert_eq!(loaded.unwrap().attachment_sources, vec!["Source 1"]);
    }

    #[test]
    fn layout_not_found() {
        let temp_dir = TempDir::new().unwrap();
        let manager = LayoutManager::new(temp_dir.path());

        let result = manager.load_layout("nonexistent").unwrap();
        assert!(result.is_none());
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
}
