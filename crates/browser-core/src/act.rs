//! `session.act()`: typed intent → browser state transition → proof.
//!
//! Flow per action:
//!
//! ```text
//! validate generation → resolve ElementRef → interactability gate →
//! pre-state → perform (bounded mechanical repairs) → settle →
//! post-state → verify action-specific postconditions
//! ```
//!
//! Repairs are mechanical only (re-resolve, scroll into view, wait out a
//! transient overlay, retry the hit test, reacquire after mutation) and
//! bounded by [`ActOptions`]. New plans and strategies belong to future
//! agent recovery — M3 never replans.

mod cdp;
mod input;
mod verification;

use browser_agent_cdp::{CdpSessionId, TabId, TargetId};
use browser_agent_element_registry::ElementRef;
use browser_agent_executor::{
    ActOptions, ActionOutcome, ActionTimings, BrowserAction, ExecutionEvidence, ExecutionFailure,
    ExecutionFailureKind, ExecutionResult, MechanicalRepair,
};
use browser_agent_observation::{BackendNodeId, SemanticElement, SemanticSnapshot, SnapshotDelta};
use browser_agent_verification::VerificationResult;
use std::time::{Duration, Instant};

use crate::error::BrowserRuntimeError;
use crate::observer::observe_full;
use crate::session::BrowserSession;

/// A resolved, gated action target.
pub(super) struct ResolvedTarget {
    pub(super) reference: ElementRef,
    pub(super) backend: BackendNodeId,
    pub(super) session: CdpSessionId,
    pub(super) element: SemanticElement,
}

/// Public entry: perform + verify one action on a tab. Never returns Err —
/// failures are data inside [`ActionOutcome`].
pub(crate) async fn act_on(
    session: &BrowserSession,
    tab: &TabId,
    action: BrowserAction,
    options: ActOptions,
) -> ActionOutcome {
    let start = Instant::now();
    let before_generation = session.generation();
    let max_attempts = options.bounded_attempts();
    let mut timings = ActionTimings::default();

    if let BrowserAction::Wait { ms } = &action {
        let action_start = Instant::now();
        tokio::time::sleep(Duration::from_millis(*ms)).await;
        timings.action_execution_ms = action_start.elapsed().as_millis() as u64;
        return ActionOutcome {
            action: action.clone(),
            execution: Ok(ExecutionEvidence {
                method: "wait".into(),
                detail: format!("{ms}ms"),
            }),
            verification: VerificationResult::success("wait", format!("waited {ms}ms"))
                .with_check("wait"),
            before_generation,
            after_generation: session.generation(),
            delta: SnapshotDelta::default(),
            repairs: vec![],
            attempts: 1,
            elapsed_ms: start.elapsed().as_millis() as u64,
            timings,
        };
    }

    // A JavaScript dialog blocks page evaluation. Handle it from the cached
    // pre-dialog snapshot and verify the close event without probing the page.
    if let BrowserAction::HandleDialog { accept, .. } = &action {
        let mut events_rx = session.events();
        let tabs_before = session.tabs().await.len();
        let target = TargetId::from(tab.as_str().to_string());
        let before = session
            .snapshots_map()
            .read()
            .await
            .get(&target)
            .cloned()
            .unwrap_or_else(|| SemanticSnapshot::minimal(String::new(), None, before_generation));
        let decision = if *accept { "accepted" } else { "dismissed" };
        let action_start = Instant::now();
        let execution = session
            .handle_dialog(tab, *accept)
            .await
            .map(|()| ExecutionEvidence {
                method: "cdp-dialog".into(),
                detail: decision.into(),
            })
            .map_err(|e| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    None,
                    format!("handle dialog failed: {e}"),
                )
            });
        timings.action_execution_ms = action_start.elapsed().as_millis() as u64;
        return verification::finish(
            session,
            tab,
            action,
            execution,
            before,
            &mut events_rx,
            tabs_before,
            before_generation,
            vec![],
            1,
            start,
            timings,
        )
        .await;
    }

    let mut events_rx = session.events();
    let tabs_before = session.tabs().await.len();

    // Pre-state (also refreshes the registry).
    let observe_start = Instant::now();
    let before = match observe_full(session, tab).await {
        Ok(s) => s,
        Err(e) => {
            timings.pre_observation_ms = observe_start.elapsed().as_millis() as u64;
            return terminal_outcome(
                session,
                action,
                before_generation,
                observe_failure(e, None),
                start,
                timings,
            )
            .await;
        }
    };
    timings.pre_observation_ms = observe_start.elapsed().as_millis() as u64;

    // Resolve + gate.
    let resolve_start = Instant::now();
    let mut resolved = match resolve_target(session, tab, action.target(), &before).await {
        Ok(r) => r,
        Err(f) => {
            timings.target_resolution_ms = resolve_start.elapsed().as_millis() as u64;
            return verification::finish(
                session,
                tab,
                action,
                Err(f),
                before,
                &mut events_rx,
                tabs_before,
                before_generation,
                vec![],
                1,
                start,
                timings,
            )
            .await;
        }
    };
    timings.target_resolution_ms = resolve_start.elapsed().as_millis() as u64;

    // Attempts with bounded mechanical repairs.
    let mut repairs: Vec<MechanicalRepair> = vec![];
    let mut attempts = 0u32;
    let execution: ExecutionResult = loop {
        attempts += 1;
        let action_start = Instant::now();
        let result = input::perform(session, tab, &action, resolved.as_ref(), &options).await;
        timings.action_execution_ms += action_start.elapsed().as_millis() as u64;
        match result {
            Ok(evidence) => break Ok(evidence),
            Err(failure) => {
                let terminal = failure.kind == ExecutionFailureKind::ConnectionLost
                    || !failure.retryable
                    || attempts >= max_attempts;
                if terminal {
                    break Err(failure);
                }
                let recovery_start = Instant::now();
                let repair_result =
                    apply_repair(session, tab, &action, &failure, resolved.as_ref()).await;
                timings.mechanical_recovery_ms += recovery_start.elapsed().as_millis() as u64;
                match repair_result {
                    Ok((repair, fresh)) => {
                        repairs.push(repair);
                        resolved = fresh;
                        continue;
                    }
                    Err(f) => break Err(f),
                }
            }
        }
    };

    verification::finish(
        session,
        tab,
        action,
        execution,
        before,
        &mut events_rx,
        tabs_before,
        before_generation,
        repairs,
        attempts,
        start,
        timings,
    )
    .await
}

// ---------------------------------------------------------------------------
// resolution + gating
// ---------------------------------------------------------------------------

async fn resolve_target(
    session: &BrowserSession,
    tab: &TabId,
    target: Option<&ElementRef>,
    snapshot: &SemanticSnapshot,
) -> Result<Option<ResolvedTarget>, ExecutionFailure> {
    let Some(requested) = target else {
        return Ok(None);
    };
    let target_id = TargetId::from(tab.as_str().to_string());
    let current_generation = session.generation();

    // Registry lookup by id (identity), with alias re-resolution on staleness.
    let (id, entry_generation, entry_alias) = {
        let registries = session.registries_map().read().await;
        let registry = registries.get(&target_id).ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::TargetNotFound,
                Some(requested.to_string()),
                "no element registry for tab",
            )
        })?;
        match registry.lookup_id(requested.id) {
            Some(entry) => (entry.id, entry.generation, entry.alias_str().to_string()),
            None => {
                return Err(ExecutionFailure::new(
                    ExecutionFailureKind::TargetNotFound,
                    Some(requested.to_string()),
                    "unknown element id",
                ));
            }
        }
    };

    // Identity confusion guard: the alias must agree with the stored one.
    // A caller mixing an id from one element with another's alias is
    // ambiguous by construction — refuse, never guess.
    if entry_alias != requested.alias_str() {
        return Err(ExecutionFailure::new(
            ExecutionFailureKind::AmbiguousTarget,
            Some(requested.to_string()),
            format!(
                "ref identity mismatch: id {} is bound as @{entry_alias}, not @{}",
                requested.id,
                requested.alias_str()
            ),
        ));
    }

    let fresh = if entry_generation != current_generation {
        // Stale: try the alias in the current generation (same control,
        // rebound identity).
        let registries = session.registries_map().read().await;
        let registry = registries.get(&target_id).ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::TargetNotFound,
                Some(requested.to_string()),
                "no element registry for tab",
            )
        })?;
        match registry.lookup_alias(requested.alias_str()) {
            Some(f) if f.generation == current_generation => Some((f, MechanicalRepair::ReResolve)),
            _ => {
                return Err(ExecutionFailure::new(
                    ExecutionFailureKind::StaleTarget,
                    Some(requested.to_string()),
                    format!(
                        "ref generation {} is stale (current {current_generation}) and alias did not rebind",
                        requested.generation
                    ),
                ));
            }
        }
    } else {
        None
    };
    let _ = fresh;

    // Element data from the pre-state snapshot (by registry id).
    let element = snapshot
        .elements
        .iter()
        .find(|e| e.id == id)
        .cloned()
        .ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::TargetNotFound,
                Some(requested.to_string()),
                "id not present in current snapshot",
            )
        })?;

    // Backend handle required for input actions.
    let backend = element.backend_node_id.ok_or_else(|| {
        ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(requested.to_string()),
            "element has no backend node (cannot address it via CDP input)",
        )
        .with_evidence(serde_json::json!({"retryable": false}))
    })?;

    // CDP session for the tab.
    let (_, cdp_session) = session.tab_session_pub(tab).await.map_err(|e| {
        ExecutionFailure::new(
            ExecutionFailureKind::TabClosed,
            Some(requested.to_string()),
            format!("tab session unavailable: {e}"),
        )
    })?;

    Ok(Some(ResolvedTarget {
        reference: requested.clone(),
        backend,
        session: cdp_session,
        element,
    }))
}

fn gate_target(
    action: &BrowserAction,
    element: &SemanticElement,
    alias: &str,
) -> Result<(), ExecutionFailure> {
    let needs_full_interaction = matches!(
        action,
        BrowserAction::Type { .. } | BrowserAction::Select { .. } | BrowserAction::Check { .. }
    );
    if needs_full_interaction && !element.interactable {
        return Err(classify_blocked(element, alias));
    }
    // Click/hover/press/scroll require a visible, enabled target; occlusion
    // fails them (input would land elsewhere).
    let needs_visible_enabled = matches!(
        action,
        BrowserAction::Click { .. }
            | BrowserAction::Hover { .. }
            | BrowserAction::Press { .. }
            | BrowserAction::Scroll { .. }
    );
    if needs_visible_enabled {
        if !element.visible {
            return Err(classify_blocked(element, alias));
        }
        if !element.enabled {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::TargetDisabled,
                Some(alias.to_string()),
                "target disabled",
            ));
        }
        if element.visibility == browser_agent_observation::VisibilityClass::Occluded {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::TargetOccluded,
                Some(alias.to_string()),
                "target occluded: input would land on covering content",
            ));
        }
        if matches!(
            action,
            BrowserAction::Type { .. } | BrowserAction::Select { .. } | BrowserAction::Check { .. }
        ) && element.state.iter().any(|s| s == "readonly")
        {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::TargetReadonly,
                Some(alias.to_string()),
                "target readonly",
            ));
        }
    }
    // Offscreen targets need a scroll first: repairable, not terminal.
    if matches!(action, BrowserAction::Click { .. })
        && element.visibility == browser_agent_observation::VisibilityClass::Offscreen
    {
        return Err(ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(alias.to_string()),
            "target offscreen: scroll into view first",
        ));
    }
    Ok(())
}

fn classify_blocked(element: &SemanticElement, alias: &str) -> ExecutionFailure {
    use browser_agent_observation::VisibilityClass;
    let (kind, details) = if !element.visible {
        match element.visibility {
            VisibilityClass::Hidden => (ExecutionFailureKind::TargetHidden, "target hidden"),
            VisibilityClass::Offscreen => {
                return ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    Some(alias.to_string()),
                    "target offscreen: scroll into view first",
                );
            }
            VisibilityClass::Occluded => (
                ExecutionFailureKind::TargetOccluded,
                "target occluded: input would land on covering content",
            ),
            VisibilityClass::Visible => (ExecutionFailureKind::TargetHidden, "target not visible"),
        }
    } else if !element.enabled {
        (ExecutionFailureKind::TargetDisabled, "target disabled")
    } else if element.state.iter().any(|s| s == "readonly") {
        (ExecutionFailureKind::TargetReadonly, "target readonly")
    } else {
        let mut failure = ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(alias.to_string()),
            "target not interactable",
        );
        failure.retryable = false;
        return failure;
    };
    ExecutionFailure::new(kind, Some(alias.to_string()), details)
}

// ---------------------------------------------------------------------------
// repairs
// ---------------------------------------------------------------------------

/// Apply one mechanical repair, then re-observe + re-resolve. Returns the
/// repair kind and the fresh resolution, or the failure that stops us.
async fn apply_repair(
    session: &BrowserSession,
    tab: &TabId,
    action: &BrowserAction,
    failure: &ExecutionFailure,
    resolved: Option<&ResolvedTarget>,
) -> Result<(MechanicalRepair, Option<ResolvedTarget>), ExecutionFailure> {
    let backend = resolved.map(|r| r.backend);
    let repair = match failure.kind {
        ExecutionFailureKind::StaleTarget => MechanicalRepair::ReResolve,
        ExecutionFailureKind::TargetOccluded => MechanicalRepair::WaitTransientOverlay,
        ExecutionFailureKind::InteractionRejected
            if failure.details.contains("offscreen")
                || failure.details.contains("scroll into view") =>
        {
            MechanicalRepair::ScrollIntoView
        }
        ExecutionFailureKind::InteractionRejected => MechanicalRepair::RetryHitTest,
        ExecutionFailureKind::ActionTimeout | ExecutionFailureKind::NavigationRace => {
            MechanicalRepair::WaitTransientOverlay
        }
        _ => MechanicalRepair::ReacquireAfterMutation,
    };
    match repair {
        MechanicalRepair::ScrollIntoView => {
            if let Some(b) = backend {
                let transport = session.transport_pub().await;
                if let Some(r) = resolved {
                    let _ = transport
                        .command_in_session(
                            &r.session,
                            "DOM.scrollIntoViewIfNeeded",
                            serde_json::json!({"backendNodeId": b.get()}),
                        )
                        .await;
                }
            }
        }
        MechanicalRepair::WaitTransientOverlay => {
            tokio::time::sleep(Duration::from_millis(750)).await;
        }
        MechanicalRepair::ReResolve
        | MechanicalRepair::RetryHitTest
        | MechanicalRepair::ReacquireAfterMutation => {}
    }
    // Fresh state + fresh resolution after every repair.
    let snapshot = observe_full(session, tab)
        .await
        .map_err(|e| observe_failure(e, resolved.map(|r| r.reference.to_string())))?;
    let fresh = resolve_against(session, tab, action.target(), &snapshot).await?;
    Ok((repair, fresh))
}

/// Re-resolve without recording another repair (used by repairs).
async fn resolve_against(
    session: &BrowserSession,
    tab: &TabId,
    target: Option<&ElementRef>,
    snapshot: &SemanticSnapshot,
) -> Result<Option<ResolvedTarget>, ExecutionFailure> {
    resolve_target(session, tab, target, snapshot).await
}

fn observe_failure(e: BrowserRuntimeError, target: Option<String>) -> ExecutionFailure {
    match &e {
        BrowserRuntimeError::ConnectionLost => {
            ExecutionFailure::new(ExecutionFailureKind::ConnectionLost, target, format!("{e}"))
        }
        BrowserRuntimeError::SessionClosed | BrowserRuntimeError::NoActiveTab => {
            ExecutionFailure::new(ExecutionFailureKind::TabClosed, target, format!("{e}"))
        }
        BrowserRuntimeError::TargetClosed(_) => {
            ExecutionFailure::new(ExecutionFailureKind::TabClosed, target, format!("{e}"))
        }
        _ => ExecutionFailure::new(ExecutionFailureKind::ActionTimeout, target, format!("{e}")),
    }
}

async fn terminal_outcome(
    session: &BrowserSession,
    action: BrowserAction,
    before_generation: u64,
    failure: ExecutionFailure,
    start: Instant,
    timings: ActionTimings,
) -> ActionOutcome {
    ActionOutcome {
        action,
        execution: Err(failure),
        verification: VerificationResult::uncertain("no pre-state", "browser unreachable"),
        before_generation,
        after_generation: session.generation(),
        delta: SnapshotDelta::default(),
        repairs: vec![],
        attempts: 0,
        elapsed_ms: start.elapsed().as_millis() as u64,
        timings,
    }
}
