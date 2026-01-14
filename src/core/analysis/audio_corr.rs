//! Audio correlation analysis for A/V sync detection
//!
//! Implements GCC-PHAT and standard cross-correlation (SCC) algorithms
//! using pure Rust with rustfft for FFT operations.

use crate::core::io::runner::CommandRunner;
use crate::core::models::results::{CoreError, CoreResult};
use ndarray::Array1;
use rustfft::{num_complex::Complex, FftPlanner};
use std::path::Path;

/// Correlation result
#[derive(Debug, Clone)]
pub struct CorrelationResult {
    /// Delay in samples
    pub delay_samples: i64,

    /// Delay in milliseconds
    pub delay_ms: f64,

    /// Confidence score (0.0 to 1.0)
    pub confidence: f64,

    /// Peak correlation value
    pub peak_value: f64,

    /// Sample rate used
    pub sample_rate: u32,
}

/// Correlation method
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CorrelationMethod {
    /// Generalized Cross-Correlation with Phase Transform
    GccPhat,

    /// Standard Cross-Correlation
    Scc,
}

/// Audio correlation analyzer
pub struct AudioCorrelator {
    runner: CommandRunner,
    method: CorrelationMethod,
    sample_rate: u32,
    chunk_duration: u32,
    chunk_count: u32,
}

impl AudioCorrelator {
    /// Create a new audio correlator
    pub fn new(
        runner: CommandRunner,
        method: CorrelationMethod,
        sample_rate: u32,
        chunk_duration: u32,
        chunk_count: u32,
    ) -> Self {
        Self {
            runner,
            method,
            sample_rate,
            chunk_duration,
            chunk_count,
        }
    }

    /// Extract audio from video file using ffmpeg
    fn extract_audio(&self, video_path: &Path, output_path: &Path) -> CoreResult<()> {
        let video_str = video_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", video_path)))?;
        let output_str = output_path
            .to_str()
            .ok_or_else(|| CoreError::Other("Invalid output path".to_string()))?;

        let output = self.runner.run(&[
            "ffmpeg",
            "-y",
            "-i",
            video_str,
            "-vn", // No video
            "-ar",
            &self.sample_rate.to_string(),
            "-ac",
            "1", // Mono
            "-f",
            "wav",
            output_str,
        ])?;

        if !output.success {
            return Err(CoreError::ExtractionError(format!(
                "Audio extraction failed: {}",
                output.stderr
            )));
        }

        Ok(())
    }

    /// Extract audio chunk at specific time
    fn extract_audio_chunk(
        &self,
        video_path: &Path,
        start_time: u32,
        duration: u32,
        output_path: &Path,
    ) -> CoreResult<()> {
        let video_str = video_path
            .to_str()
            .ok_or_else(|| CoreError::FileNotFound(format!("{:?}", video_path)))?;
        let output_str = output_path
            .to_str()
            .ok_or_else(|| CoreError::Other("Invalid output path".to_string()))?;

        let output = self.runner.run(&[
            "ffmpeg",
            "-y",
            "-ss",
            &start_time.to_string(),
            "-i",
            video_str,
            "-t",
            &duration.to_string(),
            "-vn",
            "-ar",
            &self.sample_rate.to_string(),
            "-ac",
            "1",
            "-f",
            "wav",
            output_str,
        ])?;

        if !output.success {
            return Err(CoreError::ExtractionError(format!(
                "Audio chunk extraction failed: {}",
                output.stderr
            )));
        }

        Ok(())
    }

    /// Read WAV file samples
    fn read_wav_samples(&self, wav_path: &Path) -> CoreResult<Vec<f32>> {
        let mut reader = hound::WavReader::open(wav_path)
            .map_err(|e| CoreError::ParseError(format!("WAV read error: {}", e)))?;

        let samples: Result<Vec<f32>, _> = reader.samples::<i16>().map(|s| {
            s.map(|sample| sample as f32 / i16::MAX as f32)
        }).collect();

        samples.map_err(|e| CoreError::ParseError(format!("WAV sample error: {}", e)))
    }

    /// Compute GCC-PHAT correlation
    fn gcc_phat_correlation(&self, ref_samples: &[f32], sec_samples: &[f32]) -> CorrelationResult {
        let n = ref_samples.len().max(sec_samples.len());
        let fft_size = n.next_power_of_two();

        // Zero-pad to FFT size
        let mut ref_padded = Array1::zeros(fft_size);
        let mut sec_padded = Array1::zeros(fft_size);

        for (i, &sample) in ref_samples.iter().enumerate() {
            ref_padded[i] = Complex::new(sample as f64, 0.0);
        }
        for (i, &sample) in sec_samples.iter().enumerate() {
            sec_padded[i] = Complex::new(sample as f64, 0.0);
        }

        // Create FFT planner
        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(fft_size);
        let ifft = planner.plan_fft_inverse(fft_size);

        // Compute FFTs
        let mut ref_fft = ref_padded.to_vec();
        let mut sec_fft = sec_padded.to_vec();

        fft.process(&mut ref_fft);
        fft.process(&mut sec_fft);

        // Compute cross-power spectrum: R1 * conj(R2)
        let mut cross_power: Vec<Complex<f64>> = ref_fft
            .iter()
            .zip(sec_fft.iter())
            .map(|(r1, r2)| r1 * r2.conj())
            .collect();

        // Phase Transform: normalize by magnitude
        for c in &mut cross_power {
            let mag = c.norm();
            if mag > 1e-10 {
                *c /= mag;
            }
        }

        // Inverse FFT to get correlation
        ifft.process(&mut cross_power);

        // Find peak
        let (delay_samples, peak_value, confidence) =
            self.find_peak_and_confidence(&cross_power, fft_size);

        let delay_ms = (delay_samples as f64 / self.sample_rate as f64) * 1000.0;

        CorrelationResult {
            delay_samples,
            delay_ms,
            confidence,
            peak_value,
            sample_rate: self.sample_rate,
        }
    }

    /// Compute standard cross-correlation (SCC)
    fn scc_correlation(&self, ref_samples: &[f32], sec_samples: &[f32]) -> CorrelationResult {
        let n = ref_samples.len().max(sec_samples.len());
        let fft_size = n.next_power_of_two();

        // Zero-pad to FFT size
        let mut ref_padded = Array1::zeros(fft_size);
        let mut sec_padded = Array1::zeros(fft_size);

        for (i, &sample) in ref_samples.iter().enumerate() {
            ref_padded[i] = Complex::new(sample as f64, 0.0);
        }
        for (i, &sample) in sec_samples.iter().enumerate() {
            sec_padded[i] = Complex::new(sample as f64, 0.0);
        }

        // Create FFT planner
        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(fft_size);
        let ifft = planner.plan_fft_inverse(fft_size);

        // Compute FFTs
        let mut ref_fft = ref_padded.to_vec();
        let mut sec_fft = sec_padded.to_vec();

        fft.process(&mut ref_fft);
        fft.process(&mut sec_fft);

        // Compute cross-power spectrum: R1 * conj(R2)
        let mut cross_power: Vec<Complex<f64>> = ref_fft
            .iter()
            .zip(sec_fft.iter())
            .map(|(r1, r2)| r1 * r2.conj())
            .collect();

        // Inverse FFT (no phase transform for SCC)
        ifft.process(&mut cross_power);

        // Find peak
        let (delay_samples, peak_value, confidence) =
            self.find_peak_and_confidence(&cross_power, fft_size);

        let delay_ms = (delay_samples as f64 / self.sample_rate as f64) * 1000.0;

        CorrelationResult {
            delay_samples,
            delay_ms,
            confidence,
            peak_value,
            sample_rate: self.sample_rate,
        }
    }

    /// Find correlation peak and compute confidence
    fn find_peak_and_confidence(
        &self,
        correlation: &[Complex<f64>],
        fft_size: usize,
    ) -> (i64, f64, f64) {
        // Get real magnitudes
        let magnitudes: Vec<f64> = correlation.iter().map(|c| c.norm()).collect();

        // Find peak
        let half_size = fft_size / 2;
        let mut peak_idx = 0;
        let mut peak_value = 0.0;

        for i in 0..fft_size {
            if magnitudes[i] > peak_value {
                peak_value = magnitudes[i];
                peak_idx = i;
            }
        }

        // Convert to signed delay (handle wrap-around)
        let delay_samples = if peak_idx > half_size {
            -(fft_size as i64 - peak_idx as i64)
        } else {
            peak_idx as i64
        };

        // Compute confidence: ratio of peak to mean
        let mean: f64 = magnitudes.iter().sum::<f64>() / magnitudes.len() as f64;
        let confidence = if mean > 1e-10 {
            (peak_value / mean).min(1.0)
        } else {
            0.0
        };

        (delay_samples, peak_value, confidence)
    }

    /// Analyze delay between two video files (chunked analysis)
    pub fn analyze_delay(
        &self,
        ref_path: &Path,
        sec_path: &Path,
        temp_dir: &Path,
    ) -> CoreResult<CorrelationResult> {
        let mut chunk_results = Vec::new();

        // Get video duration (simplified - assume we know it)
        // In practice, would use ffprobe to get duration

        for i in 0..self.chunk_count {
            // Calculate chunk start time (evenly spaced)
            let start_time = i * 60; // Every 60 seconds

            // Extract reference chunk
            let ref_chunk_path = temp_dir.join(format!("ref_chunk_{}.wav", i));
            self.extract_audio_chunk(ref_path, start_time, self.chunk_duration, &ref_chunk_path)?;

            // Extract secondary chunk
            let sec_chunk_path = temp_dir.join(format!("sec_chunk_{}.wav", i));
            self.extract_audio_chunk(sec_path, start_time, self.chunk_duration, &sec_chunk_path)?;

            // Read samples
            let ref_samples = self.read_wav_samples(&ref_chunk_path)?;
            let sec_samples = self.read_wav_samples(&sec_chunk_path)?;

            // Compute correlation
            let result = match self.method {
                CorrelationMethod::GccPhat => self.gcc_phat_correlation(&ref_samples, &sec_samples),
                CorrelationMethod::Scc => self.scc_correlation(&ref_samples, &sec_samples),
            };

            chunk_results.push(result);

            // Clean up temporary files
            let _ = std::fs::remove_file(&ref_chunk_path);
            let _ = std::fs::remove_file(&sec_chunk_path);
        }

        // Aggregate results (weighted average by confidence)
        let total_weight: f64 = chunk_results.iter().map(|r| r.confidence).sum();

        if total_weight < 1e-10 {
            return Err(CoreError::AnalysisError(
                "No confident correlation found".to_string(),
            ));
        }

        let weighted_delay: f64 = chunk_results
            .iter()
            .map(|r| r.delay_ms * r.confidence)
            .sum::<f64>()
            / total_weight;

        let avg_confidence: f64 = total_weight / chunk_results.len() as f64;

        // Find the result closest to weighted average
        let best_result = chunk_results
            .iter()
            .min_by(|a, b| {
                let diff_a = (a.delay_ms - weighted_delay).abs();
                let diff_b = (b.delay_ms - weighted_delay).abs();
                diff_a.partial_cmp(&diff_b).unwrap()
            })
            .cloned()
            .unwrap();

        Ok(CorrelationResult {
            delay_ms: weighted_delay,
            confidence: avg_confidence,
            ..best_result
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_correlation_method() {
        assert_eq!(CorrelationMethod::GccPhat, CorrelationMethod::GccPhat);
        assert_ne!(CorrelationMethod::GccPhat, CorrelationMethod::Scc);
    }

    #[test]
    fn test_correlation_result() {
        let result = CorrelationResult {
            delay_samples: 100,
            delay_ms: 2.0833,
            confidence: 0.95,
            peak_value: 1000.0,
            sample_rate: 48000,
        };

        assert_eq!(result.delay_samples, 100);
        assert!(result.confidence > 0.9);
    }
}
