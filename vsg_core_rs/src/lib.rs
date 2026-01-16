// src/lib.rs
use pyo3::prelude::*;

mod models;

#[pymodule]
fn vsg_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Enums
    m.add_class::<models::enums::TrackType>()?;
    m.add_class::<models::enums::AnalysisMode>()?;
    m.add_class::<models::enums::SnapMode>()?;
    m.add_class::<models::enums::StepStatus>()?;
    m.add_class::<models::enums::CorrectionVerdict>()?;

    // Media
    m.add_class::<models::media::StreamProps>()?;
    m.add_class::<models::media::Track>()?;

    // Results
    m.add_class::<models::results::StepResult>()?;
    m.add_class::<models::results::CorrectionResult>()?;

    // Jobs
    m.add_class::<models::jobs::Delays>()?;
    m.add_class::<models::jobs::PlanItem>()?;

    // Settings
    m.add_class::<models::settings::AppSettings>()?;

    // Converter functions
    m.add_function(wrap_pyfunction!(models::converters::track_type_from_str, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::track_type_to_str, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::round_delay_ms, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::nanoseconds_to_ms, m)?)?;

    Ok(())
}
