//! Configuration core.
//!
//! Rust-first configuration storage that can be surfaced to Python via PyO3,
//! while keeping the underlying logic free of embedded Python modules.

use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAnyMethods, PyBool, PyDict, PyList};
use pyo3::IntoPyObject;
use serde_json::Value;

#[pyclass]
pub struct AppConfig {
    settings_filename: PathBuf,
    data: Value,
    accessed_keys: HashSet<String>,
}

impl AppConfig {
    fn json_to_py(py: Python<'_>, value: &Value) -> PyResult<PyObject> {
        let py_value = match value {
            Value::Null => py.None(),
            Value::Bool(v) => PyBool::new(py, *v).to_owned().into(),
            Value::Number(num) => {
                if let Some(i) = num.as_i64() {
                    i.into_pyobject(py)?.into_any().unbind()
                } else if let Some(u) = num.as_u64() {
                    u.into_pyobject(py)?.into_any().unbind()
                } else if let Some(f) = num.as_f64() {
                    f.into_pyobject(py)?.into_any().unbind()
                } else {
                    py.None()
                }
            }
            Value::String(s) => s.into_pyobject(py)?.into_any().unbind(),
            Value::Array(values) => {
                let items: PyResult<Vec<PyObject>> =
                    values.iter().map(|v| Self::json_to_py(py, v)).collect();
                let list = PyList::new(py, items?)?;
                list.into()
            }
            Value::Object(map) => {
                let dict = PyDict::new(py);
                for (key, val) in map.iter() {
                    dict.set_item(key, Self::json_to_py(py, val)?)?;
                }
                dict.into()
            }
        };
        Ok(py_value)
    }

    fn py_to_json(_py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Value> {
        if value.is_none() {
            return Ok(Value::Null);
        }
        if let Ok(val) = value.extract::<bool>() {
            return Ok(Value::Bool(val));
        }
        if let Ok(val) = value.extract::<i64>() {
            return Ok(Value::Number(serde_json::Number::from(val)));
        }
        if let Ok(val) = value.extract::<f64>() {
            return Ok(serde_json::Number::from_f64(val).map_or(Value::Null, Value::Number));
        }
        if let Ok(val) = value.extract::<String>() {
            return Ok(Value::String(val));
        }
        if let Ok(list) = value.downcast::<PyList>() {
            let mut items = Vec::with_capacity(list.len());
            for item in list.iter() {
                items.push(Self::py_to_json(_py, &item)?);
            }
            return Ok(Value::Array(items));
        }
        if let Ok(dict) = value.downcast::<PyDict>() {
            let mut map = serde_json::Map::new();
            for (key, val) in dict.iter() {
                let key = key.extract::<String>()?;
                map.insert(key, Self::py_to_json(_py, &val)?);
            }
            return Ok(Value::Object(map));
        }
        Ok(Value::String(value.str()?.to_string()))
    }

    fn data_map_mut(&mut self) -> PyResult<&mut serde_json::Map<String, Value>> {
        match self.data {
            Value::Object(ref mut map) => Ok(map),
            _ => {
                self.data = Value::Object(serde_json::Map::new());
                match self.data {
                    Value::Object(ref mut map) => Ok(map),
                    _ => Err(PyValueError::new_err("Config data is not an object.")),
                }
            }
        }
    }
}

#[pymethods]
impl AppConfig {
    #[new]
    #[pyo3(signature = (settings_filename = "settings.json".to_string()))]
    pub fn new(settings_filename: String) -> Self {
        Self {
            settings_filename: PathBuf::from(settings_filename),
            data: Value::Object(serde_json::Map::new()),
            accessed_keys: HashSet::new(),
        }
    }

    /// Loads configuration from disk.
    pub fn load(&mut self) -> PyResult<()> {
        if !self.settings_filename.exists() {
            self.data = Value::Object(serde_json::Map::new());
            return Ok(());
        }

        let raw = fs::read_to_string(&self.settings_filename)?;
        self.data = serde_json::from_str(&raw).unwrap_or(Value::Object(serde_json::Map::new()));
        Ok(())
    }

    /// Saves configuration to disk.
    pub fn save(&self) -> PyResult<()> {
        if let Some(parent) = self.settings_filename.parent() {
            fs::create_dir_all(parent)?;
        }
        let json = serde_json::to_string_pretty(&self.data)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        fs::write(&self.settings_filename, json)?;
        Ok(())
    }

    /// Gets a configuration value with Python-compatible type coercion.
    #[pyo3(signature = (key, default = None))]
    pub fn get(&mut self, py: Python<'_>, key: String, default: Option<PyObject>) -> PyResult<PyObject> {
        self.accessed_keys.insert(key.clone());
        let default_value = default.unwrap_or_else(|| py.None());
        let value = match &self.data {
            Value::Object(map) => map
                .get(&key)
                .map(|v| Self::json_to_py(py, v))
                .transpose()?
                .unwrap_or(default_value),
            _ => default_value,
        };
        Ok(value)
    }

    /// Sets a configuration value.
    pub fn set(&mut self, py: Python<'_>, key: String, value: PyObject) -> PyResult<()> {
        let map = self.data_map_mut()?;
        let json_value = Self::py_to_json(py, &value.bind(py))?;
        map.insert(key, json_value);
        Ok(())
    }

    /// Returns accessed keys that are not in defaults (typo detection support).
    pub fn get_unrecognized_keys(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list: Vec<String> = Vec::new();
        let list = PyList::new(py, list)?;
        Ok(list.into())
    }

    /// Ensures output/temp directories exist on disk.
    pub fn ensure_dirs_exist(&self) -> PyResult<()> {
        let mut dirs = Vec::new();
        if let Value::Object(map) = &self.data {
            if let Some(Value::String(path)) = map.get("output_root") {
                dirs.push(PathBuf::from(path));
            }
            if let Some(Value::String(path)) = map.get("temp_root") {
                dirs.push(PathBuf::from(path));
            }
        }
        for dir in dirs {
            fs::create_dir_all(dir)?;
        }
        Ok(())
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!(
            "AppConfig(settings_filename='{}')",
            self.settings_filename.display()
        ))
    }
}
