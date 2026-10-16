use browser_agent_cdp::CdpError;
use browser_agent_core::BrowserRuntimeError;
use pyo3::prelude::*;

struct SafeBrowserError {
    message: &'static str,
    native_error_type: &'static str,
    failure_kind: &'static str,
    recoverable: bool,
    cdp_code: Option<i64>,
    method: Option<&'static str>,
}

fn safe_error(
    message: &'static str,
    native_error_type: &'static str,
    failure_kind: &'static str,
    recoverable: bool,
) -> SafeBrowserError {
    SafeBrowserError {
        message,
        native_error_type,
        failure_kind,
        recoverable,
        cdp_code: None,
        method: None,
    }
}

fn safe_browser_error(error: &BrowserRuntimeError) -> SafeBrowserError {
    match error {
        BrowserRuntimeError::Cdp(CdpError::FrameDetached { .. })
        | BrowserRuntimeError::FrameDetached(_) => safe_error(
            "The browser frame detached during observation",
            "FRAME_DETACHED",
            "FRAME",
            true,
        ),
        BrowserRuntimeError::Cdp(CdpError::TargetClosed { .. })
        | BrowserRuntimeError::TargetClosed(_) => safe_error(
            "The attached browser tab is no longer available",
            "TARGET_CLOSED",
            "TAB",
            false,
        ),
        BrowserRuntimeError::CommandTimeout { method, .. }
        | BrowserRuntimeError::Cdp(CdpError::CommandTimeout { method, .. }) => {
            let mut safe = safe_error(
                "A browser protocol command timed out",
                "COMMAND_TIMEOUT",
                "TIMEOUT",
                true,
            );
            safe.method = allowed_observation_method(method);
            safe
        }
        BrowserRuntimeError::ProtocolError { code, .. } => {
            let mut safe = safe_error(
                "The browser rejected an observation protocol command",
                "PROTOCOL_ERROR",
                "EXECUTION",
                false,
            );
            safe.cdp_code = Some(*code);
            safe
        }
        BrowserRuntimeError::Cdp(CdpError::Protocol { code, .. }) => {
            let mut safe = safe_error(
                "The browser rejected an observation protocol command",
                "PROTOCOL_ERROR",
                "EXECUTION",
                false,
            );
            safe.cdp_code = Some(*code);
            safe
        }
        BrowserRuntimeError::NavigationFailed { .. } => safe_error(
            "Browser navigation failed",
            "NAVIGATION_FAILED",
            "NAVIGATION",
            true,
        ),
        BrowserRuntimeError::NoActiveTab | BrowserRuntimeError::Cdp(CdpError::NoPageTarget) => {
            safe_error(
                "The attached browser has no active tab",
                "NO_ACTIVE_TAB",
                "TAB",
                false,
            )
        }
        BrowserRuntimeError::InvalidResponse { method } => {
            let mut safe = safe_error(
                "The browser returned an invalid response to a protocol command",
                "INVALID_RESPONSE",
                "EXECUTION",
                false,
            );
            safe.method = allowed_observation_method(method);
            safe
        }
        BrowserRuntimeError::ConnectionLost
        | BrowserRuntimeError::BrowserExited
        | BrowserRuntimeError::Cdp(
            CdpError::ConnectionLost
            | CdpError::BrowserExited
            | CdpError::Shutdown
            | CdpError::WebSocket(_),
        ) => safe_error(
            "The browser connection ended during observation",
            "CONNECTION_LOST",
            "EXECUTION",
            false,
        ),
        BrowserRuntimeError::SessionClosed => safe_error(
            "The browser session is closed",
            "SESSION_CLOSED",
            "EXECUTION",
            false,
        ),
        BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(message)) => {
            safe_extension_bridge_error(message)
        }
        BrowserRuntimeError::Cdp(CdpError::Timeout(_)) => safe_error(
            "Browser observation timed out",
            "OBSERVATION_TIMEOUT",
            "TIMEOUT",
            true,
        ),
        _ => safe_error(
            "Browser observation failed",
            "BROWSER_RUNTIME_FAILURE",
            "UNKNOWN",
            false,
        ),
    }
}

fn safe_extension_bridge_error(message: &str) -> SafeBrowserError {
    if message.contains("recursion limit exceeded") {
        return safe_error(
            "The browser bridge response exceeded the supported JSON nesting limit",
            "BRIDGE_JSON_DEPTH_LIMIT",
            "EXECUTION",
            false,
        );
    }
    if message.contains("frame size is outside limits") {
        return safe_error(
            "The browser bridge response exceeded the supported message size",
            "BRIDGE_MESSAGE_TOO_LARGE",
            "EXECUTION",
            false,
        );
    }
    if message == "Debugger command or parameters are not allowlisted." {
        return safe_error(
            "The extension refused an unsupported browser command",
            "EXTENSION_COMMAND_REJECTED",
            "SAFETY",
            false,
        );
    }
    if message == "Command does not belong to the owned tab attachment." {
        return safe_error(
            "The extension refused a command for a different browser attachment",
            "EXTENSION_SESSION_MISMATCH",
            "TAB",
            false,
        );
    }
    if message == "extension debugger command timed out or disconnected" {
        return safe_error(
            "The extension debugger command timed out or disconnected",
            "EXTENSION_COMMAND_TIMEOUT",
            "TIMEOUT",
            true,
        );
    }
    safe_error(
        "The attached browser transport could not complete observation",
        "EXTENSION_BRIDGE_FAILURE",
        "EXECUTION",
        false,
    )
}

fn allowed_observation_method(method: &str) -> Option<&'static str> {
    match method {
        "Accessibility.getFullAXTree" => Some("Accessibility.getFullAXTree"),
        "DOM.describeNode" => Some("DOM.describeNode"),
        "DOM.getBoxModel" => Some("DOM.getBoxModel"),
        "DOM.getDocument" => Some("DOM.getDocument"),
        "DOM.resolveNode" => Some("DOM.resolveNode"),
        "DOMSnapshot.captureSnapshot" => Some("DOMSnapshot.captureSnapshot"),
        "Page.getLayoutMetrics" => Some("Page.getLayoutMetrics"),
        "Runtime.callFunctionOn" => Some("Runtime.callFunctionOn"),
        "Runtime.evaluate" => Some("Runtime.evaluate"),
        _ => None,
    }
}

pub(crate) fn map_browser_runtime_err(
    py: Python<'_>,
    operation: &'static str,
    error: BrowserRuntimeError,
) -> PyErr {
    let safe = safe_browser_error(&error);
    let py_error = pyo3::exceptions::PyRuntimeError::new_err(safe.message);
    let value = py_error.value(py);
    let _ = value.setattr("component", "browser_core");
    let _ = value.setattr("operation", operation);
    let _ = value.setattr("native_error_type", safe.native_error_type);
    let _ = value.setattr("failure_kind", safe.failure_kind);
    let _ = value.setattr("recoverable", safe.recoverable);
    if let Some(code) = safe.cdp_code {
        let _ = value.setattr("cdp_code", code);
    }
    if let Some(method) = safe.method {
        let _ = value.setattr("cdp_method", method);
    }
    py_error
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn extension_bridge_errors_are_sanitized_and_typed() {
        let error =
            BrowserRuntimeError::Cdp(CdpError::ExtensionBridge("private page text".to_string()));
        let safe = safe_browser_error(&error);

        assert_eq!(safe.native_error_type, "EXTENSION_BRIDGE_FAILURE");
        assert_eq!(safe.failure_kind, "EXECUTION");
        assert!(!safe.recoverable);
        assert!(!safe.message.contains("private page text"));
    }

    #[test]
    fn bridge_failures_get_specific_safe_categories() {
        let too_deep = BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
            "recursion limit exceeded at line 1 column 2".to_string(),
        ));
        let too_large = BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
            "bridge frame size is outside limits".to_string(),
        ));

        assert_eq!(
            safe_browser_error(&too_deep).native_error_type,
            "BRIDGE_JSON_DEPTH_LIMIT"
        );
        assert_eq!(
            safe_browser_error(&too_large).native_error_type,
            "BRIDGE_MESSAGE_TOO_LARGE"
        );
    }

    #[test]
    fn observation_timeout_exposes_only_allowlisted_methods() {
        let allowed = BrowserRuntimeError::CommandTimeout {
            method: "Runtime.evaluate".to_string(),
            timeout: Duration::from_secs(1),
        };
        let unlisted = BrowserRuntimeError::CommandTimeout {
            method: "Runtime.getProperties".to_string(),
            timeout: Duration::from_secs(1),
        };

        assert_eq!(
            safe_browser_error(&allowed).method,
            Some("Runtime.evaluate")
        );
        assert_eq!(safe_browser_error(&unlisted).method, None);
    }

    #[test]
    fn protocol_error_exposes_code_without_raw_message() {
        let error = BrowserRuntimeError::ProtocolError {
            code: -32000,
            message: "private page text".to_string(),
        };
        let safe = safe_browser_error(&error);

        assert_eq!(safe.native_error_type, "PROTOCOL_ERROR");
        assert_eq!(safe.cdp_code, Some(-32000));
        assert!(!safe.message.contains("private page text"));
    }
}
