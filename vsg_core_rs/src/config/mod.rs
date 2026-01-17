//! Configuration shell.
//!
//! Rust counterpart to `python/vsg_core/config.py`.
//!
//! This shell keeps the public API aligned with the Python `AppConfig` while the
//! underlying implementation remains embedded Python. The Rust layer owns the
//! wiring so UI and orchestration can call into a stable core without waiting
//! for a full port of configuration logic.

use pyo3::prelude::*;

#[pyclass]
pub struct AppConfig {
    inner: Py<PyAny>,
}

impl AppConfig {
    fn import_app_config(py: Python<'_>) -> PyResult<Py<PyAny>> {
        let module = py.import("vsg_core.config")?;
        let class = module.getattr("AppConfig")?;
        Ok(class.into_py(py))
    }

    fn call_method0(&self, py: Python<'_>, name: &str) -> PyResult<()> {
        self.inner.as_ref(py).call_method0(name)?;
        Ok(())
    }
}

#[pymethods]
impl AppConfig {
    #[new]
    #[pyo3(signature = (settings_filename = "settings.json".to_string()))]
    pub fn new(py: Python<'_>, settings_filename: String) -> PyResult<Self> {
        let class = Self::import_app_config(py)?;
        let instance = class.call1(py, (settings_filename,))?;
        Ok(Self { inner: instance })
    }

    /// Loads configuration from disk, applying migration and validation.
    pub fn load(&self, py: Python<'_>) -> PyResult<()> {
        self.call_method0(py, "load")
    }

    /// Saves configuration to disk.
    pub fn save(&self, py: Python<'_>) -> PyResult<()> {
        self.call_method0(py, "save")
    }

    /// Gets a configuration value with Python-compatible type coercion.
    #[pyo3(signature = (key, default = None))]
    pub fn get(&self, py: Python<'_>, key: String, default: Option<PyObject>) -> PyResult<PyObject> {
        let default = default.unwrap_or_else(|| py.None());
        let value = self
            .inner
            .as_ref(py)
            .call_method1("get", (key, default))?;
        Ok(value.into_py(py))
    }

    /// Sets a configuration value, respecting Python validation rules.
    pub fn set(&self, py: Python<'_>, key: String, value: PyObject) -> PyResult<()> {
        self.inner.as_ref(py).call_method1("set", (key, value))?;
        Ok(())
    }

    /// Returns accessed keys that are not in defaults (typo detection support).
    pub fn get_unrecognized_keys(&self, py: Python<'_>) -> PyResult<PyObject> {
        let result = self.inner.as_ref(py).call_method0("get_unrecognized_keys")?;
        Ok(result.into_py(py))
    }

    /// Ensures output/temp directories exist on disk.
    pub fn ensure_dirs_exist(&self, py: Python<'_>) -> PyResult<()> {
        self.call_method0(py, "ensure_dirs_exist")
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        self.inner.as_ref(py).repr()?.extract()
    }
}
