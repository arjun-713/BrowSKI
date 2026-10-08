use crate::observer::hit_test_contains;
use crate::session::BrowserSession;
use browser_agent_cdp::{CdpSessionId, CdpTransport, TabId};
use browser_agent_executor::{ExecutionFailure, ExecutionFailureKind, MouseButton};
use browser_agent_observation::{BackendNodeId, SemanticKind};
use serde_json::Value;
use std::time::{Duration, Instant};

// ---------------------------------------------------------------------------
// CDP primitives
// ---------------------------------------------------------------------------

pub(super) async fn cmd(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    method: &str,
    params: Value,
) -> Result<Value, ExecutionFailure> {
    session
        .transport_pub()
        .await
        .command_in_session(cdp_session, method, params)
        .await
        .map_err(|e| {
            ExecutionFailure::new(
                ExecutionFailureKind::ActionTimeout,
                None,
                format!("{method} failed: {e}"),
            )
        })
}

pub(super) async fn scroll_into_view(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) {
    let _ = cmd(
        session,
        cdp_session,
        "DOM.scrollIntoViewIfNeeded",
        serde_json::json!({"backendNodeId": backend.get()}),
    )
    .await;
}

pub(super) async fn focus_backend(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) -> Result<(), ExecutionFailure> {
    cmd(
        session,
        cdp_session,
        "DOM.focus",
        serde_json::json!({"backendNodeId": backend.get()}),
    )
    .await
    .map(|_| ())
    .map_err(|_| {
        ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            None,
            "focus failed",
        )
    })
}

pub(super) async fn viewport_point(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) -> Result<(i64, i64), ExecutionFailure> {
    let res = cmd(
        session,
        cdp_session,
        "DOM.getBoxModel",
        serde_json::json!({"backendNodeId": backend.get()}),
    )
    .await?;
    let content = res
        .get("model")
        .and_then(|m| m.get("content"))
        .and_then(Value::as_array)
        .ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                None,
                "no box model",
            )
        })?;
    let nums: Vec<f64> = content.iter().filter_map(Value::as_f64).collect();
    if nums.len() != 8 {
        return Err(ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            None,
            "malformed box model",
        ));
    }
    let (x0, x1) = (
        nums[0].min(nums[2]).min(nums[4]).min(nums[6]),
        nums[0].max(nums[2]).max(nums[4]).max(nums[6]),
    );
    let (y0, y1) = (
        nums[1].min(nums[3]).min(nums[5]).min(nums[7]),
        nums[1].max(nums[3]).max(nums[5]).max(nums[7]),
    );
    // Chromium's box-model quads are already in viewport CSS coordinates.
    // Subtracting page scroll again misdirects both hit tests and input.
    Ok((
        ((x0 + x1) / 2.0).round() as i64,
        ((y0 + y1) / 2.0).round() as i64,
    ))
}

pub(super) async fn hit_passes(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
    x: i64,
    y: i64,
) -> bool {
    let transport = session.transport_pub().await;
    let topmost = transport
        .command_in_session(
            cdp_session,
            "DOM.getNodeForLocation",
            serde_json::json!({"x": x, "y": y}),
        )
        .await
        .ok()
        .and_then(|r| r.get("backendNodeId").and_then(Value::as_i64));
    match topmost {
        Some(t) if t == backend.get() => true,
        _ => hit_test_contains(transport.as_ref(), cdp_session, backend.get(), x, y).await,
    }
}

pub(super) async fn send_mouse(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    mouse_type: &str,
    (x, y): (i64, i64),
    button: &MouseButton,
    click_count: u32,
) -> Result<(), ExecutionFailure> {
    let button_str = match button {
        MouseButton::Left => "left",
        MouseButton::Middle => "middle",
        MouseButton::Right => "right",
    };
    cmd(
        session,
        cdp_session,
        "Input.dispatchMouseEvent",
        serde_json::json!({
            "type": mouse_type,
            "x": x, "y": y,
            "button": button_str,
            "clickCount": click_count,
        }),
    )
    .await
    .map(|_| ())
}

pub(super) async fn send_mouse_timeout(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    mouse_type: &str,
    (x, y): (i64, i64),
    button: &MouseButton,
    click_count: u32,
    timeout: Duration,
) -> Result<(), ExecutionFailure> {
    let button_str = match button {
        MouseButton::Left => "left",
        MouseButton::Middle => "middle",
        MouseButton::Right => "right",
    };
    session
        .transport_pub()
        .await
        .command_with_timeout(
            Some(cdp_session),
            "Input.dispatchMouseEvent",
            serde_json::json!({
                "type": mouse_type,
                "x": x, "y": y,
                "button": button_str,
                "clickCount": click_count,
            }),
            timeout,
        )
        .await
        .map(|_| ())
        .map_err(|e| {
            ExecutionFailure::new(
                ExecutionFailureKind::ActionTimeout,
                None,
                format!("Input.dispatchMouseEvent failed: {e}"),
            )
        })
}

/// Page-target count for popup-appearance probes (browser-level command,
/// unaffected by per-target input wedges).
pub(super) async fn count_page_targets(transport: &dyn CdpTransport) -> usize {
    transport
        .command("Target.getTargets", serde_json::json!({}))
        .await
        .ok()
        .and_then(|v| {
            v.get("targetInfos").and_then(Value::as_array).map(|infos| {
                infos
                    .iter()
                    .filter(|t| t.get("type").and_then(Value::as_str) == Some("page"))
                    .count()
            })
        })
        .unwrap_or(0)
}

pub(super) async fn new_page_target_appeared(transport: &dyn CdpTransport, before: usize) -> bool {
    count_page_targets(transport).await > before
}

pub(super) async fn press_key(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    key: &str,
) -> Result<(), ExecutionFailure> {
    let (windows_key_code, text) = key_code(key);
    for event_type in ["keyDown", "keyUp"] {
        let mut params = serde_json::json!({
            "type": event_type,
            "key": key,
            "windowsVirtualKeyCode": windows_key_code,
        });
        if event_type == "keyDown" {
            if let Some(t) = text {
                params["text"] = Value::from(t);
                params["unmodifiedText"] = Value::from(t);
            }
            if key == "Enter" {
                // Text events for Enter help editors/forms commit.
                params["text"] = Value::from("\r");
            }
        }
        // keyUp carries no text.
        cmd(session, cdp_session, "Input.dispatchKeyEvent", params).await?;
    }
    Ok(())
}

pub(super) fn key_code(key: &str) -> (i64, Option<&str>) {
    match key {
        "Enter" => (13, None),
        "Tab" => (9, None),
        "Escape" => (27, None),
        "Backspace" => (8, None),
        "Delete" => (46, None),
        "ArrowUp" => (38, None),
        "ArrowDown" => (40, None),
        "ArrowLeft" => (37, None),
        "ArrowRight" => (39, None),
        "Home" => (36, None),
        "End" => (35, None),
        "PageUp" => (33, None),
        "PageDown" => (34, None),
        " " => (32, Some(" ")),
        s if s.chars().count() == 1 => {
            let upper = s.to_uppercase();
            (upper.chars().next().map(|c| c as i64).unwrap_or(0), Some(s))
        }
        _ => (0, None),
    }
}

pub(super) async fn key_with_modifiers(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    key: &str,
    code: i64,
    modifiers: i64,
) -> Result<(), ExecutionFailure> {
    for event_type in ["keyDown", "keyUp"] {
        cmd(
            session,
            cdp_session,
            "Input.dispatchKeyEvent",
            serde_json::json!({
                "type": event_type,
                "key": key,
                "windowsVirtualKeyCode": code,
                "modifiers": modifiers,
            }),
        )
        .await?;
    }
    Ok(())
}

pub(super) async fn call_on_backend(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
    function: &str,
) -> Result<Value, ExecutionFailure> {
    call_on_backend_with_args(session, cdp_session, backend, function, &[]).await
}

pub(super) async fn call_on_backend_with_args(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
    function: &str,
    arguments: &[Value],
) -> Result<Value, ExecutionFailure> {
    let transport = session.transport_pub().await;
    let object_id = transport
        .command_in_session(
            cdp_session,
            "DOM.resolveNode",
            serde_json::json!({"backendNodeId": backend.get()}),
        )
        .await
        .map_err(|e| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                None,
                format!("resolveNode failed: {e}"),
            )
        })?
        .get("object")
        .and_then(|o| o.get("objectId"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                None,
                "resolveNode returned no object id",
            )
        })?;
    let res = transport
        .command_in_session(
            cdp_session,
            "Runtime.callFunctionOn",
            serde_json::json!({
                "objectId": object_id,
                "functionDeclaration": function,
                "arguments": arguments.iter().map(|value| {
                    serde_json::json!({"value": value})
                }).collect::<Vec<_>>(),
                "returnByValue": true,
                "awaitPromise": true,
            }),
        )
        .await
        .map_err(|e| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                None,
                format!("callFunctionOn failed: {e}"),
            )
        })?;
    if res.get("exceptionDetails").is_some() {
        return Err(ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            None,
            format!("page threw: {}", res["exceptionDetails"]),
        ));
    }
    Ok(res
        .get("result")
        .and_then(|r| r.get("value"))
        .cloned()
        .unwrap_or(Value::Null))
}

pub(super) async fn read_value(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
    role: &str,
    kind: &SemanticKind,
) -> Option<String> {
    let script = if role == "textbox"
        || matches!(kind, SemanticKind::TextInput | SemanticKind::OptionList)
    {
        include_str!("../mechanics/read-value.js")
    } else {
        include_str!("../mechanics/read-text.js")
    };
    call_on_backend(session, cdp_session, backend, script)
        .await
        .ok()
        .and_then(|v| v.as_str().map(str::to_string))
}

pub(super) async fn read_checked(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) -> Option<bool> {
    call_on_backend(
        session,
        cdp_session,
        backend,
        include_str!("../mechanics/read-checked.js"),
    )
    .await
    .ok()
    .and_then(|v| v.as_bool())
}

pub(super) async fn read_selected(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) -> Option<(String, String)> {
    let v = call_on_backend(
        session,
        cdp_session,
        backend,
        include_str!("../mechanics/read-selected.js"),
    )
    .await
    .ok()?;
    let s = v.as_str()?;
    let mut parts = s.splitn(2, '\u{0}');
    Some((
        parts.next().unwrap_or("").to_string(),
        parts.next().unwrap_or("").to_string(),
    ))
}

pub(super) async fn element_tag(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
) -> Option<String> {
    call_on_backend(
        session,
        cdp_session,
        backend,
        include_str!("../mechanics/element-tag.js"),
    )
    .await
    .ok()
    .and_then(|v| v.as_str().map(str::to_string))
}

pub(super) async fn read_scroll(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: Option<BackendNodeId>,
) -> Option<(i64, i64)> {
    match backend {
        Some(b) => call_on_backend(
            session,
            cdp_session,
            b,
            include_str!("../mechanics/read-scroll.js"),
        )
        .await
        .ok()
        .and_then(|v| v.as_str().map(str::to_string))
        .and_then(|s| {
            let mut parts = s.split(',');
            Some((parts.next()?.parse().ok()?, parts.next()?.parse().ok()?))
        }),
        None => session
            .evaluate_in(cdp_session, "window.scrollX + ',' + window.scrollY")
            .await
            .ok()
            .and_then(|v| {
                v.get("result")
                    .and_then(|r| r.get("value"))
                    .and_then(Value::as_str)
                    .map(str::to_string)
            })
            .and_then(|s| {
                let mut parts = s.split(',');
                Some((parts.next()?.parse().ok()?, parts.next()?.parse().ok()?))
            }),
    }
}

pub(super) async fn js_set_value(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    backend: BackendNodeId,
    text: &str,
) -> Result<(), ExecutionFailure> {
    // Native-setter path for controlled inputs (React): bypasses the plain
    // property assignment that frameworks ignore.
    call_on_backend_with_args(
        session,
        cdp_session,
        backend,
        include_str!("../mechanics/set-value.js"),
        &[serde_json::json!(text)],
    )
    .await
    .map(|_| ())
}

pub(super) async fn wait_for_evaluate(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    expression: &str,
    timeout: Duration,
) {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if session.dialog_open() {
            return;
        }
        let ok = probe_value(session, cdp_session, expression)
            .await
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if ok {
            return;
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
}

/// Bounded settle: stable (url, ready) twice in a row, or timeout.
/// Deliberately NOT network-idle (persistent polling breaks that rule).
/// Dialog-aware with short probes: evaluates hang while a JS dialog is
/// open, so bail immediately instead of burning full command timeouts.
pub(super) async fn settle(session: &BrowserSession, tab: &TabId) {
    let Ok((_, cdp_session)) = session.tab_session_pub(tab).await else {
        return;
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut last: Option<(String, String)> = None;
    let mut stable = 0u32;
    while Instant::now() < deadline {
        if session.dialog_open() {
            return;
        }
        let reading = probe_value(
            session,
            &cdp_session,
            "window.location.href + '|' + document.readyState",
        )
        .await
        .and_then(|v| v.as_str().map(str::to_string))
        .map(|s| {
            let mut parts = s.splitn(2, '|');
            (
                parts.next().unwrap_or("").to_string(),
                parts.next().unwrap_or("").to_string(),
            )
        });
        match (reading, &last) {
            (Some(r), Some(l)) if &r == l => {
                stable += 1;
                if stable >= 2 && r.1 == "complete" {
                    return;
                }
            }
            (Some(r), _) => {
                last = Some(r);
                stable = 0;
            }
            _ => {}
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// Short-timeout evaluate probe (2s). Returns the unwrapped value.
pub(super) async fn probe_value(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    expression: &str,
) -> Option<Value> {
    if session.dialog_open() {
        return None;
    }
    session
        .transport_pub()
        .await
        .command_with_timeout(
            Some(cdp_session),
            "Runtime.evaluate",
            serde_json::json!({"expression": expression, "returnByValue": true}),
            Duration::from_secs(2),
        )
        .await
        .ok()?
        .get("result")
        .and_then(|r| r.get("value"))
        .cloned()
}

pub(super) async fn wait_ready(
    session: &BrowserSession,
    cdp_session: &CdpSessionId,
    expect_url: Option<&str>,
) -> Result<(), ExecutionFailure> {
    // Reuse the navigate-grade readiness wait via a bounded poll.
    let timeout = Duration::from_secs(15);
    let start = Instant::now();
    while start.elapsed() < timeout {
        if session.dialog_open() {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::DialogBlocked,
                None,
                "dialog opened during navigation wait",
            ));
        }
        let state = probe_value(session, cdp_session, "document.readyState")
            .await
            .and_then(|v| v.as_str().map(str::to_string));
        let href = probe_value(session, cdp_session, "window.location.href")
            .await
            .and_then(|v| v.as_str().map(str::to_string));
        if href
            .as_deref()
            .is_some_and(|u| u.starts_with("chrome-error://"))
        {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::NavigationRace,
                None,
                format!("error page: {}", href.unwrap_or_default()),
            ));
        }
        let ready = state.as_deref() == Some("complete");
        let url_ok = match (expect_url, &href) {
            (Some(prefix), Some(u)) => u
                .trim_end_matches('/')
                .starts_with(prefix.trim_end_matches('/')),
            _ => true,
        };
        if ready && url_ok {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    Err(ExecutionFailure::new(
        ExecutionFailureKind::ActionTimeout,
        None,
        "readiness wait timed out",
    ))
}

// -- small helpers on SemanticElement -----------------------------------------
