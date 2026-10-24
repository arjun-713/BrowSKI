//! Native `_blank` links retain actual click semantics on the attached backend.

use super::cdp::{call_on_backend, send_mouse, send_mouse_timeout};
use super::ResolvedTarget;
use crate::session::BrowserSession;
use browser_agent_executor::{
    ExecutionEvidence, ExecutionFailure, ExecutionFailureKind, MouseButton,
};
use std::time::Duration;

pub(super) async fn click_expected_popup(
    session: &BrowserSession,
    target: &ResolvedTarget,
    point: (i64, i64),
    button: &MouseButton,
    click_count: u32,
) -> Result<Option<ExecutionEvidence>, ExecutionFailure> {
    let transport = session.transport_pub().await;
    if !transport.supports_owned_popups()
        || !matches!(button, MouseButton::Left)
        || click_count > 1
        || target.element.role != "link"
    {
        return Ok(None);
    }
    let metadata = call_on_backend(
        session,
        &target.session,
        target.backend,
        include_str!("../mechanics/popup-link.js"),
    )
    .await?;
    let Some(url) = metadata.as_str() else {
        return Ok(None);
    };
    let popup_id = transport
        .prepare_owned_popup(&target.session, url)
        .await
        .map_err(|_| popup_failure(target, "the native link popup could not be prepared"))?;

    let press = send_mouse(session, &target.session, "mousePressed", point, button, 1).await;
    if let Err(error) = press {
        // No pending intent may survive failed input and match a later user click.
        let _ = transport.finish_owned_popup(&popup_id, true).await;
        return Err(error);
    }
    let release = send_mouse_timeout(
        session,
        &target.session,
        "mouseReleased",
        point,
        button,
        1,
        Duration::from_secs(5),
    )
    .await;
    let owned = transport
        .finish_owned_popup(&popup_id, false)
        .await
        .map_err(|_| {
            popup_failure(
                target,
                "the native popup did not match its bounded attachment intent",
            )
        })?
        .ok_or_else(|| popup_failure(target, "the expected native popup is unavailable"))?;
    let tab = session
        .adopt_owned_tab(transport, owned)
        .await
        .map_err(|_| {
            popup_failure(
                target,
                "the native popup could not join the existing browser session",
            )
        })?;
    // Some Chrome versions withhold the release acknowledgment after popup focus.
    // The correlated browser gesture + new owned tab prove delivery in that case.
    let method = if release.is_ok() {
        "cdp-input-owned-popup"
    } else {
        "cdp-input-owned-popup-unacked-release"
    };
    Ok(Some(ExecutionEvidence {
        method: method.into(),
        detail: tab.to_string(),
    }))
}

fn popup_failure(target: &ResolvedTarget, message: &str) -> ExecutionFailure {
    ExecutionFailure::new(
        ExecutionFailureKind::InteractionRejected,
        Some(target.reference.to_string()),
        message,
    )
}
