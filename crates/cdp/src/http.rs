//! HTTP debugger endpoints (`/json/version`, `/json/list`, `/json/new`,
//! `/json/close`, `/json/activate`).
//!
//! Used for discovery and target management. All steady-state commanding
//! goes through [`crate::transport::PersistentTransport`]; HTTP is not on
//! any hot path.

use crate::error::CdpError;
use crate::ids::TargetId;
use serde::{Deserialize, Serialize};

/// A debugger target from `/json/list`.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DebuggerTarget {
    pub id: String,
    pub title: String,
    pub url: String,
    #[serde(rename = "type")]
    pub target_type: String,
    pub web_socket_debugger_url: Option<String>,
}

/// Browser-level websocket URL from `/json/version`.
pub async fn browser_ws_url(base_url: &str) -> Result<String, CdpError> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{base_url}/json/version"))
        .send()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))?;
    let v: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))?;
    v.get("webSocketDebuggerUrl")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| CdpError::Unexpected("missing webSocketDebuggerUrl".into()))
}

/// List debugger targets.
pub async fn list_targets(base_url: &str) -> Result<Vec<DebuggerTarget>, CdpError> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{base_url}/json/list"))
        .send()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))?;
    resp.json::<Vec<DebuggerTarget>>()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))
}

/// Open a new blank page target and return it.
pub async fn new_page_target(base_url: &str) -> Result<DebuggerTarget, CdpError> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{base_url}/json/new?about:blank"))
        .send()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))?;
    resp.json::<DebuggerTarget>()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))
}

/// Close a target over HTTP (used by tests to simulate *external* tab close;
/// in-session closes use `Target.closeTarget` on the transport).
pub async fn close_target_http(base_url: &str, target: &TargetId) -> Result<(), CdpError> {
    let client = reqwest::Client::new();
    client
        .get(format!("{base_url}/json/close/{}", target.as_str()))
        .send()
        .await
        .map_err(|e| CdpError::Http(e.to_string()))?;
    Ok(())
}
