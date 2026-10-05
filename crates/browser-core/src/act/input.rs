use super::cdp::{
    call_on_backend, cmd, count_page_targets, element_tag, focus_backend, hit_passes, js_set_value,
    key_with_modifiers, new_page_target_appeared, press_key, read_checked, read_scroll, read_value,
    scroll_into_view, send_mouse, send_mouse_timeout, viewport_point, wait_for_evaluate,
    wait_ready,
};
use super::{gate_target, ResolvedTarget};
use crate::observer::observe_full;
use crate::session::BrowserSession;
use browser_agent_cdp::TabId;
use browser_agent_executor::{
    ActOptions, BrowserAction, ExecutionEvidence, ExecutionFailure, ExecutionFailureKind,
    ExecutionResult, MouseButton,
};
use serde_json::Value;
use std::time::Duration;

// ---------------------------------------------------------------------------
// perform
// ---------------------------------------------------------------------------

pub(super) async fn perform(
    session: &BrowserSession,
    tab: &TabId,
    action: &BrowserAction,
    resolved: Option<&ResolvedTarget>,
    options: &ActOptions,
) -> ExecutionResult {
    // Dialogs swallow input: fail fast with evidence instead of clicking
    // into the void (the agent dismisses explicitly via handle_dialog).
    if session.dialog_open()
        && matches!(
            action,
            BrowserAction::Click { .. }
                | BrowserAction::Type { .. }
                | BrowserAction::Select { .. }
                | BrowserAction::Check { .. }
                | BrowserAction::Press { .. }
        )
    {
        return Err(ExecutionFailure::new(
            ExecutionFailureKind::DialogBlocked,
            resolved.map(|r| r.reference.to_string()),
            "a JavaScript dialog is open; input would be swallowed",
        ));
    }
    // Gate every targeted action against fresh pre-state data.
    if let (Some(want), Some(got)) = (action.target(), resolved) {
        gate_target(action, &got.element, &want.to_string())?;
    }
    match action {
        BrowserAction::Click {
            target: _,
            options: click_options,
            ..
        } => {
            let r = resolved.expect("click always resolves a target");
            perform_click(
                session,
                r,
                &click_options.button,
                click_options.click_count,
                options,
            )
            .await
        }
        BrowserAction::Type {
            target: _,
            text,
            clear,
            submit,
            ..
        } => {
            let r = resolved.expect("type always resolves a target");
            let out = perform_type(session, r, text, *clear, options).await?;
            if *submit {
                press_key(session, &r.session, "Enter").await?;
            }
            Ok(out)
        }
        BrowserAction::Select {
            target: _,
            value,
            by,
            ..
        } => {
            let r = resolved.expect("select always resolves a target");
            perform_select(session, r, value, by, options).await
        }
        BrowserAction::Check {
            target: _, checked, ..
        } => {
            let r = resolved.expect("check always resolves a target");
            perform_check(session, r, *checked, options).await
        }
        BrowserAction::Press { target: _, key, .. } => {
            let (_, cdp_session) = session.tab_session_pub(tab).await.map_err(|e| {
                ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
            })?;
            if let Some(r) = resolved {
                focus_backend(session, &r.session, r.backend).await?;
            }
            press_key(session, &cdp_session, key).await?;
            Ok(ExecutionEvidence {
                method: "cdp-input".into(),
                detail: format!("pressed {key}"),
            })
        }
        BrowserAction::Scroll {
            target: _, dx, dy, ..
        } => perform_scroll(session, tab, resolved, *dx, *dy).await,
        BrowserAction::Hover { .. } => {
            let r = resolved.expect("hover always resolves a target");
            let (x, y) = viewport_point(session, &r.session, r.backend).await?;
            send_mouse(
                session,
                &r.session,
                "mouseMoved",
                (x, y),
                &MouseButton::Left,
                0,
            )
            .await?;
            Ok(ExecutionEvidence {
                method: "cdp-input".into(),
                detail: format!("hovered at {x},{y}"),
            })
        }
        BrowserAction::Navigate { url, .. } => {
            session.navigate_tab(tab, url).await.map_err(|e| {
                ExecutionFailure::new(ExecutionFailureKind::NavigationRace, None, format!("{e}"))
            })?;
            Ok(ExecutionEvidence {
                method: "navigate".into(),
                detail: url.clone(),
            })
        }
        BrowserAction::Back { .. } => history_go(session, tab, -1).await,
        BrowserAction::Forward { .. } => history_go(session, tab, 1).await,
        BrowserAction::Reload { .. } => {
            let (_, cdp_session) = session.tab_session_pub(tab).await.map_err(|e| {
                ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
            })?;
            cmd(session, &cdp_session, "Page.reload", serde_json::json!({})).await?;
            wait_ready(session, &cdp_session, None).await?;
            Ok(ExecutionEvidence {
                method: "reload".into(),
                detail: String::new(),
            })
        }
        BrowserAction::ActivateTab { tab: other, .. } => {
            session.activate_tab(other).await.map_err(|e| {
                ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
            })?;
            Ok(ExecutionEvidence {
                method: "activate-tab".into(),
                detail: other.to_string(),
            })
        }
        BrowserAction::CloseTab { tab: other, .. } => {
            session.close_tab(other).await.map_err(|e| {
                ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
            })?;
            Ok(ExecutionEvidence {
                method: "close-tab".into(),
                detail: other.to_string(),
            })
        }
        BrowserAction::NewTab { url, .. } => {
            let created = session.new_tab(url.as_deref()).await.map_err(|e| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    None,
                    format!("new tab failed: {e}"),
                )
            })?;
            Ok(ExecutionEvidence {
                method: "target-create".into(),
                detail: created.to_string(),
            })
        }
        BrowserAction::HandleDialog { accept, .. } => {
            session.handle_dialog(tab, *accept).await.map_err(|e| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    None,
                    format!("handle dialog failed: {e}"),
                )
            })?;
            Ok(ExecutionEvidence {
                method: "cdp-dialog".into(),
                detail: if *accept { "accepted" } else { "dismissed" }.into(),
            })
        }
        BrowserAction::Wait { .. } => unreachable!("wait handled in act_on"),
    }
}

// -- click cascade ----------------------------------------------------------

fn keyboard_activatable(role: &str) -> bool {
    matches!(
        role,
        "button" | "link" | "checkbox" | "radio" | "switch" | "option" | "tab" | "menuitem"
    )
}

async fn perform_click(
    session: &BrowserSession,
    r: &ResolvedTarget,
    button: &MouseButton,
    click_count: u32,
    options: &ActOptions,
) -> ExecutionResult {
    // 1. Trusted CDP input at the verified point.
    scroll_into_view(session, &r.session, r.backend).await;
    match viewport_point(session, &r.session, r.backend).await {
        Ok((x, y)) => {
            if hit_passes(session, &r.session, r.backend, x, y).await {
                let transport = session.transport_pub().await;
                let targets_before = count_page_targets(&transport).await;
                let button_str = match button {
                    MouseButton::Left => "left",
                    MouseButton::Middle => "middle",
                    MouseButton::Right => "right",
                };
                send_mouse(
                    session,
                    &r.session,
                    "mousePressed",
                    (x, y),
                    button,
                    click_count.max(1),
                )
                .await?;
                let _ = button_str;
                match send_mouse_timeout(
                    session,
                    &r.session,
                    "mouseReleased",
                    (x, y),
                    button,
                    click_count.max(1),
                    Duration::from_secs(5),
                )
                .await
                {
                    Ok(()) => {
                        return Ok(ExecutionEvidence {
                            method: "cdp-input".into(),
                            detail: format!("clicked at {x},{y}"),
                        });
                    }
                    Err(_) => {
                        // Popup-focus quirk (observed): when the press opens a
                        // new target, Chrome sometimes never answers the
                        // release and wedges opener input while the popup is
                        // open. A synchronously-appeared page target proves
                        // delivery; anything else stays a timeout failure.
                        if new_page_target_appeared(&transport, targets_before).await {
                            return Ok(ExecutionEvidence {
                                method: "cdp-input".into(),
                                detail: format!(
                                    "pressed at {x},{y}; release unacked after popup opened"
                                ),
                            });
                        }
                        return Err(ExecutionFailure::new(
                            ExecutionFailureKind::ActionTimeout,
                            Some(r.reference.to_string()),
                            "mouse release timed out with no synchronous effect",
                        ));
                    }
                }
            }
        }
        Err(e) => return Err(e),
    }
    // 2. Focus + keyboard activation where semantically valid.
    if keyboard_activatable(&r.element.role) {
        focus_backend(session, &r.session, r.backend).await?;
        let key = if r.element.role == "checkbox" || r.element.role == "radio" {
            " "
        } else {
            "Enter"
        };
        press_key(session, &r.session, key).await?;
        return Ok(ExecutionEvidence {
            method: "keyboard".into(),
            detail: format!("activated via {key}"),
        });
    }
    // 3. DOM method only when policy permits.
    if options.allow_dom_fallback {
        call_on_backend(session, &r.session, r.backend, "function(){this.click()}")
            .await
            .map_err(|e| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    Some(r.reference.to_string()),
                    format!("dom click failed: {e}"),
                )
            })?;
        return Ok(ExecutionEvidence {
            method: "dom-method".into(),
            detail: "el.click()".into(),
        });
    }
    // 4. Fail with evidence.
    Err(ExecutionFailure::new(
        ExecutionFailureKind::InteractionRejected,
        Some(r.reference.to_string()),
        "hit test failed and no fallback applied (keyboard invalid, dom fallback disabled)",
    )
    .with_evidence(serde_json::json!({"role": r.element.role})))
}

// -- typing -----------------------------------------------------------------

async fn perform_type(
    session: &BrowserSession,
    r: &ResolvedTarget,
    text: &str,
    clear: bool,
    options: &ActOptions,
) -> ExecutionResult {
    focus_backend(session, &r.session, r.backend).await?;
    if clear {
        // Select-all + delete (works for inputs, textareas, contenteditable).
        key_with_modifiers(session, &r.session, "a", 65, 2).await?;
        press_key(session, &r.session, "Backspace").await?;
    } else {
        press_key(session, &r.session, "End").await?;
    }
    if !text.is_empty() {
        cmd(
            session,
            &r.session,
            "Input.insertText",
            serde_json::json!({"text": text}),
        )
        .await
        .map_err(|e| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                Some(r.reference.to_string()),
                format!("insertText failed: {e}"),
            )
        })?;
    }
    let observed = read_value(
        session,
        &r.session,
        r.backend,
        &r.element.role,
        &r.element.semantic_kind,
    )
    .await;
    match observed {
        Some(v) if clear && v == text => Ok(ExecutionEvidence {
            method: "cdp-input".into(),
            detail: "target value matched requested text".into(),
        }),
        Some(v) if !clear && v.ends_with(text) => Ok(ExecutionEvidence {
            method: "cdp-input".into(),
            detail: "target value ends with requested text".into(),
        }),
        Some(_) if options.allow_dom_fallback => {
            // Controlled inputs (React): set through the native setter and
            // dispatch input+change so framework state syncs.
            js_set_value(session, &r.session, r.backend, text).await?;
            let v2 = read_value(
                session,
                &r.session,
                r.backend,
                &r.element.role,
                &r.element.semantic_kind,
            )
            .await
            .unwrap_or_default();
            if (clear && v2 == text) || (!clear && v2.ends_with(text)) {
                Ok(ExecutionEvidence {
                    method: "dom-method".into(),
                    detail: "native setter; target value matched requested text".into(),
                })
            } else {
                Err(ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    Some(r.reference.to_string()),
                    "controlled input value did not match requested text after fallback",
                ))
            }
        }
        _ => Err(ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(r.reference.to_string()),
            "target value did not match requested text",
        )),
    }
}

// -- select -----------------------------------------------------------------

async fn perform_select(
    session: &BrowserSession,
    r: &ResolvedTarget,
    value: &str,
    by: &browser_agent_executor::SelectBy,
    options: &ActOptions,
) -> ExecutionResult {
    let tag = element_tag(session, &r.session, r.backend)
        .await
        .unwrap_or_default();
    let is_native = tag == "select" || (r.element.role == "combobox" && tag == "select");
    let is_text_combo =
        r.element.role == "combobox" && (tag == "input" || r.element.role == "textbox");
    if is_native {
        let selector = match by {
            browser_agent_executor::SelectBy::Value => "option.value",
            browser_agent_executor::SelectBy::Label => "(option.text || '').trim()",
        };
        let script = format!(
            "function(){{ const wanted = {value:?}; const options = [...this.options]; const targetIndex = options.findIndex(option => {selector} === wanted); return JSON.stringify({{targetIndex, selectedIndex: this.selectedIndex, multiple: this.multiple}}); }}"
        );
        let selection = call_on_backend(session, &r.session, r.backend, &script)
            .await?
            .as_str()
            .and_then(|json| serde_json::from_str::<Value>(json).ok())
            .ok_or_else(|| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    Some(r.reference.to_string()),
                    "native select returned malformed option metadata",
                )
            })?;
        let target_index = selection
            .get("targetIndex")
            .and_then(Value::as_i64)
            .filter(|index| *index >= 0)
            .ok_or_else(|| {
                ExecutionFailure::new(
                    ExecutionFailureKind::InteractionRejected,
                    Some(r.reference.to_string()),
                    format!("native option {value:?} not found by {by:?}"),
                )
            })?;
        let selected_index = selection
            .get("selectedIndex")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        if selection
            .get("multiple")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            return Err(ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                Some(r.reference.to_string()),
                "multi-select controls are not supported by this action",
            ));
        }

        focus_backend(session, &r.session, r.backend).await?;
        let first_index = if selected_index < 0 || target_index < selected_index {
            press_key(session, &r.session, "Home").await?;
            0
        } else {
            selected_index
        };
        for _ in first_index..target_index {
            press_key(session, &r.session, "ArrowDown").await?;
        }
        press_key(session, &r.session, "Enter").await?;
        return Ok(ExecutionEvidence {
            method: "cdp-input".into(),
            detail: format!("selected native option {value:?} by {by:?}"),
        });
    }
    if is_text_combo || r.element.role == "textbox" {
        // Datalist/ARIA textbox combo: type the value, confirm, verify text.
        focus_backend(session, &r.session, r.backend).await?;
        key_with_modifiers(session, &r.session, "a", 65, 2).await?;
        press_key(session, &r.session, "Backspace").await?;
        cmd(
            session,
            &r.session,
            "Input.insertText",
            serde_json::json!({"text": value}),
        )
        .await?;
        press_key(session, &r.session, "Enter").await?;
        return Ok(ExecutionEvidence {
            method: "cdp-input".into(),
            detail: format!("typed {value:?}"),
        });
    }
    // Custom dropdown: open → wait for options → click the matching option.
    perform_click(session, r, &MouseButton::Left, 1, options).await?;
    wait_for_evaluate(
        session,
        &r.session,
        "!!document.querySelector('[role=listbox],[role=option],select')",
        Duration::from_secs(2),
    )
    .await;
    // Fresh observation to find the option, then click it like any target.
    let tab_id = session_tab_id(session, r).await?;
    let post = observe_full(session, &tab_id).await.map_err(|e| {
        ExecutionFailure::new(
            ExecutionFailureKind::ActionTimeout,
            Some(r.reference.to_string()),
            format!("re-observe for option failed: {e}"),
        )
    })?;
    let option = post
        .elements
        .iter()
        .find(|e| {
            e.semantic_kind == browser_agent_observation::SemanticKind::Option
                && match by {
                    browser_agent_executor::SelectBy::Value => {
                        e.value.as_deref() == Some(value)
                            || e.accessible_name.as_deref() == Some(value)
                    }
                    browser_agent_executor::SelectBy::Label => {
                        e.accessible_name.as_deref() == Some(value)
                            || e.text.as_deref() == Some(value)
                    }
                }
        })
        .cloned()
        .ok_or_else(|| {
            ExecutionFailure::new(
                ExecutionFailureKind::InteractionRejected,
                Some(r.reference.to_string()),
                format!("custom option {value:?} not found after opening"),
            )
        })?;
    let backend = option.backend_node_id.ok_or_else(|| {
        ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(r.reference.to_string()),
            "custom option has no backend node",
        )
    })?;
    let option_ref = browser_agent_element_registry::ElementRef::new(
        option.id,
        &option.reference,
        option.generation,
    );
    let option_target = ResolvedTarget {
        reference: option_ref,
        backend,
        session: r.session.clone(),
        element: option,
    };
    perform_click(session, &option_target, &MouseButton::Left, 1, options).await?;
    Ok(ExecutionEvidence {
        method: "custom-dropdown".into(),
        detail: format!("chose {value:?} by {by:?}"),
    })
}

async fn session_tab_id(
    session: &BrowserSession,
    r: &ResolvedTarget,
) -> Result<TabId, ExecutionFailure> {
    // The tab is the registry owner of the resolved id: find it.
    let registries = session.registries_map().read().await;
    for (target, registry) in registries.iter() {
        if registry.lookup_id(r.reference.id).is_some() {
            return Ok(TabId::from(target.as_str().to_string()));
        }
    }
    Err(ExecutionFailure::new(
        ExecutionFailureKind::TabClosed,
        Some(r.reference.to_string()),
        "owning tab vanished mid-select",
    ))
}

// -- check ------------------------------------------------------------------

async fn perform_check(
    session: &BrowserSession,
    r: &ResolvedTarget,
    checked: bool,
    options: &ActOptions,
) -> ExecutionResult {
    if read_checked(session, &r.session, r.backend).await == Some(checked) {
        return Ok(ExecutionEvidence {
            method: "none".into(),
            detail: "already in desired state".into(),
        });
    }
    perform_click(session, r, &MouseButton::Left, 1, options).await?;
    match read_checked(session, &r.session, r.backend).await {
        Some(v) if v == checked => Ok(ExecutionEvidence {
            method: "cdp-input".into(),
            detail: format!("checked={checked}"),
        }),
        other => Err(ExecutionFailure::new(
            ExecutionFailureKind::InteractionRejected,
            Some(r.reference.to_string()),
            format!("checked state stuck: {other:?}, wanted {checked}"),
        )),
    }
}

// -- scroll / press / history -------------------------------------------------

async fn perform_scroll(
    session: &BrowserSession,
    tab: &TabId,
    resolved: Option<&ResolvedTarget>,
    dx: i64,
    dy: i64,
) -> ExecutionResult {
    let (_, cdp_session) = session.tab_session_pub(tab).await.map_err(|e| {
        ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
    })?;
    let before = read_scroll(session, &cdp_session, resolved.map(|r| r.backend)).await;
    let (x, y) = if let Some(r) = resolved {
        viewport_point(session, &r.session, r.backend).await?
    } else {
        let viewport = cmd(
            session,
            &cdp_session,
            "Page.getLayoutMetrics",
            serde_json::json!({}),
        )
        .await?;
        let visual = viewport.get("cssVisualViewport").unwrap_or(&Value::Null);
        let width = visual
            .get("clientWidth")
            .and_then(Value::as_f64)
            .unwrap_or(800.0);
        let height = visual
            .get("clientHeight")
            .and_then(Value::as_f64)
            .unwrap_or(600.0);
        ((width / 2.0).round() as i64, (height / 2.0).round() as i64)
    };
    cmd(
        session,
        &cdp_session,
        "Input.dispatchMouseEvent",
        serde_json::json!({
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": dx,
            "deltaY": dy,
        }),
    )
    .await?;
    let after = read_scroll(session, &cdp_session, resolved.map(|r| r.backend)).await;
    Ok(ExecutionEvidence {
        method: "scroll".into(),
        detail: format!("scroll {before:?} → {after:?}"),
    })
}

async fn history_go(session: &BrowserSession, tab: &TabId, delta: i32) -> ExecutionResult {
    let (_, cdp_session) = session.tab_session_pub(tab).await.map_err(|e| {
        ExecutionFailure::new(ExecutionFailureKind::TabClosed, None, format!("{e}"))
    })?;
    let history = cmd(
        session,
        &cdp_session,
        "Page.getNavigationHistory",
        serde_json::json!({}),
    )
    .await?;
    let index = history
        .get("currentIndex")
        .and_then(Value::as_i64)
        .unwrap_or(0);
    let entries = history
        .get("entries")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let target_idx = index + delta as i64;
    let entry = entries.get(target_idx as usize).ok_or_else(|| {
        ExecutionFailure::new(
            ExecutionFailureKind::NavigationRace,
            None,
            format!("no history entry at index {target_idx}"),
        )
    })?;
    let entry_id = entry.get("id").and_then(Value::as_i64).unwrap_or(-1);
    cmd(
        session,
        &cdp_session,
        "Page.navigateToHistoryEntry",
        serde_json::json!({"entryId": entry_id}),
    )
    .await?;
    wait_ready(session, &cdp_session, None).await?;
    Ok(ExecutionEvidence {
        method: "history".into(),
        detail: format!("went {delta}"),
    })
}
