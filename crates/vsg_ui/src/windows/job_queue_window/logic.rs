//! Job queue window helper functions

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::jobs::{discover_jobs, JobQueueEntry};

use super::messages::DiscoveredJob;

/// Convert discovered jobs from backend to UI format
pub fn convert_discovered_jobs(jobs: Vec<JobQueueEntry>) -> Vec<DiscoveredJob> {
    jobs.into_iter()
        .map(|entry| DiscoveredJob {
            id: entry.id,
            name: entry.name,
            sources: entry.sources,
        })
        .collect()
}

/// Discover jobs from source paths
pub fn discover_jobs_from_sources(
    sources: HashMap<String, PathBuf>,
) -> Result<Vec<JobQueueEntry>, String> {
    discover_jobs(&sources)
}

/// Sort jobs by natural filename order (Source 1 name)
#[allow(dead_code)]
pub fn sort_jobs_naturally(jobs: &mut [DiscoveredJob]) {
    jobs.sort_by(|a, b| {
        let name_a = a
            .sources
            .get("Source 1")
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        let name_b = b
            .sources
            .get("Source 1")
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        natural_sort_cmp(&name_a, &name_b)
    });
}

/// Natural sort comparison (handles numbers in strings)
fn natural_sort_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    let parts_a = split_numeric(a);
    let parts_b = split_numeric(b);

    for (pa, pb) in parts_a.iter().zip(parts_b.iter()) {
        let ord = match (pa.parse::<u64>(), pb.parse::<u64>()) {
            (Ok(na), Ok(nb)) => na.cmp(&nb),
            _ => pa.to_lowercase().cmp(&pb.to_lowercase()),
        };
        if ord != std::cmp::Ordering::Equal {
            return ord;
        }
    }

    parts_a.len().cmp(&parts_b.len())
}

/// Split string into numeric and non-numeric parts
fn split_numeric(s: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut is_digit = false;

    for c in s.chars() {
        let c_is_digit = c.is_ascii_digit();
        if current.is_empty() {
            is_digit = c_is_digit;
            current.push(c);
        } else if c_is_digit == is_digit {
            current.push(c);
        } else {
            parts.push(std::mem::take(&mut current));
            is_digit = c_is_digit;
            current.push(c);
        }
    }

    if !current.is_empty() {
        parts.push(current);
    }

    parts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_natural_sort() {
        let mut items = vec!["ep10.mkv", "ep2.mkv", "ep1.mkv", "ep20.mkv"];
        items.sort_by(|a, b| natural_sort_cmp(a, b));
        assert_eq!(items, vec!["ep1.mkv", "ep2.mkv", "ep10.mkv", "ep20.mkv"]);
    }
}
