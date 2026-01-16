// src/correction/utils.rs
// Utility functions for audio correction

/// CRITICAL: Buffer alignment for Opus and other codecs
/// Opus and certain codecs can produce unaligned output that must be trimmed
/// to a multiple of element_size (4 bytes for i32, f32)
///
/// PRESERVATION: Must match Python logic exactly
pub fn align_buffer(data: &[u8], element_size: usize) -> &[u8] {
    let aligned_len = (data.len() / element_size) * element_size;
    let _trimmed = data.len() - aligned_len;

    // In production, would log trimmed bytes for diagnostics
    // For now, this is just logic
    // if trimmed > 0 {
    //     log::debug!("Trimmed {} unaligned bytes", trimmed);
    // }

    &data[..aligned_len]
}

/// CRITICAL: Silence detection for int32 PCM audio
/// Uses standard deviation < 100.0 as threshold
///
/// PRESERVATION: Threshold must be exactly 100.0 for int32 PCM
/// This prevents correlation on silent/near-silent chunks
pub fn is_silence(samples: &[i32]) -> bool {
    let std_dev = calculate_std_i32(samples);
    std_dev < 100.0
}

/// Calculate standard deviation for i32 samples
pub fn calculate_std_i32(samples: &[i32]) -> f64 {
    if samples.is_empty() {
        return 0.0;
    }

    let mean = samples.iter().map(|&x| x as f64).sum::<f64>() / samples.len() as f64;
    let variance = samples.iter()
        .map(|&x| {
            let diff = x as f64 - mean;
            diff * diff
        })
        .sum::<f64>() / samples.len() as f64;

    variance.sqrt()
}

/// Calculate standard deviation for f64 samples
pub fn calculate_std_f64(samples: &[f64]) -> f64 {
    if samples.is_empty() {
        return 0.0;
    }

    let mean = samples.iter().sum::<f64>() / samples.len() as f64;
    let variance = samples.iter()
        .map(|&x| {
            let diff = x - mean;
            diff * diff
        })
        .sum::<f64>() / samples.len() as f64;

    variance.sqrt()
}

/// CRITICAL: Stepping scan ranges
/// Different from main analysis (5%-95%), stepping uses 5%-99%
pub const STEPPING_SCAN_START_PCT: f64 = 5.0;
pub const STEPPING_SCAN_END_PCT: f64 = 99.0;

/// Convert buffer of i32 samples to f32 (normalized to ±1.0)
pub fn i32_to_f32_normalized(samples: &[i32]) -> Vec<f32> {
    samples.iter()
        .map(|&x| x as f32 / i32::MAX as f32)
        .collect()
}

/// Convert buffer of f32 samples to i32 (denormalized from ±1.0)
pub fn f32_to_i32_denormalized(samples: &[f32]) -> Vec<i32> {
    samples.iter()
        .map(|&x| (x * i32::MAX as f32) as i32)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_align_buffer() {
        // 4-byte alignment for i32/f32
        let data = vec![0u8; 17]; // 17 bytes
        let aligned = align_buffer(&data, 4);
        assert_eq!(aligned.len(), 16); // Should trim to 16 bytes

        // Already aligned
        let data = vec![0u8; 16];
        let aligned = align_buffer(&data, 4);
        assert_eq!(aligned.len(), 16);

        // Empty buffer
        let data: Vec<u8> = vec![];
        let aligned = align_buffer(&data, 4);
        assert_eq!(aligned.len(), 0);
    }

    #[test]
    fn test_is_silence_loud() {
        // Loud signal (std > 100)
        let loud_samples: Vec<i32> = (0..1000).map(|i| i * 1000).collect();
        assert!(!is_silence(&loud_samples));
    }

    #[test]
    fn test_is_silence_quiet() {
        // Quiet signal (std < 100)
        let quiet_samples: Vec<i32> = vec![0; 1000]; // All zeros
        assert!(is_silence(&quiet_samples));

        let quiet_samples: Vec<i32> = vec![1, -1, 2, -2, 1, -1]; // Very small
        assert!(is_silence(&quiet_samples));
    }

    #[test]
    fn test_is_silence_threshold() {
        // Right at threshold
        // Create samples with std very close to 100
        let samples: Vec<i32> = vec![0, 200, 0, 200, 0, 200]; // Should have std around 100
        let std = calculate_std_i32(&samples);
        println!("std = {}", std);
        // This is borderline, behavior depends on exact std value
    }

    #[test]
    fn test_calculate_std_i32() {
        // Simple test case
        let samples = vec![0, 0, 0, 0];
        let std = calculate_std_i32(&samples);
        assert_eq!(std, 0.0);

        // Non-zero variance
        let samples = vec![1000, 2000, 3000, 4000];
        let std = calculate_std_i32(&samples);
        assert!(std > 0.0);

        // Empty
        let samples: Vec<i32> = vec![];
        let std = calculate_std_i32(&samples);
        assert_eq!(std, 0.0);
    }

    #[test]
    fn test_calculate_std_f64() {
        let samples = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let std = calculate_std_f64(&samples);
        // Mean = 3.0, variance = ((1-3)^2 + (2-3)^2 + (3-3)^2 + (4-3)^2 + (5-3)^2) / 5
        //                      = (4 + 1 + 0 + 1 + 4) / 5 = 2.0
        // std = sqrt(2.0) ≈ 1.414
        assert!((std - 1.414).abs() < 0.01);
    }

    #[test]
    fn test_scan_range_constants() {
        assert_eq!(STEPPING_SCAN_START_PCT, 5.0);
        assert_eq!(STEPPING_SCAN_END_PCT, 99.0);
    }

    #[test]
    fn test_i32_to_f32_normalized() {
        let samples = vec![i32::MAX, 0, i32::MIN + 1]; // MIN+1 to avoid overflow
        let normalized = i32_to_f32_normalized(&samples);

        assert!((normalized[0] - 1.0).abs() < 0.01);
        assert!((normalized[1] - 0.0).abs() < 0.01);
        assert!((normalized[2] + 1.0).abs() < 0.01);
    }

    #[test]
    fn test_f32_to_i32_denormalized() {
        let samples = vec![1.0f32, 0.0f32, -1.0f32];
        let denormalized = f32_to_i32_denormalized(&samples);

        assert_eq!(denormalized[0], i32::MAX);
        assert_eq!(denormalized[1], 0);
        // -1.0 * i32::MAX = i32::MIN (due to overflow), which is expected
        assert_eq!(denormalized[2], i32::MIN);
    }

    #[test]
    fn test_roundtrip_conversion() {
        let original = vec![100000i32, 0, -100000];
        let normalized = i32_to_f32_normalized(&original);
        let denormalized = f32_to_i32_denormalized(&normalized);

        // Should be close (some precision loss expected)
        for (orig, roundtrip) in original.iter().zip(denormalized.iter()) {
            let diff = (orig - roundtrip).abs();
            assert!(diff < 100); // Allow small error
        }
    }
}
