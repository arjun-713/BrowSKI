//! PyO3 interface exposing the stable high-level Rust browser API to Python.
//!
//! Boundary: this crate exposes [`PyBrowserSession`] (launch / navigate /
//! observe / close) plus version helpers. It must NOT expose random
//! implementation details (no raw CDP handles, no websocket internals). The
//! Python package in `python/` wraps the synchronous API here in `asyncio`
//! helpers via `asyncio.to_thread`, so no async PyO3 machinery is required.
//!
//! API changes here follow `docs/protocols/versioning.md`.

use browser_agent_core::BrowserSession;
use pyo3::prelude::*;
use std::sync::{Mutex, OnceLock};
use tokio::runtime::Runtime;

fn runtime() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .thread_name("browser-agent-runtime")
            .build()
            .expect("failed to build tokio runtime for python bindings")
    })
}

fn map_err(e: impl std::fmt::Display) -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
}

/// Synchronous browser session handle (wrap with `asyncio.to_thread` on the
/// Python side to present an `async` API).
#[pyclass(name = "PyBrowserSession")]
pub struct PyBrowserSession {
    inner: Mutex<Option<BrowserSession>>,
}

#[pymethods]
impl PyBrowserSession {
    #[staticmethod]
    fn launch(headless: Option<bool>) -> PyResult<Self> {
        let headless = headless.unwrap_or(true);
        let session = runtime()
            .block_on(BrowserSession::launch_with_options(
                browser_agent_core::LaunchOptions {
                    headless,
                    ..Default::default()
                },
            ))
            .map_err(map_err)?;
        Ok(Self {
            inner: Mutex::new(Some(session)),
        })
    }

    fn navigate(&self, url: &str) -> PyResult<()> {
        let mut guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_mut().ok_or_else(|| map_err("session is closed"))?;
        runtime().block_on(session.navigate(url)).map_err(map_err)
    }

    /// Observe the current page state. Returns a JSON string encoding a
    /// `SemanticSnapshot` (schema v1; see the `observation` crate).
    fn observe_json(&self) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let snapshot = runtime().block_on(session.observe()).map_err(map_err)?;
        serde_json::to_string(&snapshot).map_err(map_err)
    }

    /// Execute one typed action and return its evidence-bearing outcome as
    /// JSON. Action mechanics and verification remain in the Rust core.
    fn act_json(&self, tab_id: &str, action_json: &str) -> PyResult<String> {
        let action: browser_agent_core::BrowserAction =
            serde_json::from_str(action_json).map_err(map_err)?;
        let tab = browser_agent_core::TabId::from(tab_id);
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let outcome = runtime().block_on(session.act(
            &tab,
            action,
            browser_agent_core::ActOptions::default(),
        ));
        serde_json::to_string(&outcome).map_err(map_err)
    }

    fn session_id(&self) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        guard
            .as_ref()
            .map(|s| s.session_id().to_string())
            .ok_or_else(|| map_err("session is closed"))
    }

    fn generation(&self) -> PyResult<u64> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        guard
            .as_ref()
            .map(|s| s.generation())
            .ok_or_else(|| map_err("session is closed"))
    }

    /// List tabs as JSON (`Vec<TabInfo>`).
    fn tabs_json(&self) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let tabs = runtime().block_on(session.tabs());
        serde_json::to_string(&tabs).map_err(map_err)
    }

    fn active_tab_id(&self) -> PyResult<Option<String>> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let tab = runtime().block_on(session.active_tab());
        Ok(tab.map(|t| t.id.to_string()))
    }

    /// Model-facing rendered observation (`@ref` blocks) for a tab.
    fn render_observation(&self, tab_id: &str, memory_refs: Vec<String>) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let tab = browser_agent_core::TabId::from(tab_id);
        let refs: std::collections::HashSet<String> = memory_refs.into_iter().collect();
        runtime()
            .block_on(session.render_observation(&tab, &refs))
            .map_err(map_err)
    }

    /// Incremental delta vs the previous snapshot of a tab (JSON).
    fn observe_delta_json(&self, tab_id: &str) -> PyResult<String> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let tab = browser_agent_core::TabId::from(tab_id);
        let delta = runtime()
            .block_on(session.observe_delta(&tab))
            .map_err(map_err)?;
        serde_json::to_string(&delta).map_err(map_err)
    }

    /// Resolve a model-facing alias to its registry identity (JSON) or None.
    fn resolve_json(&self, tab_id: &str, alias: &str) -> PyResult<Option<String>> {
        let guard = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?;
        let session = guard.as_ref().ok_or_else(|| map_err("session is closed"))?;
        let tab = browser_agent_core::TabId::from(tab_id);
        let resolved = runtime().block_on(session.resolve(&tab, alias));
        resolved
            .map(|r| serde_json::to_string(&r).map_err(map_err))
            .transpose()
    }

    fn close(&self) -> PyResult<()> {
        let session = self
            .inner
            .lock()
            .map_err(|_| map_err("session lock poisoned"))?
            .take();
        if let Some(session) = session {
            runtime().block_on(session.close()).map_err(map_err)?;
        }
        Ok(())
    }

    fn __enter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __exit__(
        &self,
        _exc_type: &Bound<'_, PyAny>,
        _exc: &Bound<'_, PyAny>,
        _tb: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        self.close()?;
        Ok(false)
    }
}

#[pyfunction]
fn core_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Native extension module. The maturin `module-name` is
/// `browser_agent._core`, so Python imports this as
/// `browser_agent._core`.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyBrowserSession>()?;
    m.add_function(wrap_pyfunction!(core_version, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
