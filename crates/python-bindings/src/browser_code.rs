//! Narrow binding adapter for the isolated semantic-data transform capability.

use browser_agent_code::{transform_snapshot as run_transform, BrowserCodeError};
use browser_agent_observation::SemanticSnapshot;
use pyo3::prelude::*;

pub(crate) fn transform_snapshot(
    snapshot: &SemanticSnapshot,
    script: &str,
    timeout_ms: u64,
    max_result_bytes: usize,
) -> PyResult<String> {
    let result =
        run_transform(snapshot, script, timeout_ms, max_result_bytes).map_err(|error| {
            if error == BrowserCodeError::Timeout {
                pyo3::exceptions::PyTimeoutError::new_err(error.to_string())
            } else {
                pyo3::exceptions::PyRuntimeError::new_err(error.to_string())
            }
        })?;
    serde_json::to_string(&result).map_err(|_| {
        pyo3::exceptions::PyRuntimeError::new_err("could not serialize transform result")
    })
}
