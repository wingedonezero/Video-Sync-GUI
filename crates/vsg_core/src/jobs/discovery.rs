//! Job discovery from source files.
//!
//! This module scans source files and creates job entries based on matching.
//! Currently a stub that creates one job per source set - batch matching
//! will be implemented later.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::types::JobQueueEntry;
use crate::models::SourceIndex;

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

/// Discover jobs from source paths.
///
/// # Current Implementation (Stub)
///
/// Creates a single job with the exact sources provided.
/// Does not scan directories or match files by duration/tracks.
///
/// # Future Implementation
///
/// Will support:
/// - Directory scanning (find all video files)
/// - Duration matching (files with similar duration are likely same content)
/// - Track count matching (similar track structures)
/// - Fuzzy filename matching
/// - Creating multiple jobs from directory scans
///
/// # Arguments
///
/// * `sources` - Map of source indices to file paths
///
/// # Returns
///
/// Vector of discovered jobs (currently always 1 job).
pub fn discover_jobs(sources: &HashMap<SourceIndex, PathBuf>) -> Result<Vec<JobQueueEntry>, String> {
    // Validate we have at least Source 1 and Source 2
    let source1 = sources.get(&SourceIndex::source1()).ok_or("Source 1 is required")?;
    let source2 = sources.get(&SourceIndex::source2()).ok_or("Source 2 is required")?;

    // Validate paths exist
    if !source1.exists() {
        return Err(format!("Source 1 file not found: {}", source1.display()));
    }
    if !source2.exists() {
        return Err(format!("Source 2 file not found: {}", source2.display()));
    }

    // Check optional sources
    for (source, path) in sources.iter() {
        if *source != SourceIndex::source1() && *source != SourceIndex::source2() && !path.as_os_str().is_empty() {
            if !path.exists() {
                return Err(format!("{} file not found: {}", source.display_name(), path.display()));
            }
        }
    }

    // Create single job with provided sources
    let job_id = generate_job_id();
    let job_name = derive_job_name(source1);

    let job = JobQueueEntry::new(job_id, job_name, sources.clone());

    tracing::info!(
        "Discovered 1 job: '{}' with {} sources",
        job.name,
        sources.len()
    );

    Ok(vec![job])
}

/// Discover jobs from a directory (future implementation).
///
/// Will scan directory for video files and match them based on duration
/// and track structure to create multiple jobs.
#[allow(dead_code)]
pub fn discover_jobs_from_directory(
    _dir: &Path,
    _reference_source: Option<&Path>,
) -> Result<Vec<JobQueueEntry>, String> {
    // TODO: Implement directory scanning and matching
    Err("Directory scanning not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn discover_jobs_requires_sources() {
        let empty: HashMap<SourceIndex, PathBuf> = HashMap::new();
        assert!(discover_jobs(&empty).is_err());

        let mut only_source1 = HashMap::new();
        only_source1.insert(SourceIndex::source1(), PathBuf::from("/test.mkv"));
        assert!(discover_jobs(&only_source1).is_err());
    }

    #[test]
    fn discover_jobs_validates_files() {
        let mut sources = HashMap::new();
        sources.insert(SourceIndex::source1(), PathBuf::from("/nonexistent/a.mkv"));
        sources.insert(SourceIndex::source2(), PathBuf::from("/nonexistent/b.mkv"));

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
        sources.insert(SourceIndex::source1(), file1.path().to_path_buf());
        sources.insert(SourceIndex::source2(), file2.path().to_path_buf());

        let result = discover_jobs(&sources).unwrap();
        assert_eq!(result.len(), 1);
        assert!(!result[0].id.is_empty());
    }

    #[test]
    fn job_id_is_unique() {
        let id1 = generate_job_id();
        let id2 = generate_job_id();
        assert_ne!(id1, id2);
    }
}
