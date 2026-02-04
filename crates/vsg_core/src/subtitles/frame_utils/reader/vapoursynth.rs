//! VapourSynth-based video reader.
//!
//! Uses VapourSynth with FFMS2 or BestSource for fast, frame-accurate video access.
//! This is the preferred backend when available.
//!
//! # Backends
//!
//! - **FFMS2**: Fast indexing, widely used, default choice
//! - **BestSource**: Slower first load, more accurate for edge cases
//! - **L-SMASH**: Alternative backend

use std::path::{Path, PathBuf};
use std::sync::Arc;

use image::{DynamicImage, RgbImage};
use parking_lot::Mutex;

use super::VideoReader;
use crate::subtitles::error::FrameError;
use crate::subtitles::frame_utils::types::{DeinterlaceMethod, IndexerBackend, VideoReaderConfig};

// VapourSynth imports
use vapoursynth::prelude::*;
use vapoursynth::video_info::Property;

/// VapourSynth-based video reader.
///
/// Provides fast, frame-accurate video access through VapourSynth plugins.
pub struct VapourSynthReader {
    path: PathBuf,
    fps: f64,
    frame_count: u32,
    width: u32,
    height: u32,
    backend: IndexerBackend,
    // VapourSynth environment and node are kept in Arc<Mutex> for thread safety
    // Note: VapourSynth itself handles caching and efficient frame access
    env: Arc<Mutex<Option<VsEnvironment>>>,
}

/// Internal struct to hold VapourSynth state.
struct VsEnvironment {
    /// Leaked environment pointer - we manage its lifetime manually
    #[allow(dead_code)]
    leaked_env: &'static Environment,
    node: Node<'static>,
}

// Safety: VapourSynth handles thread safety internally
unsafe impl Send for VsEnvironment {}
unsafe impl Sync for VsEnvironment {}

impl VapourSynthReader {
    /// Open a video file with VapourSynth.
    ///
    /// # Arguments
    /// * `path` - Path to video file
    /// * `config` - Reader configuration
    ///
    /// # Returns
    /// VapourSynthReader instance
    pub fn open(path: &Path, config: &VideoReaderConfig) -> Result<Self, FrameError> {
        if !path.exists() {
            return Err(FrameError::OpenFailed {
                path: path.to_path_buf(),
                message: "File does not exist".to_string(),
            });
        }

        let path_str = path.to_string_lossy();

        tracing::info!(
            "[VapourSynth] Opening with {} backend: {}",
            config.indexer_backend.name(),
            path_str
        );

        // Create VapourSynth script based on backend
        let script = Self::create_script(path, config)?;

        tracing::debug!("[VapourSynth] Script:\n{}", script);

        // Create environment and evaluate script
        // We leak the environment to get 'static lifetime for the node
        let environment = Environment::from_script(&script).map_err(|e| {
            FrameError::OpenFailed {
                path: path.to_path_buf(),
                message: format!("VapourSynth script evaluation failed: {}", e),
            }
        })?;

        // Leak the environment to get 'static lifetime
        // This is intentional - VapourSynth nodes have lifetime tied to environment
        let leaked_env: &'static Environment = Box::leak(Box::new(environment));

        // Get the output node from the leaked environment
        let (node, _) = leaked_env.get_output(0).map_err(|e| {
            FrameError::OpenFailed {
                path: path.to_path_buf(),
                message: format!("Failed to get VapourSynth output: {}", e),
            }
        })?;

        // Get video info
        let info = node.info();

        // Get resolution - must be constant
        let resolution = match info.resolution {
            Property::Constant(r) => r,
            Property::Variable => {
                return Err(FrameError::OpenFailed {
                    path: path.to_path_buf(),
                    message: "Variable resolution not supported".to_string(),
                });
            }
        };

        // Get framerate - must be constant
        let framerate = match info.framerate {
            Property::Constant(f) => f,
            Property::Variable => {
                return Err(FrameError::OpenFailed {
                    path: path.to_path_buf(),
                    message: "Variable framerate not supported".to_string(),
                });
            }
        };

        let num_frames = info.num_frames;
        let fps = framerate.numerator as f64 / framerate.denominator as f64;

        tracing::info!(
            "[VapourSynth] Video info: {}x{}, {:.3} fps ({}/{}), {} frames",
            resolution.width,
            resolution.height,
            fps,
            framerate.numerator,
            framerate.denominator,
            num_frames
        );

        // Store the leaked environment pointer for cleanup
        // Safety: We control the lifetime through Arc<Mutex>
        let vs_env = VsEnvironment {
            leaked_env,
            node,
        };

        Ok(Self {
            path: path.to_path_buf(),
            fps,
            frame_count: num_frames as u32,
            width: resolution.width as u32,
            height: resolution.height as u32,
            backend: config.indexer_backend,
            env: Arc::new(Mutex::new(Some(vs_env))),
        })
    }

    /// Check if VapourSynth is available.
    pub fn is_available() -> bool {
        // Try to create a minimal VapourSynth environment
        let script = "import vapoursynth as vs\ncore = vs.core\nvs.core.std.BlankClip().set_output()";
        Environment::from_script(script).is_ok()
    }

    /// Check if a specific indexer plugin is available.
    pub fn is_plugin_available(backend: IndexerBackend) -> bool {
        let plugin_check = match backend {
            IndexerBackend::Ffms2 => {
                "import vapoursynth as vs\ncore = vs.core\ncore.ffms2"
            }
            IndexerBackend::BestSource => {
                "import vapoursynth as vs\ncore = vs.core\ncore.bs"
            }
            IndexerBackend::LSmash => {
                "import vapoursynth as vs\ncore = vs.core\ncore.lsmas"
            }
        };

        // This will fail if the plugin isn't loaded
        let script = format!(
            "{}\nvs.core.std.BlankClip().set_output()",
            plugin_check
        );
        Environment::from_script(&script).is_ok()
    }

    /// Create VapourSynth script for the given video and config.
    fn create_script(path: &Path, config: &VideoReaderConfig) -> Result<String, FrameError> {
        let path_str = path.to_string_lossy().replace('\\', "/");

        // Determine cache path for index
        let cache_dir = config.temp_dir.clone().unwrap_or_else(std::env::temp_dir);
        let cache_file = cache_dir.join(format!(
            "vsg_{}_{}.ffindex",
            path.file_name()
                .map(|s| s.to_string_lossy())
                .unwrap_or_default(),
            // Simple hash of path for uniqueness
            path_str.bytes().fold(0u64, |acc, b| acc.wrapping_add(b as u64))
        ));
        let cache_str = cache_file.to_string_lossy().replace('\\', "/");

        // Build script based on backend
        let source_line = match config.indexer_backend {
            IndexerBackend::Ffms2 => {
                format!(
                    "clip = core.ffms2.Source(source=r\"{}\", cachefile=r\"{}\")",
                    path_str, cache_str
                )
            }
            IndexerBackend::BestSource => {
                format!(
                    "clip = core.bs.VideoSource(source=r\"{}\")",
                    path_str
                )
            }
            IndexerBackend::LSmash => {
                format!(
                    "clip = core.lsmas.LWLibavSource(source=r\"{}\")",
                    path_str
                )
            }
        };

        // Build deinterlace filter if needed
        let deinterlace_line = match config.deinterlace {
            DeinterlaceMethod::None | DeinterlaceMethod::Auto => String::new(),
            DeinterlaceMethod::Yadif => "clip = core.yadifmod.Yadifmod(clip)".to_string(),
            DeinterlaceMethod::YadifMod => "clip = core.yadifmod.Yadifmod(clip)".to_string(),
            DeinterlaceMethod::Bob => "clip = core.std.SeparateFields(clip).std.DoubleWeave()".to_string(),
            DeinterlaceMethod::Bwdif => "clip = core.bwdif.Bwdif(clip)".to_string(),
        };

        // Convert to RGB for easier frame extraction
        let convert_line = "clip = core.resize.Bicubic(clip, format=vs.RGB24)";

        let script = format!(
            r#"import vapoursynth as vs
core = vs.core
{}
{}
{}
clip.set_output()
"#,
            source_line,
            if deinterlace_line.is_empty() {
                "# No deinterlacing".to_string()
            } else {
                deinterlace_line
            },
            convert_line
        );

        Ok(script)
    }

    /// Extract frame data as RGB image.
    fn get_frame_internal(&self, index: u32) -> Result<DynamicImage, FrameError> {
        let env_guard = self.env.lock();
        let vs_env = env_guard.as_ref().ok_or_else(|| FrameError::ExtractionFailed {
            time_ms: index as f64 * 1000.0 / self.fps,
            message: "VapourSynth environment not initialized".to_string(),
        })?;

        tracing::trace!("[VapourSynth] Getting frame {}", index);

        // Get frame from VapourSynth
        let frame = vs_env.node.get_frame(index as usize).map_err(|e| {
            FrameError::ExtractionFailed {
                time_ms: index as f64 * 1000.0 / self.fps,
                message: format!("Failed to get frame {}: {}", index, e),
            }
        })?;

        // Get frame dimensions
        let width = frame.width(0) as u32;
        let height = frame.height(0) as u32;

        // Extract RGB data
        // VapourSynth RGB24 has R, G, B planes
        let r_plane = frame.plane(0).map_err(|e| FrameError::ExtractionFailed {
            time_ms: index as f64 * 1000.0 / self.fps,
            message: format!("Failed to get R plane: {}", e),
        })?;
        let g_plane = frame.plane(1).map_err(|e| FrameError::ExtractionFailed {
            time_ms: index as f64 * 1000.0 / self.fps,
            message: format!("Failed to get G plane: {}", e),
        })?;
        let b_plane = frame.plane(2).map_err(|e| FrameError::ExtractionFailed {
            time_ms: index as f64 * 1000.0 / self.fps,
            message: format!("Failed to get B plane: {}", e),
        })?;

        // Build RGB image
        let mut rgb_data = Vec::with_capacity((width * height * 3) as usize);
        let stride = frame.stride(0);

        for y in 0..height as usize {
            for x in 0..width as usize {
                let offset = y * stride + x;
                rgb_data.push(r_plane[offset]);
                rgb_data.push(g_plane[offset]);
                rgb_data.push(b_plane[offset]);
            }
        }

        let img = RgbImage::from_raw(width, height, rgb_data).ok_or_else(|| {
            FrameError::ExtractionFailed {
                time_ms: index as f64 * 1000.0 / self.fps,
                message: "Failed to create image from frame data".to_string(),
            }
        })?;

        Ok(DynamicImage::ImageRgb8(img))
    }
}

impl VideoReader for VapourSynthReader {
    fn get_frame(&self, index: u32) -> Result<DynamicImage, FrameError> {
        if index >= self.frame_count {
            return Err(FrameError::ExtractionFailed {
                time_ms: index as f64 * 1000.0 / self.fps,
                message: format!(
                    "Frame index {} out of range (max: {})",
                    index,
                    self.frame_count - 1
                ),
            });
        }
        self.get_frame_internal(index)
    }

    fn get_frame_at_time(&self, time_ms: f64) -> Result<DynamicImage, FrameError> {
        let index = (time_ms * self.fps / 1000.0).round() as u32;
        self.get_frame(index.min(self.frame_count.saturating_sub(1)))
    }

    fn get_pts(&self, index: u32) -> Result<f64, FrameError> {
        // For CFR content, PTS is straightforward
        // TODO: For VFR, we'd need to read frame properties
        Ok(index as f64 * 1000.0 / self.fps)
    }

    fn frame_count(&self) -> u32 {
        self.frame_count
    }

    fn fps(&self) -> f64 {
        self.fps
    }

    fn width(&self) -> u32 {
        self.width
    }

    fn height(&self) -> u32 {
        self.height
    }

    fn backend_name(&self) -> &str {
        match self.backend {
            IndexerBackend::Ffms2 => "vapoursynth-ffms2",
            IndexerBackend::BestSource => "vapoursynth-bestsource",
            IndexerBackend::LSmash => "vapoursynth-lsmash",
        }
    }

    fn supports_deinterlace(&self) -> bool {
        true
    }
}

impl Drop for VapourSynthReader {
    fn drop(&mut self) {
        // Clean up VapourSynth environment
        let mut env_guard = self.env.lock();
        *env_guard = None;
        tracing::debug!("[VapourSynth] Closed video: {}", self.path.display());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available() {
        // Just verify it doesn't panic
        let _available = VapourSynthReader::is_available();
    }

    #[test]
    fn test_create_script_ffms2() {
        let path = Path::new("/test/video.mkv");
        let config = VideoReaderConfig {
            indexer_backend: IndexerBackend::Ffms2,
            ..Default::default()
        };

        let script = VapourSynthReader::create_script(path, &config).unwrap();
        assert!(script.contains("ffms2.Source"));
        assert!(script.contains("RGB24"));
    }

    #[test]
    fn test_create_script_bestsource() {
        let path = Path::new("/test/video.mkv");
        let config = VideoReaderConfig {
            indexer_backend: IndexerBackend::BestSource,
            ..Default::default()
        };

        let script = VapourSynthReader::create_script(path, &config).unwrap();
        assert!(script.contains("bs.VideoSource"));
    }

    #[test]
    fn test_create_script_with_deinterlace() {
        let path = Path::new("/test/video.mkv");
        let config = VideoReaderConfig {
            deinterlace: DeinterlaceMethod::Bwdif,
            ..Default::default()
        };

        let script = VapourSynthReader::create_script(path, &config).unwrap();
        assert!(script.contains("bwdif.Bwdif"));
    }
}
