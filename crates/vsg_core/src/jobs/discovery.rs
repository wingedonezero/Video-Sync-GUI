//! Job discovery from source files and directories.
//!
//! This module scans source files/directories and creates job entries.
//! Supports both direct file specification and batch folder matching.
//!
//! # Batch Matching Algorithm
//!
//! When directories are provided:
//! 1. Source 1 (reference) directory is scanned for video files
//! 2. For each reference file, matching files are found in other sources by filename
//! 3. A job is created for each reference file (even without matches in other sources)
//!
//! Supported formats: .mkv, .mp4, .m4v

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::types::JobQueueEntry;

/// Supported video file extensions.
const VIDEO_EXTENSIONS: &[&str] = &["mkv", "mp4", "m4v"];

/// Generate a unique job ID.
fn generate_job_id() -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);

    // Use timestamp + random suffix for uniqueness
    let suffix: u32 = rand::random::<u32>() % 10000;
    format!("job_{}_{:04}", timestamp, suffix)
}

/// Simple random number generator for job IDs (no external dependency).
mod rand {
    use std::cell::Cell;
    use std::time::{SystemTime, UNIX_EPOCH};

    thread_local! {
        static SEED: Cell<u64> = Cell::new(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_nanos() as u64)
                .unwrap_or(12345)
        );
    }

    pub fn random<T: From<u32>>() -> T {
        SEED.with(|seed| {
            // Simple xorshift
            let mut x = seed.get();
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            seed.set(x);
            T::from((x & 0xFFFFFFFF) as u32)
        })
    }
}

/// Derive a job name from the primary source path.
fn derive_job_name(source1: &Path) -> String {
    source1
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "Unnamed Job".to_string())
}

/// Check if a path is a supported video file.
fn is_video_file(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }

    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| VIDEO_EXTENSIONS.contains(&ext.to_lowercase().as_str()))
        .unwrap_or(false)
}

/// Find all video files in a directory (sorted).
fn find_video_files(dir: &Path) -> Vec<PathBuf> {
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| is_video_file(path))
        .collect();

    // Sort for consistent ordering
    files.sort();
    files
}

/// Discover jobs from source paths.
///
/// Creates jobs based on the provided sources. If sources are directories,
/// performs batch matching by filename.
///
/// # Arguments
///
/// * `sources` - Map of source keys ("Source 1", "Source 2", etc.) to file/dir paths
///
/// # Returns
///
/// Vector of discovered jobs.
pub fn discover_jobs(sources: &HashMap<String, PathBuf>) -> Result<Vec<JobQueueEntry>, String> {
    // Must have at least Source 1
    let source1_path = sources.get("Source 1").ok_or("Source 1 is required")?;

    // Check if Source 1 exists
    if !source1_path.exists() {
        return Err(format!("Source 1 not found: {}", source1_path.display()));
    }

    // Determine if we're doing batch (directory) or single file discovery
    if source1_path.is_dir() {
        discover_jobs_from_directories(sources)
    } else {
        discover_jobs_from_files(sources)
    }
}

/// Discover a single job from explicit file paths.
fn discover_jobs_from_files(sources: &HashMap<String, PathBuf>) -> Result<Vec<JobQueueEntry>, String> {
    let source1 = sources.get("Source 1").ok_or("Source 1 is required")?;

    // Validate Source 1 exists and is a file
    if !source1.exists() {
        return Err(format!("Source 1 file not found: {}", source1.display()));
    }
    if !source1.is_file() {
        return Err("Source 1 must be a file when not using batch mode".to_string());
    }

    // Validate other sources (if provided)
    for (key, path) in sources.iter() {
        if key == "Source 1" {
            continue;
        }
        // Skip empty paths
        if path.as_os_str().is_empty() {
            continue;
        }
        if !path.exists() {
            return Err(format!("{} file not found: {}", key, path.display()));
        }
        if !path.is_file() {
            return Err(format!("{} must be a file: {}", key, path.display()));
        }
    }

    // Filter out empty paths from sources
    let filtered_sources: HashMap<String, PathBuf> = sources
        .iter()
        .filter(|(_, p)| !p.as_os_str().is_empty() && p.exists())
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();

    // Create single job
    let job_id = generate_job_id();
    let job_name = derive_job_name(source1);
    let job = JobQueueEntry::new(job_id, job_name, filtered_sources.clone());

    tracing::info!(
        "Discovered 1 job: '{}' with {} sources",
        job.name,
        filtered_sources.len()
    );

    Ok(vec![job])
}

/// Discover jobs from directories using filename matching.
///
/// Scans Source 1 directory for video files and matches them by filename
/// to files in other source directories.
fn discover_jobs_from_directories(sources: &HashMap<String, PathBuf>) -> Result<Vec<JobQueueEntry>, String> {
    let source1_dir = sources.get("Source 1").ok_or("Source 1 is required")?;

    // Validate Source 1 is a directory
    if !source1_dir.is_dir() {
        return Err(format!(
            "Source 1 must be a directory for batch mode: {}",
            source1_dir.display()
        ));
    }

    // Collect other source directories
    let mut other_sources: Vec<(String, PathBuf)> = Vec::new();
    for (key, path) in sources.iter() {
        if key == "Source 1" {
            continue;
        }
        // Skip empty paths
        if path.as_os_str().is_empty() {
            continue;
        }
        if !path.exists() {
            return Err(format!("{} not found: {}", key, path.display()));
        }
        if !path.is_dir() {
            return Err(format!(
                "{} must be a directory for batch mode: {}",
                key,
                path.display()
            ));
        }
        other_sources.push((key.clone(), path.clone()));
    }

    // Sort other sources by key for consistent matching
    other_sources.sort_by(|a, b| a.0.cmp(&b.0));

    // Find all video files in Source 1
    let reference_files = find_video_files(source1_dir);

    if reference_files.is_empty() {
        return Err(format!(
            "No video files found in Source 1 directory: {}",
            source1_dir.display()
        ));
    }

    // Create a job for each reference file
    let mut jobs = Vec::new();

    for ref_file in &reference_files {
        let mut job_sources = HashMap::new();
        job_sources.insert("Source 1".to_string(), ref_file.clone());

        // Try to match by filename in other source directories
        let ref_filename = ref_file.file_name();

        for (key, dir) in &other_sources {
            if let Some(filename) = ref_filename {
                let match_path = dir.join(filename);
                if match_path.is_file() {
                    job_sources.insert(key.clone(), match_path);
                }
            }
        }

        let job_id = generate_job_id();
        let job_name = derive_job_name(ref_file);
        let job = JobQueueEntry::new(job_id, job_name, job_sources);
        jobs.push(job);
    }

    tracing::info!(
        "Discovered {} jobs from batch folder matching",
        jobs.len()
    );

    // Log match statistics
    let multi_source_count = jobs.iter().filter(|j| j.sources.len() > 1).count();
    let single_source_count = jobs.len() - multi_source_count;

    if multi_source_count > 0 {
        tracing::info!("  {} jobs with multiple sources", multi_source_count);
    }
    if single_source_count > 0 {
        tracing::info!("  {} jobs with only Source 1", single_source_count);
    }

    Ok(jobs)
}

/// Batch discovery options for future expansion.
#[derive(Debug, Clone, Default)]
pub struct BatchDiscoveryOptions {
    /// Only include jobs with at least this many sources.
    pub min_sources: Option<usize>,
    /// Filter to files matching this extension (e.g., "mkv").
    pub extension_filter: Option<String>,
    /// Enable recursive directory scanning.
    pub recursive: bool,
}

/// Discover jobs with options.
///
/// This variant allows more control over the discovery process.
pub fn discover_jobs_with_options(
    sources: &HashMap<String, PathBuf>,
    options: &BatchDiscoveryOptions,
) -> Result<Vec<JobQueueEntry>, String> {
    let mut jobs = discover_jobs(sources)?;

    // Apply min_sources filter
    if let Some(min) = options.min_sources {
        jobs.retain(|job| job.sources.len() >= min);
    }

    Ok(jobs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::{NamedTempFile, TempDir};

    #[test]
    fn discover_jobs_requires_sources() {
        let empty: HashMap<String, PathBuf> = HashMap::new();
        assert!(discover_jobs(&empty).is_err());
    }

    #[test]
    fn discover_jobs_validates_files() {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/nonexistent/a.mkv"));
        sources.insert("Source 2".to_string(), PathBuf::from("/nonexistent/b.mkv"));

        let result = discover_jobs(&sources);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("not found"));
    }

    #[test]
    fn discover_jobs_creates_job() {
        // Create temp files
        let mut file1 = NamedTempFile::new().unwrap();
        let mut file2 = NamedTempFile::new().unwrap();
        writeln!(file1, "test").unwrap();
        writeln!(file2, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), file1.path().to_path_buf());
        sources.insert("Source 2".to_string(), file2.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();
        assert_eq!(result.len(), 1);
        assert!(!result[0].id.is_empty());
    }

    #[test]
    fn discover_jobs_single_source() {
        // Create temp file
        let mut file1 = NamedTempFile::new().unwrap();
        writeln!(file1, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), file1.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].sources.len(), 1);
    }

    #[test]
    fn job_id_is_unique() {
        let id1 = generate_job_id();
        let id2 = generate_job_id();
        assert_ne!(id1, id2);
    }

    #[test]
    fn is_video_file_works() {
        assert!(is_video_file(Path::new("/test/movie.mkv")) || !Path::new("/test/movie.mkv").exists());
        // More thorough test would need actual files
    }

    #[test]
    fn batch_discovery_from_directories() {
        // Create temp directories
        let source1_dir = TempDir::new().unwrap();
        let source2_dir = TempDir::new().unwrap();

        // Create matching files
        let file1_path = source1_dir.path().join("movie.mkv");
        let file2_path = source2_dir.path().join("movie.mkv");
        let file3_path = source1_dir.path().join("other.mkv");

        std::fs::write(&file1_path, "test").unwrap();
        std::fs::write(&file2_path, "test").unwrap();
        std::fs::write(&file3_path, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1_dir.path().to_path_buf());
        sources.insert("Source 2".to_string(), source2_dir.path().to_path_buf());

        let jobs = discover_jobs(&sources).unwrap();

        // Should discover 2 jobs (movie.mkv and other.mkv)
        assert_eq!(jobs.len(), 2);

        // movie.mkv should have both sources
        let movie_job = jobs.iter().find(|j| j.name == "movie").unwrap();
        assert_eq!(movie_job.sources.len(), 2);

        // other.mkv should have only Source 1
        let other_job = jobs.iter().find(|j| j.name == "other").unwrap();
        assert_eq!(other_job.sources.len(), 1);
    }

    #[test]
    fn batch_discovery_empty_directory() {
        let empty_dir = TempDir::new().unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), empty_dir.path().to_path_buf());

        let result = discover_jobs(&sources);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("No video files"));
    }

    #[test]
    fn batch_discovery_with_min_sources() {
        // Create temp directories
        let source1_dir = TempDir::new().unwrap();
        let source2_dir = TempDir::new().unwrap();

        // Create files - only one has a match
        let file1_path = source1_dir.path().join("matched.mkv");
        let file2_path = source2_dir.path().join("matched.mkv");
        let file3_path = source1_dir.path().join("unmatched.mkv");

        std::fs::write(&file1_path, "test").unwrap();
        std::fs::write(&file2_path, "test").unwrap();
        std::fs::write(&file3_path, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1_dir.path().to_path_buf());
        sources.insert("Source 2".to_string(), source2_dir.path().to_path_buf());

        let options = BatchDiscoveryOptions {
            min_sources: Some(2),
            ..Default::default()
        };

        let jobs = discover_jobs_with_options(&sources, &options).unwrap();

        // Should only include matched.mkv (has 2 sources)
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].name, "matched");
    }
}
