//! Structured runtime events, timing, and trace records.
//!
//! Boundary: this crate defines the [`TraceEvent`] envelope and helpers for
//! emitting structured events. It performs no browser I/O and no LLM calls.
//! See `README.md` and `docs/protocols/versioning.md` (trace schema versions).

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

/// Schema version for serialized trace events. Bump with migration notes in
/// `docs/protocols/versioning.md`.
pub const TRACE_SCHEMA_VERSION: u32 = 1;

/// A single structured runtime event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceEvent {
    /// Schema version (see [`TRACE_SCHEMA_VERSION`]).
    pub schema_version: u32,
    /// Monotonic-ish millisecond timestamp (unix epoch).
    pub ts_ms: u64,
    /// Short event kind, e.g. `browser.navigate.start`.
    pub kind: String,
    /// Human-readable message.
    pub message: String,
    /// Session/run correlation id, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    /// Arbitrary structured fields.
    #[serde(default)]
    pub fields: HashMap<String, serde_json::Value>,
}

impl TraceEvent {
    pub fn new(kind: impl Into<String>, message: impl Into<String>) -> Self {
        let ts_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0);
        Self {
            schema_version: TRACE_SCHEMA_VERSION,
            ts_ms,
            kind: kind.into(),
            message: message.into(),
            session_id: None,
            fields: HashMap::new(),
        }
    }

    pub fn with_session(mut self, session_id: impl Into<String>) -> Self {
        self.session_id = Some(session_id.into());
        self
    }

    pub fn with_field(mut self, key: impl Into<String>, value: serde_json::Value) -> Self {
        self.fields.insert(key.into(), value);
        self
    }

    /// Emit via `tracing` at INFO level as JSON.
    pub fn emit(&self) {
        match serde_json::to_string(self) {
            Ok(json) => tracing::info!(target: "browser_agent::trace", "{json}"),
            Err(e) => tracing::warn!("failed to serialize trace event: {e}"),
        }
    }
}

/// Initialize process-wide tracing subscriber (idempotent-ish: ignores error if
/// a global subscriber is already set, e.g. under tests).
pub fn init_tracing() {
    use tracing_subscriber::{fmt, EnvFilter};
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let _ = fmt().with_env_filter(filter).try_init();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trace_event_serializes_with_schema_version() {
        let ev = TraceEvent::new("test.kind", "hello").with_session("s1");
        let v = serde_json::to_value(&ev).unwrap();
        assert_eq!(v["schema_version"], 1);
        assert_eq!(v["kind"], "test.kind");
        assert_eq!(v["session_id"], "s1");
    }
}
