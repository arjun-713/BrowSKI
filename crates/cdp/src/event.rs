//! Typed CDP events.
//!
//! The transport delivers raw protocol messages; this module parses the
//! event half (messages without an `id`) into [`CdpEvent`]. Unknown methods
//! are preserved as [`CdpEvent::Unknown`] so protocol upgrades never break
//! parsing — the reader stays alive and typed handling degrades gracefully.

use crate::ids::{CdpSessionId, FrameId, TargetId};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Summary of a debugger target (`Target.targetCreated/InfoChanged` params).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TargetSummary {
    pub target_id: TargetId,
    #[serde(rename = "type")]
    pub target_type: String,
    pub title: String,
    pub url: String,
    pub attached: bool,
    #[serde(default)]
    pub opener_id: Option<TargetId>,
}

/// Frame info (`Page.frameNavigated` params' `frame` object).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrameSummary {
    pub id: FrameId,
    #[serde(default)]
    pub parent_id: Option<FrameId>,
    pub url: String,
    #[serde(default)]
    pub name: Option<String>,
}

/// Typed CDP event. `session` is the flattened session the event arrived on
/// (`None` for browser-level events such as `Target.*`).
#[derive(Debug, Clone)]
pub enum CdpEvent {
    AttachedToTarget {
        session: CdpSessionId,
        target: TargetSummary,
    },
    DetachedFromTarget {
        session: CdpSessionId,
        target: Option<TargetId>,
    },
    TargetCreated {
        target: TargetSummary,
    },
    TargetDestroyed {
        target_id: TargetId,
    },
    TargetInfoChanged {
        target: TargetSummary,
    },
    FrameAttached {
        session: CdpSessionId,
        frame_id: FrameId,
        parent_frame_id: FrameId,
    },
    FrameDetached {
        session: CdpSessionId,
        frame_id: FrameId,
        reason: String,
    },
    FrameNavigated {
        session: CdpSessionId,
        frame: FrameSummary,
    },
    FrameStartedLoading {
        session: CdpSessionId,
        frame_id: FrameId,
    },
    FrameStoppedLoading {
        session: CdpSessionId,
        frame_id: FrameId,
    },
    LoadEventFired {
        session: CdpSessionId,
    },
    DialogOpening {
        session: CdpSessionId,
        dialog_type: String,
        message: String,
        url: String,
    },
    DialogClosed {
        session: CdpSessionId,
    },
    DownloadWillBegin {
        session: CdpSessionId,
        guid: String,
        url: String,
        suggested_filename: String,
    },
    DownloadProgress {
        session: CdpSessionId,
        guid: String,
        state: String,
    },
    TargetCrashed {
        session: Option<CdpSessionId>,
        status: String,
        error_code: i64,
    },
    ExecutionContextsCleared {
        session: CdpSessionId,
    },
    /// The underlying transport died. Terminal for all pending commands.
    ConnectionLost,
    Unknown {
        method: String,
    },
}

fn get<'a>(params: &'a Value, key: &str) -> &'a Value {
    params.get(key).unwrap_or(&Value::Null)
}

fn str_field(params: &Value, key: &str) -> String {
    get(params, key).as_str().unwrap_or("").to_string()
}

fn session_of(envelope: &Value) -> Option<CdpSessionId> {
    envelope
        .get("sessionId")
        .and_then(Value::as_str)
        .map(CdpSessionId::from)
}

fn parse_target(params: &Value) -> Option<TargetSummary> {
    let info = if params.get("targetInfo").is_some() {
        &params["targetInfo"]
    } else {
        params
    };
    serde_json::from_value(info.clone()).ok()
}

impl CdpEvent {
    /// Parse one protocol event envelope:
    /// `{"method": "...", "params": {...}, "sessionId"?}`.
    pub fn parse(envelope: &Value) -> Self {
        let method = envelope.get("method").and_then(Value::as_str).unwrap_or("");
        let params = envelope.get("params").unwrap_or(&Value::Null);
        let session = || session_of(envelope).unwrap_or_else(|| CdpSessionId::from(""));
        match method {
            // NOTE: attach/detach carry the session id inside `params`
            // (`params.sessionId`), unlike session-scoped events where it
            // rides on the envelope. Parsing the wrong level binds an empty
            // session and every later command fails with "wasn't found".
            "Target.attachedToTarget" => {
                let session = params
                    .get("sessionId")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                match parse_target(&params["targetInfo"]) {
                    Some(target) => CdpEvent::AttachedToTarget {
                        session: CdpSessionId::from(session),
                        target,
                    },
                    None => CdpEvent::Unknown {
                        method: method.into(),
                    },
                }
            }
            "Target.detachedFromTarget" => CdpEvent::DetachedFromTarget {
                session: CdpSessionId::from(
                    params
                        .get("sessionId")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                ),
                target: params
                    .get("targetId")
                    .and_then(Value::as_str)
                    .map(TargetId::from),
            },
            "Target.targetCreated" => match parse_target(&params["targetInfo"]) {
                Some(target) => CdpEvent::TargetCreated { target },
                None => CdpEvent::Unknown {
                    method: method.into(),
                },
            },
            "Target.targetDestroyed" => CdpEvent::TargetDestroyed {
                target_id: TargetId::from(str_field(params, "targetId")),
            },
            "Target.targetInfoChanged" => match parse_target(&params["targetInfo"]) {
                Some(target) => CdpEvent::TargetInfoChanged { target },
                None => CdpEvent::Unknown {
                    method: method.into(),
                },
            },
            "Page.frameAttached" => CdpEvent::FrameAttached {
                session: session(),
                frame_id: FrameId::from(str_field(params, "frameId")),
                parent_frame_id: FrameId::from(str_field(params, "parentFrameId")),
            },
            "Page.frameDetached" => CdpEvent::FrameDetached {
                session: session(),
                frame_id: FrameId::from(str_field(params, "frameId")),
                reason: str_field(params, "reason"),
            },
            "Page.frameNavigated" => {
                match serde_json::from_value::<FrameSummary>(params["frame"].clone()) {
                    Ok(frame) => CdpEvent::FrameNavigated {
                        session: session(),
                        frame,
                    },
                    Err(_) => CdpEvent::Unknown {
                        method: method.into(),
                    },
                }
            }
            "Page.frameStartedLoading" => CdpEvent::FrameStartedLoading {
                session: session(),
                frame_id: FrameId::from(str_field(params, "frameId")),
            },
            "Page.frameStoppedLoading" => CdpEvent::FrameStoppedLoading {
                session: session(),
                frame_id: FrameId::from(str_field(params, "frameId")),
            },
            "Page.loadEventFired" => CdpEvent::LoadEventFired { session: session() },
            "Page.javascriptDialogOpening" => CdpEvent::DialogOpening {
                session: session(),
                dialog_type: str_field(params, "type"),
                message: str_field(params, "message"),
                url: str_field(params, "url"),
            },
            "Page.javascriptDialogClosed" => CdpEvent::DialogClosed { session: session() },
            "Browser.downloadWillBegin" => CdpEvent::DownloadWillBegin {
                session: session(),
                guid: str_field(params, "guid"),
                url: str_field(params, "url"),
                suggested_filename: str_field(params, "suggestedFilename"),
            },
            "Browser.downloadProgress" => CdpEvent::DownloadProgress {
                session: session(),
                guid: str_field(params, "guid"),
                state: str_field(params, "state"),
            },
            "Inspector.targetCrashed" => CdpEvent::TargetCrashed {
                session: session_of(envelope),
                status: String::new(),
                error_code: params.get("errorCode").and_then(Value::as_i64).unwrap_or(0),
            },
            "Runtime.executionContextsCleared" => {
                CdpEvent::ExecutionContextsCleared { session: session() }
            }
            _ => CdpEvent::Unknown {
                method: method.into(),
            },
        }
    }

    /// Short label for metrics/dispatch timing.
    pub fn kind(&self) -> &'static str {
        match self {
            CdpEvent::AttachedToTarget { .. } => "Target.attachedToTarget",
            CdpEvent::DetachedFromTarget { .. } => "Target.detachedFromTarget",
            CdpEvent::TargetCreated { .. } => "Target.targetCreated",
            CdpEvent::TargetDestroyed { .. } => "Target.targetDestroyed",
            CdpEvent::TargetInfoChanged { .. } => "Target.targetInfoChanged",
            CdpEvent::FrameAttached { .. } => "Page.frameAttached",
            CdpEvent::FrameDetached { .. } => "Page.frameDetached",
            CdpEvent::FrameNavigated { .. } => "Page.frameNavigated",
            CdpEvent::FrameStartedLoading { .. } => "Page.frameStartedLoading",
            CdpEvent::FrameStoppedLoading { .. } => "Page.frameStoppedLoading",
            CdpEvent::LoadEventFired { .. } => "Page.loadEventFired",
            CdpEvent::DialogOpening { .. } => "Page.javascriptDialogOpening",
            CdpEvent::DialogClosed { .. } => "Page.javascriptDialogClosed",
            CdpEvent::DownloadWillBegin { .. } => "Browser.downloadWillBegin",
            CdpEvent::DownloadProgress { .. } => "Browser.downloadProgress",
            CdpEvent::TargetCrashed { .. } => "Inspector.targetCrashed",
            CdpEvent::ExecutionContextsCleared { .. } => "Runtime.executionContextsCleared",
            CdpEvent::ConnectionLost => "(connection-lost)",
            CdpEvent::Unknown { .. } => "(unknown)",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_frame_navigated_and_unknown() {
        let frame = CdpEvent::parse(&json!({
            "sessionId": "S1",
            "method": "Page.frameNavigated",
            "params": {"frame": {"id": "F1", "url": "https://example.com/"}}
        }));
        assert!(matches!(frame, CdpEvent::FrameNavigated { .. }));

        let unknown = CdpEvent::parse(&json!({
            "method": "Some.futureEvent", "params": {}
        }));
        assert!(matches!(unknown, CdpEvent::Unknown { .. }));
    }

    #[test]
    fn parses_target_lifecycle() {
        let created = CdpEvent::parse(&json!({
            "method": "Target.targetCreated",
            "params": {"targetInfo": {
                "targetId": "T1", "type": "page", "title": "",
                "url": "about:blank", "attached": false
            }}
        }));
        assert!(matches!(created, CdpEvent::TargetCreated { .. }));
        let destroyed = CdpEvent::parse(&json!({
            "method": "Target.targetDestroyed",
            "params": {"targetId": "T1"}
        }));
        assert!(matches!(destroyed, CdpEvent::TargetDestroyed { .. }));
    }
}
