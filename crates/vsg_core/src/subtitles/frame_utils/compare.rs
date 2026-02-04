//! Frame comparison functions.
//!
//! Pure functions for comparing video frames using various methods:
//! - Hash-based comparison (pHash, dHash, etc.)
//! - SSIM (Structural Similarity Index)
//! - MSE (Mean Squared Error)
//!
//! Uses the `image-compare` crate for SSIM and RMS calculations.

use image::DynamicImage;
use image_compare::Algorithm;

use super::hash::{compute_hash, hamming_distance};
use super::types::{ComparisonMethod, FrameCompareResult, HashAlgorithm};

/// Compare two frames using the specified method.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
/// * `method` - Comparison method to use
/// * `hash_algorithm` - Hash algorithm (if method is Hash)
/// * `hash_size` - Hash size (if method is Hash)
/// * `hash_threshold` - Threshold for hash matching
///
/// # Returns
/// FrameCompareResult with distance and match status
pub fn compare_frames(
    frame1: &DynamicImage,
    frame2: &DynamicImage,
    method: ComparisonMethod,
    hash_algorithm: HashAlgorithm,
    hash_size: u8,
    hash_threshold: u32,
) -> FrameCompareResult {
    match method {
        ComparisonMethod::Hash => {
            compare_frames_hash(frame1, frame2, hash_algorithm, hash_size, hash_threshold)
        }
        ComparisonMethod::Ssim => compare_frames_ssim(frame1, frame2),
        ComparisonMethod::Mse => compare_frames_mse(frame1, frame2),
    }
}

/// Compare frames using perceptual hashing.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
/// * `algorithm` - Hash algorithm
/// * `hash_size` - Hash size
/// * `threshold` - Maximum distance for a match
///
/// # Returns
/// FrameCompareResult where distance is Hamming distance (0 = identical)
pub fn compare_frames_hash(
    frame1: &DynamicImage,
    frame2: &DynamicImage,
    algorithm: HashAlgorithm,
    hash_size: u8,
    threshold: u32,
) -> FrameCompareResult {
    let hash1 = match compute_hash(frame1, algorithm, hash_size) {
        Some(h) => h,
        None => {
            return FrameCompareResult {
                distance: f64::MAX,
                is_match: false,
                method: ComparisonMethod::Hash,
            }
        }
    };

    let hash2 = match compute_hash(frame2, algorithm, hash_size) {
        Some(h) => h,
        None => {
            return FrameCompareResult {
                distance: f64::MAX,
                is_match: false,
                method: ComparisonMethod::Hash,
            }
        }
    };

    let distance = hamming_distance(&hash1, &hash2);

    FrameCompareResult {
        distance: distance as f64,
        is_match: distance <= threshold,
        method: ComparisonMethod::Hash,
    }
}

/// Compute SSIM (Structural Similarity Index) between two frames.
///
/// SSIM compares structural patterns and is more accurate than perceptual
/// hashing for detecting subtle differences.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
///
/// # Returns
/// SSIM value from 0.0 to 1.0 (higher = more similar)
/// - 1.0 = identical
/// - > 0.95 = very similar
/// - < 0.8 = noticeably different
pub fn compute_ssim(frame1: &DynamicImage, frame2: &DynamicImage) -> f64 {
    // Convert to grayscale for SSIM
    let gray1 = frame1.to_luma8();
    let gray2 = frame2.to_luma8();

    // Resize if needed to match dimensions
    let (gray1, gray2) = if gray1.dimensions() != gray2.dimensions() {
        let (w1, h1) = gray1.dimensions();
        let (w2, h2) = gray2.dimensions();

        // Use the smaller dimensions
        let (w, h) = (w1.min(w2), h1.min(h2));

        let resized1 = image::imageops::resize(&gray1, w, h, image::imageops::FilterType::Lanczos3);
        let resized2 = image::imageops::resize(&gray2, w, h, image::imageops::FilterType::Lanczos3);
        (resized1, resized2)
    } else {
        (gray1, gray2)
    };

    // Use image-compare's SSIM implementation
    match image_compare::gray_similarity_structure(&Algorithm::MSSIMSimple, &gray1, &gray2) {
        Ok(similarity) => similarity.score,
        Err(_) => 0.0,
    }
}

/// Compare frames using SSIM.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
///
/// # Returns
/// FrameCompareResult where distance is (1.0 - SSIM) * 100 (0 = identical)
pub fn compare_frames_ssim(frame1: &DynamicImage, frame2: &DynamicImage) -> FrameCompareResult {
    let ssim = compute_ssim(frame1, frame2);

    // Convert SSIM to distance (0 = identical, higher = more different)
    // Scale to roughly 0-100 range for consistency with other methods
    let distance = (1.0 - ssim) * 100.0;

    // Consider it a match if SSIM > 0.90 (90% similarity)
    let is_match = ssim > 0.90;

    FrameCompareResult {
        distance,
        is_match,
        method: ComparisonMethod::Ssim,
    }
}

/// Compute MSE (Mean Squared Error) between two frames.
///
/// MSE measures the average squared difference between pixel values.
/// Lower = more similar, 0 = identical.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
///
/// # Returns
/// MSE value (0 = identical, higher = more different)
pub fn compute_mse(frame1: &DynamicImage, frame2: &DynamicImage) -> f64 {
    // Convert to grayscale
    let gray1 = frame1.to_luma8();
    let gray2 = frame2.to_luma8();

    // Resize if needed
    let (gray1, gray2) = if gray1.dimensions() != gray2.dimensions() {
        let (w1, h1) = gray1.dimensions();
        let (w2, h2) = gray2.dimensions();

        let (w, h) = (w1.min(w2), h1.min(h2));

        let resized1 = image::imageops::resize(&gray1, w, h, image::imageops::FilterType::Lanczos3);
        let resized2 = image::imageops::resize(&gray2, w, h, image::imageops::FilterType::Lanczos3);
        (resized1, resized2)
    } else {
        (gray1, gray2)
    };

    // Use image-compare's RMS (which is sqrt of MSE, so we square it)
    match image_compare::gray_similarity_structure(&Algorithm::RootMeanSquared, &gray1, &gray2) {
        Ok(similarity) => {
            // RMS returns a similarity score, we want MSE
            // The score is 1.0 for identical, 0.0 for completely different
            // Convert to MSE-like scale
            let rms_diff = (1.0 - similarity.score) * 255.0; // Scale to 0-255
            rms_diff * rms_diff // Square for MSE
        }
        Err(_) => f64::MAX,
    }
}

/// Compare frames using MSE.
///
/// # Arguments
/// * `frame1` - First frame
/// * `frame2` - Second frame
///
/// # Returns
/// FrameCompareResult where distance is normalized MSE (0 = identical)
pub fn compare_frames_mse(frame1: &DynamicImage, frame2: &DynamicImage) -> FrameCompareResult {
    let mse = compute_mse(frame1, frame2);

    // Normalize to ~0-100 range
    let distance = (mse / 100.0).min(100.0);

    // Consider it a match if MSE < 500 (empirical threshold)
    let is_match = mse < 500.0;

    FrameCompareResult {
        distance,
        is_match,
        method: ComparisonMethod::Mse,
    }
}

/// Get recommended threshold for a comparison method.
///
/// # Arguments
/// * `method` - Comparison method
/// * `hash_size` - Hash size (for hash-based methods)
///
/// # Returns
/// Recommended threshold value
pub fn recommended_threshold(method: ComparisonMethod, hash_size: u8) -> f64 {
    match method {
        ComparisonMethod::Hash => {
            // Threshold depends on hash size
            // For 8x8 (64 bits): ~5-10
            // For 16x16 (256 bits): ~10-15
            if hash_size <= 8 {
                5.0
            } else {
                12.0
            }
        }
        ComparisonMethod::Ssim => {
            // SSIM distance (1 - ssim) * 100
            // 10 means SSIM > 0.90
            10.0
        }
        ComparisonMethod::Mse => {
            // Normalized MSE
            5.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgb, RgbImage};

    fn create_solid_image(r: u8, g: u8, b: u8) -> DynamicImage {
        let img = RgbImage::from_fn(64, 64, |_, _| Rgb([r, g, b]));
        DynamicImage::ImageRgb8(img)
    }

    fn create_gradient_image() -> DynamicImage {
        let img = RgbImage::from_fn(64, 64, |x, y| Rgb([(x * 4) as u8, (y * 4) as u8, 128]));
        DynamicImage::ImageRgb8(img)
    }

    #[test]
    fn test_ssim_identical() {
        let img1 = create_solid_image(128, 128, 128);
        let img2 = create_solid_image(128, 128, 128);

        let ssim = compute_ssim(&img1, &img2);
        assert!(ssim > 0.99, "Identical images should have SSIM near 1.0, got {}", ssim);
    }

    #[test]
    fn test_ssim_different() {
        let img1 = create_solid_image(0, 0, 0);
        let img2 = create_solid_image(255, 255, 255);

        let ssim = compute_ssim(&img1, &img2);
        assert!(ssim < 0.5, "Different images should have low SSIM, got {}", ssim);
    }

    #[test]
    fn test_mse_identical() {
        let img1 = create_solid_image(128, 128, 128);
        let img2 = create_solid_image(128, 128, 128);

        let mse = compute_mse(&img1, &img2);
        assert!(mse < 1.0, "Identical images should have MSE near 0, got {}", mse);
    }

    #[test]
    fn test_compare_frames_hash() {
        let img1 = create_gradient_image();
        let img2 = create_gradient_image();

        let result = compare_frames_hash(&img1, &img2, HashAlgorithm::PHash, 8, 5);
        assert!(result.is_match, "Identical images should match");
        assert!(result.distance < 1.0, "Distance should be near 0");
    }

    #[test]
    fn test_compare_frames_ssim() {
        let img1 = create_gradient_image();
        let img2 = create_gradient_image();

        let result = compare_frames_ssim(&img1, &img2);
        assert!(result.is_match, "Identical images should match");
    }

    #[test]
    fn test_compare_frames_mse() {
        let img1 = create_gradient_image();
        let img2 = create_gradient_image();

        let result = compare_frames_mse(&img1, &img2);
        assert!(result.is_match, "Identical images should match");
    }

    #[test]
    fn test_compare_frames_wrapper() {
        let img1 = create_solid_image(100, 100, 100);
        let img2 = create_solid_image(100, 100, 100);

        // Test all methods through wrapper
        let hash_result = compare_frames(
            &img1,
            &img2,
            ComparisonMethod::Hash,
            HashAlgorithm::PHash,
            8,
            5,
        );
        assert!(hash_result.is_match);

        let ssim_result = compare_frames(
            &img1,
            &img2,
            ComparisonMethod::Ssim,
            HashAlgorithm::PHash,
            8,
            5,
        );
        assert!(ssim_result.is_match);

        let mse_result = compare_frames(
            &img1,
            &img2,
            ComparisonMethod::Mse,
            HashAlgorithm::PHash,
            8,
            5,
        );
        assert!(mse_result.is_match);
    }

    #[test]
    fn test_different_sized_images() {
        let img1 = DynamicImage::ImageRgb8(RgbImage::from_fn(64, 64, |_, _| Rgb([128, 128, 128])));
        let img2 = DynamicImage::ImageRgb8(RgbImage::from_fn(128, 128, |_, _| Rgb([128, 128, 128])));

        // Should handle different sizes gracefully
        let ssim = compute_ssim(&img1, &img2);
        assert!(ssim > 0.9, "Same content at different sizes should be similar");
    }
}
