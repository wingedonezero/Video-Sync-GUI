//! Job discovery from source files.
//!
//! Discovers and creates processing jobs from source file paths. Supports two modes:
//!
//! 1. Single File Mode: Source 1 is a file. Creates one job using provided sources,
//!    or a single-source job for remux-only mode.
//!
//! 2. Batch Folder Mode: Source 1 is a folder. Scans for video files (.mkv, .mp4, .m4v)
//!    and creates multiple jobs by matching filenames across all source folders.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::types::JobQueueEntry;

/// Supported video file extensions for batch discovery.
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

/// Check if a path has a supported video extension.
fn is_video_file(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| VIDEO_EXTENSIONS.contains(&ext.to_lowercase().as_str()))
        .unwrap_or(false)
}

/// Discover jobs from source paths.
///
/// # Modes
///
/// ## Single File Mode
/// When Source 1 is a file, creates one job with all provided sources.
/// Supports single-source mode (Source 1 only) for remux-only operations.
///
/// ## Batch Folder Mode
/// When Source 1 is a folder, scans for video files and creates multiple jobs
/// by matching filenames across all source folders.
///
/// # Arguments
///
/// * `sources` - Map of source keys ("Source 1", "Source 2", etc.) to file/folder paths
///
/// # Returns
///
/// Vector of discovered jobs.
pub fn discover_jobs(sources: &HashMap<String, PathBuf>) -> Result<Vec<JobQueueEntry>, String> {
    let source1 = sources
        .get("Source 1")
        .ok_or("Source 1 (Reference) path is required")?;

    if !source1.exists() {
        return Err(format!("Source 1 path does not exist: {}", source1.display()));
    }

    // Get other source paths (non-empty ones)
    let other_sources: HashMap<String, PathBuf> = sources
        .iter()
        .filter(|(k, p)| *k != "Source 1" && !p.as_os_str().is_empty())
        .map(|(k, p)| (k.clone(), p.clone()))
        .collect();

    // === Single File Mode ===
    if source1.is_file() {
        return discover_single_file(source1, &other_sources);
    }

    // === Batch Folder Mode ===
    if source1.is_dir() {
        return discover_batch_folder(source1, &other_sources);
    }

    Err("Source 1 path is not a valid file or directory".to_string())
}

/// Discover a single job from file sources.
fn discover_single_file(
    source1: &Path,
    other_sources: &HashMap<String, PathBuf>,
) -> Result<Vec<JobQueueEntry>, String> {
    let mut job_sources: HashMap<String, PathBuf> = HashMap::new();
    job_sources.insert("Source 1".to_string(), source1.to_path_buf());

    // Add other sources that are files
    for (key, path) in other_sources {
        if path.is_file() {
            job_sources.insert(key.clone(), path.clone());
        } else if path.exists() && path.is_dir() {
            // If other source is a folder, try to find matching filename
            let match_file = path.join(source1.file_name().unwrap_or_default());
            if match_file.is_file() {
                job_sources.insert(key.clone(), match_file);
            }
        }
    }

    // Create job (even with only Source 1 for remux-only mode)
    let job_id = generate_job_id();
    let job_name = derive_job_name(source1);
    let job = JobQueueEntry::new(job_id, job_name, job_sources.clone());

    tracing::info!(
        "Discovered 1 job (single file): '{}' with {} sources",
        job.name,
        job_sources.len()
    );

    Ok(vec![job])
}

/// Discover multiple jobs by scanning a folder.
fn discover_batch_folder(
    source1_folder: &Path,
    other_sources: &HashMap<String, PathBuf>,
) -> Result<Vec<JobQueueEntry>, String> {
    // Validate that other sources are also folders (or empty)
    for (key, path) in other_sources {
        if path.exists() && path.is_file() {
            return Err(format!(
                "If Source 1 is a folder, {} must also be a folder (got file: {})",
                key,
                path.display()
            ));
        }
    }

    // Scan Source 1 folder for video files
    let video_files = scan_video_files(source1_folder)?;

    if video_files.is_empty() {
        return Err(format!(
            "No video files found in Source 1 folder: {}",
            source1_folder.display()
        ));
    }

    let mut jobs = Vec::new();

    for ref_file in video_files {
        let mut job_sources: HashMap<String, PathBuf> = HashMap::new();
        job_sources.insert("Source 1".to_string(), ref_file.clone());

        // Try to find matching files in other source folders
        if let Some(filename) = ref_file.file_name() {
            for (key, folder) in other_sources {
                if folder.is_dir() {
                    let match_file = folder.join(filename);
                    if match_file.is_file() {
                        job_sources.insert(key.clone(), match_file);
                    }
                }
            }
        }

        // Create job (even with only Source 1 for remux-only batch)
        let job_id = generate_job_id();
        let job_name = derive_job_name(&ref_file);
        let job = JobQueueEntry::new(job_id, job_name, job_sources);
        jobs.push(job);
    }

    tracing::info!(
        "Discovered {} jobs (batch folder) from {}",
        jobs.len(),
        source1_folder.display()
    );

    Ok(jobs)
}

/// Scan a directory for video files, sorted by name.
fn scan_video_files(dir: &Path) -> Result<Vec<PathBuf>, String> {
    let entries = fs::read_dir(dir)
        .map_err(|e| format!("Failed to read directory {}: {}", dir.display(), e))?;

    let mut video_files: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.is_file() && is_video_file(path))
        .collect();

    // Sort by filename for consistent ordering
    video_files.sort_by(|a, b| {
        a.file_name()
            .unwrap_or_default()
            .cmp(b.file_name().unwrap_or_default())
    });

    Ok(video_files)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::{NamedTempFile, TempDir};

    #[test]
    fn discover_jobs_requires_source1() {
        let empty: HashMap<String, PathBuf> = HashMap::new();
        assert!(discover_jobs(&empty).is_err());
    }

    #[test]
    fn discover_jobs_validates_source1_exists() {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/nonexistent/a.mkv"));

        let result = discover_jobs(&sources);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("does not exist"));
    }

    #[test]
    fn single_file_mode_creates_one_job() {
        let mut file1 = NamedTempFile::new().unwrap();
        writeln!(file1, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), file1.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();
        assert_eq!(result.len(), 1);
        assert!(!result[0].id.is_empty());
    }

    #[test]
    fn single_file_mode_with_multiple_sources() {
        let mut file1 = NamedTempFile::new().unwrap();
        let mut file2 = NamedTempFile::new().unwrap();
        writeln!(file1, "test").unwrap();
        writeln!(file2, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), file1.path().to_path_buf());
        sources.insert("Source 2".to_string(), file2.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].sources.len(), 2);
    }

    #[test]
    fn batch_folder_mode_creates_multiple_jobs() {
        let source1_dir = TempDir::new().unwrap();
        let source2_dir = TempDir::new().unwrap();

        // Create video files in Source 1
        fs::write(source1_dir.path().join("ep01.mkv"), "video1").unwrap();
        fs::write(source1_dir.path().join("ep02.mkv"), "video2").unwrap();
        fs::write(source1_dir.path().join("readme.txt"), "not a video").unwrap();

        // Create matching files in Source 2
        fs::write(source2_dir.path().join("ep01.mkv"), "audio1").unwrap();
        fs::write(source2_dir.path().join("ep02.mkv"), "audio2").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1_dir.path().to_path_buf());
        sources.insert("Source 2".to_string(), source2_dir.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();

        // Should find 2 video files (not the .txt)
        assert_eq!(result.len(), 2);

        // Jobs should be sorted by filename
        assert!(result[0].name.contains("ep01"));
        assert!(result[1].name.contains("ep02"));

        // Each job should have both sources
        assert_eq!(result[0].sources.len(), 2);
        assert_eq!(result[1].sources.len(), 2);
    }

    #[test]
    fn batch_folder_mode_partial_matches() {
        let source1_dir = TempDir::new().unwrap();
        let source2_dir = TempDir::new().unwrap();

        // Create video files in Source 1
        fs::write(source1_dir.path().join("ep01.mkv"), "video1").unwrap();
        fs::write(source1_dir.path().join("ep02.mkv"), "video2").unwrap();

        // Source 2 only has ep01
        fs::write(source2_dir.path().join("ep01.mkv"), "audio1").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1_dir.path().to_path_buf());
        sources.insert("Source 2".to_string(), source2_dir.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();

        assert_eq!(result.len(), 2);

        // ep01 should have 2 sources
        assert_eq!(result[0].sources.len(), 2);
        // ep02 should have only 1 source (remux-only mode)
        assert_eq!(result[1].sources.len(), 1);
    }

    #[test]
    fn batch_folder_rejects_file_as_other_source() {
        let source1_dir = TempDir::new().unwrap();
        let mut source2_file = NamedTempFile::new().unwrap();

        fs::write(source1_dir.path().join("ep01.mkv"), "video1").unwrap();
        writeln!(source2_file, "test").unwrap();

        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), source1_dir.path().to_path_buf());
        sources.insert("Source 2".to_string(), source2_file.path().to_path_buf());

        let result = discover_jobs(&sources);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("must also be a folder"));
    }

    #[test]
    fn video_extension_detection() {
        assert!(is_video_file(Path::new("test.mkv")));
        assert!(is_video_file(Path::new("test.MKV")));
        assert!(is_video_file(Path::new("test.mp4")));
        assert!(is_video_file(Path::new("test.m4v")));
        assert!(!is_video_file(Path::new("test.txt")));
        assert!(!is_video_file(Path::new("test.avi"))); // Not in our list
    }

    #[test]
    fn job_id_is_unique() {
        let id1 = generate_job_id();
        let id2 = generate_job_id();
        assert_ne!(id1, id2);
    }
}
