// src/models/media.rs
use pyo3::prelude::*;
use super::enums::TrackType;

#[pyclass]
#[derive(Clone, Debug)]
pub struct StreamProps {
    #[pyo3(get, set)]
    pub codec_id: String,
    #[pyo3(get, set)]
    pub language: Option<String>,
    #[pyo3(get, set)]
    pub track_name: Option<String>,
    #[pyo3(get, set)]
    pub audio_channels: Option<u32>,
    #[pyo3(get, set)]
    pub audio_sampling_frequency: Option<u32>,
}

#[pymethods]
impl StreamProps {
    #[new]
    #[pyo3(signature = (codec_id, language=None, track_name=None, audio_channels=None, audio_sampling_frequency=None))]
    fn new(
        codec_id: String,
        language: Option<String>,
        track_name: Option<String>,
        audio_channels: Option<u32>,
        audio_sampling_frequency: Option<u32>,
    ) -> Self {
        StreamProps {
            codec_id,
            language,
            track_name,
            audio_channels,
            audio_sampling_frequency,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "StreamProps(codec_id='{}', language={:?}, track_name={:?}, audio_channels={:?}, audio_sampling_frequency={:?})",
            self.codec_id, self.language, self.track_name, self.audio_channels, self.audio_sampling_frequency
        )
    }
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct Track {
    #[pyo3(get, set)]
    pub id: u32,
    #[pyo3(get, set)]
    pub track_type: TrackType,
    #[pyo3(get, set)]
    pub props: StreamProps,
    #[pyo3(get, set)]
    pub container_delay_ms: i32,  // CRITICAL: Must be i32, not u32 (can be negative)
}

#[pymethods]
impl Track {
    #[new]
    fn new(id: u32, track_type: TrackType, props: StreamProps, container_delay_ms: i32) -> Self {
        Track {
            id,
            track_type,
            props,
            container_delay_ms,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Track(id={}, track_type={:?}, container_delay_ms={})",
            self.id, self.track_type, self.container_delay_ms
        )
    }
}
