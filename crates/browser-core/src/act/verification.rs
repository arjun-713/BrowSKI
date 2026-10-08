use super::cdp::{call_on_backend, read_selected, settle};
use crate::events::BrowserEvent;
use crate::observer::observe_full;
use crate::session::BrowserSession;
use browser_agent_cdp::TabId;
use browser_agent_element_registry::ElementRef;
use browser_agent_executor::{
    ActionOutcome, ActionTimings, BrowserAction, ExecutionResult, MechanicalRepair,
};
use browser_agent_observation::{SemanticSnapshot, SnapshotDelta};
use browser_agent_verification::{
    verify_expected, EffectExpectation, ExpectedEffect, SideEffects, VerificationResult,
};
use serde_json::Value;
use std::time::Instant;

// ---------------------------------------------------------------------------
// finish: settle → post-state → verify
// ---------------------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
pub(super) async fn finish(
    session: &BrowserSession,
    tab: &TabId,
    action: BrowserAction,
    execution: ExecutionResult,
    before: SemanticSnapshot,
    events_rx: &mut tokio::sync::broadcast::Receiver<BrowserEvent>,
    tabs_before: usize,
    before_generation: u64,
    repairs: Vec<MechanicalRepair>,
    attempts: u32,
    start: Instant,
    mut timings: ActionTimings,
) -> ActionOutcome {
    // Settle: bounded stability wait (NOT a fixed sleep, NOT network idle —
    // persistent polling would make network-idle useless on modern apps).
    // Dialog-aware: evaluates hang while a JS dialog is open, so bail out
    // early and skip post-state capture entirely (verify from events).
    let dialog_fast_path = session.dialog_open();
    let settle_start = Instant::now();
    if !dialog_fast_path {
        settle(session, tab).await;
    }
    timings.settle_ms = settle_start.elapsed().as_millis() as u64;

    // Drain side-effect evidence.
    let mut side = SideEffects {
        url_changed: false, // computed from snapshots below (authoritative)
        ..SideEffects::default()
    };
    while let Ok(ev) = events_rx.try_recv() {
        match ev {
            BrowserEvent::DialogOpened { .. } => side.dialog_opened = true,
            BrowserEvent::DialogClosed { .. } => side.dialog_closed = true,
            BrowserEvent::TargetCreated { .. } => side.new_tab_opened = true,
            BrowserEvent::NavigationCompleted { .. } => side.url_changed = true,
            _ => {}
        }
    }
    if session.dialog_open() {
        side.dialog_opened = true;
    }
    let tabs_after = session.tabs().await.len();
    if tabs_after > tabs_before {
        side.new_tab_opened = true;
    } else if tabs_after < tabs_before {
        side.tab_closed = true;
    }

    let active_tab_closed = !session.tabs().await.iter().any(|info| &info.id == tab);
    let post_observation_start = Instant::now();
    let after = if active_tab_closed || session.dialog_open() {
        // A modal dialog blocks page evaluation: post-state is unavailable
        // by construction; a closed tab is also no longer observable. Verify
        // either transition from its lifecycle evidence, not page commands.
        before.clone()
    } else {
        match observe_full(session, tab).await {
            Ok(s) => s,
            Err(e) => {
                return ActionOutcome {
                    action,
                    execution,
                    verification: VerificationResult::uncertain(
                        "post-state unavailable",
                        format!("{e}"),
                    ),
                    before_generation,
                    after_generation: session.generation(),
                    delta: SnapshotDelta::default(),
                    repairs,
                    attempts,
                    elapsed_ms: start.elapsed().as_millis() as u64,
                    timings,
                };
            }
        }
    };
    timings.post_observation_ms = post_observation_start.elapsed().as_millis() as u64;
    if before.url != after.url {
        side.url_changed = true;
    }
    let delta_start = Instant::now();
    let delta = session.observe_delta(tab).await.unwrap_or_default();
    timings.delta_ms = delta_start.elapsed().as_millis() as u64;
    let verification_start = Instant::now();
    let verification = verify_for(session, tab, &action, &before, &after, &delta, &side).await;
    timings.verification_ms = verification_start.elapsed().as_millis() as u64;

    ActionOutcome {
        action,
        execution,
        verification,
        before_generation,
        after_generation: session.generation(),
        delta,
        repairs,
        attempts,
        elapsed_ms: start.elapsed().as_millis() as u64,
        timings,
    }
}

async fn verify_for(
    session: &BrowserSession,
    tab: &TabId,
    action: &BrowserAction,
    before: &SemanticSnapshot,
    after: &SemanticSnapshot,
    delta: &SnapshotDelta,
    side: &SideEffects,
) -> VerificationResult {
    let expected = action.expected_effect();
    let effective = match &expected {
        ExpectedEffect::Unspecified => default_for(session, tab, action, before).await,
        other => other.clone(),
    };
    // Custom direct read-back checks that need the live browser.
    match action {
        BrowserAction::Select {
            target, value, by, ..
        } => {
            return verify_select(session, tab, target, value, by, after).await;
        }
        BrowserAction::Scroll { .. } => {
            return verify_scroll(before, after);
        }
        BrowserAction::Hover { target, .. } => {
            return verify_hover(session, tab, target, after).await;
        }
        BrowserAction::Reload { .. } => {
            return if after.state_generation > before.state_generation {
                VerificationResult::success(
                    "document reloaded",
                    format!(
                        "generation {} → {}",
                        before.state_generation, after.state_generation
                    ),
                )
                .with_check("document-reloaded")
            } else {
                VerificationResult::failure(
                    "document reloaded",
                    "main-frame generation did not advance",
                )
                .with_check("no-effect")
            };
        }
        BrowserAction::ActivateTab { tab: other, .. } => {
            let active = session.active_tab().await.map(|t| t.id);
            return if active.as_ref() == Some(other) {
                VerificationResult::success("tab activated", format!("active is {other}"))
                    .with_check("tab-active")
            } else {
                VerificationResult::failure(
                    "tab activated",
                    format!("active is {active:?}, expected {other}"),
                )
                .with_check("tab-active")
            };
        }
        BrowserAction::CloseTab { tab: other, .. } => {
            let gone = !session.tabs().await.iter().any(|t| &t.id == other);
            return if gone {
                VerificationResult::success("tab closed", format!("{other} gone"))
                    .with_check("tab-closed")
            } else {
                VerificationResult::failure("tab closed", format!("{other} still present"))
                    .with_check("tab-closed")
            };
        }
        _ => {}
    }
    verify_expected(&effective, action.action_type(), before, after, delta, side)
}

/// Default expectations for actions that verify directly from parameters.
async fn default_for(
    _session: &BrowserSession,
    _tab: &TabId,
    action: &BrowserAction,
    before: &SemanticSnapshot,
) -> ExpectedEffect {
    match action {
        BrowserAction::Type {
            target,
            text,
            clear,
            ..
        } => {
            let expected = if *clear {
                text.clone()
            } else {
                let prev = before
                    .elements
                    .iter()
                    .find(|e| e.id == target.id)
                    .and_then(|e| e.value.clone())
                    .unwrap_or_default();
                format!("{prev}{text}")
            };
            ExpectedEffect::AnyOf(vec![EffectExpectation::ValueIs {
                target: target.clone(),
                value: expected,
            }])
        }
        BrowserAction::Check {
            target, checked, ..
        } => ExpectedEffect::AnyOf(vec![EffectExpectation::CheckedIs {
            target: target.clone(),
            checked: *checked,
        }]),
        BrowserAction::Navigate { url, .. } => {
            ExpectedEffect::AnyOf(vec![EffectExpectation::UrlIs { url: url.clone() }])
        }
        BrowserAction::Back { .. } | BrowserAction::Forward { .. } => {
            ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged])
        }
        BrowserAction::NewTab { .. } => {
            ExpectedEffect::AnyOf(vec![EffectExpectation::NewTabOpened])
        }
        BrowserAction::HandleDialog { .. } => {
            ExpectedEffect::AnyOf(vec![EffectExpectation::DialogClosed])
        }
        _ => ExpectedEffect::Unspecified,
    }
}

async fn verify_select(
    session: &BrowserSession,
    tab: &TabId,
    target: &ElementRef,
    value: &str,
    by: &browser_agent_executor::SelectBy,
    after: &SemanticSnapshot,
) -> VerificationResult {
    let element = after.elements.iter().find(|e| e.id == target.id);
    let Some(el) = element else {
        return VerificationResult::uncertain("select verified", format!("{target} not observed"));
    };
    let backend = match el.backend_node_id {
        Some(b) => b,
        None => {
            return VerificationResult::uncertain(
                "select verified",
                format!("{target} has no backend node"),
            );
        }
    };
    let (_, cdp_session) = match session.tab_session_pub(tab).await {
        Ok(s) => s,
        Err(e) => {
            return VerificationResult::uncertain("select verified", format!("{e}"));
        }
    };
    let read = read_selected(session, &cdp_session, backend).await;
    match read {
        Some((selected_value, selected_label)) => {
            let ok = match by {
                browser_agent_executor::SelectBy::Value => selected_value == value,
                browser_agent_executor::SelectBy::Label => selected_label == value,
            };
            if ok {
                VerificationResult::success(
                    format!("{target} selection matched"),
                    "selected option matched the requested selection",
                )
                .with_check("select-value")
            } else {
                VerificationResult::failure(
                    format!("{target} selection matched"),
                    "selected option did not match the requested selection",
                )
                .with_check("wrong-effect")
            }
        }
        None => VerificationResult::uncertain("select verified", "could not read selected option"),
    }
}

fn verify_scroll(before: &SemanticSnapshot, after: &SemanticSnapshot) -> VerificationResult {
    if before.scroll != after.scroll {
        VerificationResult::success(
            "scroll moved",
            format!("{:?} → {:?}", before.scroll, after.scroll),
        )
        .with_check("scroll-changed")
    } else {
        VerificationResult::failure("scroll moved", "scroll position unchanged")
            .with_check("no-effect")
    }
}

async fn verify_hover(
    session: &BrowserSession,
    tab: &TabId,
    target: &ElementRef,
    after: &SemanticSnapshot,
) -> VerificationResult {
    let element = after.elements.iter().find(|e| e.id == target.id);
    let backend = match element {
        Some(el) => match el.backend_node_id {
            Some(backend) => backend,
            None => {
                return VerificationResult::uncertain("hover verified", "no backend node");
            }
        },
        None => {
            return VerificationResult::uncertain(
                "hover verified",
                format!("{target} not observed"),
            );
        }
    };
    let Ok((_, cdp_session)) = session.tab_session_pub(tab).await else {
        return VerificationResult::uncertain("hover verified", "tab gone".to_string());
    };
    match call_on_backend(
        session,
        &cdp_session,
        backend,
        include_str!("../mechanics/read-hover.js"),
    )
    .await
    {
        Ok(Value::Bool(true)) => VerificationResult::success(
            "hover landed",
            format!("{target} matches :hover after trusted pointer input"),
        )
        .with_check("hover-match"),
        Ok(Value::Bool(false)) => {
            VerificationResult::failure("hover landed", format!("{target} does not match :hover"))
                .with_check("no-effect")
        }
        _ => VerificationResult::uncertain("hover landed", "hover state could not be read")
            .with_check("uncertain-effect"),
    }
}
