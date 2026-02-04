//! Perceptual hashing functions for frame comparison.
//!
//! Pure functions for computing perceptual hashes of images.
//! Uses the `image_hasher` crate which provides pHash, dHash, aHash, and BlockHash.
//!
//! # Hash Algorithms
//!
//! - **PHash** (Perceptual Hash): DCT-based, best for different encodes/color grading
//! - **DHash** (Difference Hash): Gradient-based, fast, good for same encode
//! - **AHash** (Average Hash): Simplest, fastest, less robust
//! - **BlockHash**: Block-based, good for partial matching

use image::DynamicImage;
use image_hasher::{HashAlg, Hasher, HasherConfig, ImageHash};

use super::types::HashAlgorithm;

/// Compute a perceptual hash of an image.
///
/// # Arguments
/// * `image` - Image to hash
/// * `algorithm` - Hash algorithm to use
/// * `hash_size` - Hash size (8 or 16, larger = more precise but less tolerant)
///
/// # Returns
/// Hash as a byte vector, or None on failure
pub fn compute_hash(
    image: &DynamicImage,
    algorithm: HashAlgorithm,
    hash_size: u8,
) -> Option<ImageHash> {
    let alg = match algorithm {
        HashAlgorithm::PHash => HashAlg::DoubleGradient, // DCT-based perceptual hash
        HashAlgorithm::DHash => HashAlg::Gradient,       // Difference hash
        HashAlgorithm::AHash => HashAlg::Mean,           // Average hash
        HashAlgorithm::BlockHash => HashAlg::Blockhash,  // Block hash
    };

    let hasher = HasherConfig::new()
        .hash_alg(alg)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher();

    Some(hasher.hash_image(image))
}

/// Compute pHash (Perceptual Hash) of an image.
///
/// Best for comparing frames with different encodes or color grading.
///
/// # Arguments
/// * `image` - Image to hash
/// * `hash_size` - Hash size (default 16 for 256 bits)
///
/// # Returns
/// ImageHash object
pub fn compute_phash(image: &DynamicImage, hash_size: u8) -> ImageHash {
    let hasher = HasherConfig::new()
        .hash_alg(HashAlg::DoubleGradient)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher();

    hasher.hash_image(image)
}

/// Compute dHash (Difference Hash) of an image.
///
/// Fast, good for comparing frames from the same encode.
///
/// # Arguments
/// * `image` - Image to hash
/// * `hash_size` - Hash size (default 8 for 64 bits)
///
/// # Returns
/// ImageHash object
pub fn compute_dhash(image: &DynamicImage, hash_size: u8) -> ImageHash {
    let hasher = HasherConfig::new()
        .hash_alg(HashAlg::Gradient)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher();

    hasher.hash_image(image)
}

/// Compute aHash (Average Hash) of an image.
///
/// Simplest and fastest, but less robust to changes.
///
/// # Arguments
/// * `image` - Image to hash
/// * `hash_size` - Hash size (default 8 for 64 bits)
///
/// # Returns
/// ImageHash object
pub fn compute_ahash(image: &DynamicImage, hash_size: u8) -> ImageHash {
    let hasher = HasherConfig::new()
        .hash_alg(HashAlg::Mean)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher();

    hasher.hash_image(image)
}

/// Compute BlockHash of an image.
///
/// Good for partial image matching.
///
/// # Arguments
/// * `image` - Image to hash
/// * `hash_size` - Hash size
///
/// # Returns
/// ImageHash object
pub fn compute_blockhash(image: &DynamicImage, hash_size: u8) -> ImageHash {
    let hasher = HasherConfig::new()
        .hash_alg(HashAlg::Blockhash)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher();

    hasher.hash_image(image)
}

/// Compute Hamming distance between two hashes.
///
/// The Hamming distance is the number of bits that differ between two hashes.
/// Lower distance = more similar.
///
/// # Arguments
/// * `hash1` - First hash
/// * `hash2` - Second hash
///
/// # Returns
/// Number of differing bits (0 = identical)
///
/// # Typical Thresholds
/// - 0: Identical frames
/// - 1-5: Very similar (likely same frame)
/// - 6-10: Similar (might be same scene)
/// - 10+: Different frames
pub fn hamming_distance(hash1: &ImageHash, hash2: &ImageHash) -> u32 {
    hash1.dist(hash2)
}

/// Check if two hashes are considered matching.
///
/// # Arguments
/// * `hash1` - First hash
/// * `hash2` - Second hash
/// * `threshold` - Maximum distance for a match
///
/// # Returns
/// True if distance <= threshold
pub fn is_hash_match(hash1: &ImageHash, hash2: &ImageHash, threshold: u32) -> bool {
    hash1.dist(hash2) <= threshold
}

/// Convert hash to hexadecimal string.
///
/// Useful for logging and debugging.
///
/// # Arguments
/// * `hash` - Hash to convert
///
/// # Returns
/// Hex string representation
pub fn hash_to_hex(hash: &ImageHash) -> String {
    hash.to_base64()
}

/// Create a hasher with specified configuration.
///
/// Use this when you need to hash many images with the same settings.
///
/// # Arguments
/// * `algorithm` - Hash algorithm
/// * `hash_size` - Hash size
///
/// # Returns
/// Configured Hasher
pub fn create_hasher(algorithm: HashAlgorithm, hash_size: u8) -> Hasher {
    let alg = match algorithm {
        HashAlgorithm::PHash => HashAlg::DoubleGradient,
        HashAlgorithm::DHash => HashAlg::Gradient,
        HashAlgorithm::AHash => HashAlg::Mean,
        HashAlgorithm::BlockHash => HashAlg::Blockhash,
    };

    HasherConfig::new()
        .hash_alg(alg)
        .hash_size(hash_size as u32, hash_size as u32)
        .to_hasher()
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgb, RgbImage};

    fn create_test_image(r: u8, g: u8, b: u8) -> DynamicImage {
        let img = RgbImage::from_fn(64, 64, |_, _| Rgb([r, g, b]));
        DynamicImage::ImageRgb8(img)
    }

    fn create_gradient_image() -> DynamicImage {
        let img = RgbImage::from_fn(64, 64, |x, y| {
            Rgb([(x * 4) as u8, (y * 4) as u8, 128])
        });
        DynamicImage::ImageRgb8(img)
    }

    #[test]
    fn test_identical_images_zero_distance() {
        let img1 = create_test_image(128, 128, 128);
        let img2 = create_test_image(128, 128, 128);

        let hash1 = compute_phash(&img1, 8);
        let hash2 = compute_phash(&img2, 8);

        assert_eq!(hamming_distance(&hash1, &hash2), 0);
    }

    #[test]
    fn test_different_images_nonzero_distance() {
        let img1 = create_test_image(0, 0, 0);     // Black
        let img2 = create_test_image(255, 255, 255); // White

        let hash1 = compute_phash(&img1, 8);
        let hash2 = compute_phash(&img2, 8);

        let distance = hamming_distance(&hash1, &hash2);
        assert!(distance > 0, "Different images should have non-zero distance");
    }

    #[test]
    fn test_similar_images_low_distance() {
        let img1 = create_test_image(128, 128, 128);
        let img2 = create_test_image(130, 130, 130); // Slightly different

        let hash1 = compute_phash(&img1, 8);
        let hash2 = compute_phash(&img2, 8);

        let distance = hamming_distance(&hash1, &hash2);
        // Similar images should have low distance
        assert!(distance <= 5, "Similar images should have low distance, got {}", distance);
    }

    #[test]
    fn test_is_hash_match() {
        let img1 = create_test_image(128, 128, 128);
        let img2 = create_test_image(128, 128, 128);

        let hash1 = compute_phash(&img1, 8);
        let hash2 = compute_phash(&img2, 8);

        assert!(is_hash_match(&hash1, &hash2, 5));
    }

    #[test]
    fn test_all_algorithms() {
        let img = create_gradient_image();

        // All algorithms should produce valid hashes
        let phash = compute_phash(&img, 8);
        let dhash = compute_dhash(&img, 8);
        let ahash = compute_ahash(&img, 8);
        let blockhash = compute_blockhash(&img, 8);

        // Self-distance should be zero
        assert_eq!(hamming_distance(&phash, &phash), 0);
        assert_eq!(hamming_distance(&dhash, &dhash), 0);
        assert_eq!(hamming_distance(&ahash, &ahash), 0);
        assert_eq!(hamming_distance(&blockhash, &blockhash), 0);
    }

    #[test]
    fn test_compute_hash_wrapper() {
        let img = create_gradient_image();

        let hash = compute_hash(&img, HashAlgorithm::PHash, 8).unwrap();
        assert_eq!(hamming_distance(&hash, &hash), 0);
    }

    #[test]
    fn test_hash_to_hex() {
        let img = create_test_image(128, 128, 128);
        let hash = compute_phash(&img, 8);

        let hex = hash_to_hex(&hash);
        assert!(!hex.is_empty());
    }

    #[test]
    fn test_create_hasher() {
        let img = create_gradient_image();
        let hasher = create_hasher(HashAlgorithm::DHash, 8);

        let hash1 = hasher.hash_image(&img);
        let hash2 = hasher.hash_image(&img);

        assert_eq!(hamming_distance(&hash1, &hash2), 0);
    }
}
