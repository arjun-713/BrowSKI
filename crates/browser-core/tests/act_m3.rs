//! Milestone-3 gate suite: executor + verification against the adversarial
//! fixture corpus (`tests/fixtures/m3/`).
//!
//! Principle under test: CDP command success != task success. Every gate
//! asserts on [`ActionOutcome`] (execution evidence + verification verdict),
//! never on the absence of a protocol error.

use browser_agent_core::{ActionOutcome, BrowserSession};
use browser_agent_element_registry::ElementRef;
use browser_agent_executor::{ActOptions, BrowserAction, ClickOptions, ExecutionFailureKind};
use browser_agent_verification::VerificationStatus;
use browser_agent_verification::{EffectExpectation, ExpectedEffect};
use std::path::PathBuf;
use std::time::{Duration, Instant};

static M3_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn require_chrome() -> bool {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return false;
    }
    true
}

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/m3")
}

/// Static file server for the M3 corpus.
async fn fixture_server() -> String {
    let dir = fixture_dir();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                break;
            };
            let dir = dir.clone();
            tokio::spawn(async move {
                use tokio::io::{AsyncReadExt, AsyncWriteExt};
                let mut buf = Vec::new();
                let mut tmp = [0u8; 4096];
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") && buf.len() < 32 * 1024 {
                    match stream.read(&mut tmp).await {
                        Ok(0) | Err(_) => break,
                        Ok(n) => buf.extend_from_slice(&tmp[..n]),
                    }
                }
                let request = String::from_utf8_lossy(&buf);
                let raw_path = request
                    .lines()
                    .next()
                    .and_then(|l| l.split_whitespace().nth(1))
                    .unwrap_or("/");
                let mut path = raw_path.split('?').next().unwrap_or(raw_path);
                if path.ends_with('/') {
                    path = "/confirmation.html";
                }
                let file = dir.join(path.trim_start_matches('/'));
                let body = tokio::fs::read(&file)
                    .await
                    .unwrap_or_else(|_| b"not found".to_vec());
                let (status, ctype) = if body != b"not found" {
                    ("200 OK", "text/html; charset=utf-8")
                } else {
                    ("404 Not Found", "text/plain")
                };
                let response = format!(
                    "HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes()).await;
                let _ = stream.write_all(&body).await;
            });
        }
    });
    base
}

async fn launch() -> Option<BrowserSession> {
    if !require_chrome() {
        return None;
    }
    Some(BrowserSession::launch().await.expect("launch"))
}

/// Resolve an alias to a full ref via the latest snapshot.
async fn rref(session: &BrowserSession, tab: &browser_agent_cdp::TabId, alias: &str) -> ElementRef {
    let snap = session.observe_tab(tab).await.expect("observe for resolve");
    let el = snap
        .by_ref(alias)
        .unwrap_or_else(|| panic!("no such ref {alias}"));
    ElementRef::new(el.id, alias, el.generation)
}

fn click(target: ElementRef, expected_effect: ExpectedEffect) -> BrowserAction {
    BrowserAction::Click {
        target,
        options: ClickOptions::default(),
        expected_effect,
    }
}

fn succeeded(outcome: &ActionOutcome) -> bool {
    if !outcome.succeeded() {
        eprintln!(
            "NOT SUCCEEDED: execution={:?} verification={:?}",
            outcome.execution, outcome.verification
        );
    }
    outcome.succeeded()
}

// ---------------------------------------------------------------------------
// gates
// ---------------------------------------------------------------------------

/// Gate: native click 100%.
#[tokio::test]
async fn m3_native_click() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@increment").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    assert_eq!(outcome.attempts, 1);
    // Counter text advanced (tracked element text change).
    assert!(
        outcome
            .delta
            .changed
            .iter()
            .any(|c| c.fields.iter().any(|f| f.contains('1'))),
        "delta: {:?}",
        outcome.delta
    );
    session.close().await.expect("close");
}

/// Gate: controlled input typing 100%.
#[tokio::test]
async fn m3_controlled_input_typing() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/input-controlled-react.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@nickname").await;
    let outcome = session
        .act(
            &tab,
            BrowserAction::Type {
                target,
                text: "mallik".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    assert_eq!(outcome.verification.check, "value-is");
    // Framework mirror synced (input event dispatched, not just property set).
    let mirror = session
        .execute(&tab, "document.getElementById('mirror').textContent")
        .await
        .expect("read mirror");
    assert_eq!(mirror.as_str(), Some("mallik"), "mirror: {mirror}");
    // Churn-tolerant input on the same page still works afterwards.
    session
        .navigate(&format!("{base}/input-rerender.html"))
        .await
        .expect("nav");
    let target = rref(&session, &tab, "@churning_input").await;
    let outcome = session
        .act(
            &tab,
            BrowserAction::Type {
                target,
                text: "abc".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    session.close().await.expect("close");
}

/// Gate: native select 100% (by value and by label).
#[tokio::test]
async fn m3_native_select() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/native-select.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    for (value, by) in [
        ("ka", browser_agent_executor::SelectBy::Value),
        ("Maharashtra", browser_agent_executor::SelectBy::Label),
    ] {
        let target = rref(&session, &tab, "@state").await;
        let outcome = session
            .act(
                &tab,
                BrowserAction::Select {
                    target,
                    value: value.into(),
                    by: by.clone(),
                    expected_effect: ExpectedEffect::Unspecified,
                },
                ActOptions::default(),
            )
            .await;
        assert!(succeeded(&outcome), "select {value:?}");
        assert_eq!(outcome.verification.check, "select-value");
        assert_eq!(outcome.execution.as_ref().unwrap().method, "cdp-input");
    }
    session.close().await.expect("close");
}

/// Gate: checkbox/radio 100%.
#[tokio::test]
async fn m3_checkbox_radio() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/checkbox-radio.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    // Uncheck an already-checked box, check an unchecked one, switch radio.
    for (alias, checked) in [("@newsletter", false), ("@offers", true), ("@s", true)] {
        let target = rref(&session, &tab, alias).await;
        let outcome = session
            .act(
                &tab,
                BrowserAction::Check {
                    target,
                    checked,
                    expected_effect: ExpectedEffect::Unspecified,
                },
                ActOptions::default(),
            )
            .await;
        assert!(succeeded(&outcome), "check {alias}={checked}");
    }
    session.close().await.expect("close");
}

/// Gate: SPA transition verification 100%.
#[tokio::test]
async fn m3_spa_transition() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/spa-route.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@section_a").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    let after = session.observe().await.expect("observe");
    assert!(after.url.ends_with("#/a"), "url: {}", after.url);
    session.close().await.expect("close");
}

/// Gate: full navigation verification 100%.
#[tokio::test]
async fn m3_full_navigation() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/navigation-button.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@go_to_confirmation").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    assert!(outcome.after_generation > outcome.before_generation);
    let after = session.observe().await.expect("observe");
    assert!(
        after.url.ends_with("confirmation.html"),
        "url: {}",
        after.url
    );
    session.close().await.expect("close");
}

/// Gate: direct navigation, browser history, and reload are verified.
#[tokio::test]
async fn m3_navigation_history_actions() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    let tab = session.active_tab().await.expect("active").id;
    let start_url = format!("{base}/navigation-button.html");
    let navigate = session
        .act(
            &tab,
            BrowserAction::Navigate {
                url: start_url,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&navigate), "navigate: {navigate:?}");

    let go = rref(&session, &tab, "@go_to_confirmation").await;
    let clicked = session
        .act(
            &tab,
            click(
                go,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&clicked), "navigation click: {clicked:?}");

    let back = session
        .act(
            &tab,
            BrowserAction::Back {
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&back), "back: {back:?}");
    assert!(session
        .observe()
        .await
        .expect("back snapshot")
        .url
        .ends_with("navigation-button.html"));

    let forward = session
        .act(
            &tab,
            BrowserAction::Forward {
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&forward), "forward: {forward:?}");
    assert!(session
        .observe()
        .await
        .expect("forward snapshot")
        .url
        .ends_with("confirmation.html"));

    let reload = session
        .act(
            &tab,
            BrowserAction::Reload {
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&reload), "reload: {reload:?}");
    assert_eq!(reload.verification.check, "document-reloaded");
    session.close().await.expect("close");
}

/// Gate: keyboard activation, hover state, and trusted wheel scrolling work.
#[tokio::test]
async fn m3_keyboard_hover_and_scroll() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let increment = rref(&session, &tab, "@increment").await;
    let pressed = session
        .act(
            &tab,
            BrowserAction::Press {
                target: Some(increment),
                key: "Enter".into(),
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&pressed), "press: {pressed:?}");

    let increment = rref(&session, &tab, "@increment").await;
    let hovered = session
        .act(
            &tab,
            BrowserAction::Hover {
                target: increment,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&hovered), "hover: {hovered:?}");
    assert_eq!(hovered.verification.check, "hover-match");

    session
        .navigate(&format!("{base}/scroll.html"))
        .await
        .expect("nav");
    let scrolled = session
        .act(
            &tab,
            BrowserAction::Scroll {
                target: None,
                dx: 0,
                dy: 400,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&scrolled), "scroll: {scrolled:?}");
    assert_eq!(scrolled.verification.check, "scroll-changed");
    session.close().await.expect("close");
}

/// Gate: new-tab detection 100%.
#[tokio::test]
async fn m3_new_tab_detection() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/opens-new-tab.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before_tabs = session.tabs().await.len();
    let target = rref(&session, &tab, "@open_report").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::NewTabOpened]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    assert_eq!(outcome.verification.check, "new-tab-opened");
    let tabs = session.tabs().await;
    assert_eq!(tabs.len(), before_tabs + 1);
    // Cleanup: close the opened tab.
    let opened = tabs
        .iter()
        .find(|t| t.id != tab)
        .expect("new tab listed")
        .id
        .clone();
    session.close_tab(&opened).await.expect("close new tab");
    session.close().await.expect("close");
}

/// Gate: the typed NewTab action waits for the target to attach.
#[tokio::test]
async fn m3_new_tab_action() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before_tabs = session.tabs().await.len();
    let outcome = session
        .act(
            &tab,
            BrowserAction::NewTab {
                url: Some(format!("{base}/confirmation.html")),
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;

    assert!(succeeded(&outcome), "outcome: {outcome:?}");
    assert_eq!(outcome.verification.check, "new-tab-opened");
    let tabs = session.tabs().await;
    assert_eq!(tabs.len(), before_tabs + 1);
    let opened = tabs
        .iter()
        .find(|candidate| candidate.id != tab)
        .expect("new tab listed")
        .id
        .clone();
    let activated = session
        .act(
            &tab,
            BrowserAction::ActivateTab {
                tab: opened.clone(),
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&activated), "activation: {activated:?}");
    assert_eq!(activated.verification.check, "tab-active");
    let closed = session
        .act(
            &tab,
            BrowserAction::CloseTab {
                tab: opened,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&closed), "close new tab: {closed:?}");
    assert_eq!(closed.verification.check, "tab-closed");
    session.close().await.expect("close");
}

/// Gate: closing the context tab verifies from lifecycle state.
#[tokio::test]
async fn m3_close_tab_action() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let outcome = session
        .act(
            &tab,
            BrowserAction::CloseTab {
                tab: tab.clone(),
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;

    assert!(succeeded(&outcome), "outcome: {outcome:?}");
    assert_eq!(outcome.verification.check, "tab-closed");
    assert!(!session.tabs().await.iter().any(|open| open.id == tab));
    session.close().await.expect("close");
}

/// Gate: dialog detection/handling 100%.
#[tokio::test]
async fn m3_dialog_detection() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/dialog.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@raise_alert").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::DialogOpened]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome), "outcome: {outcome:?}");
    assert_eq!(outcome.verification.check, "dialog-opened");
    // Dismiss through the typed action, then prove the executor remains usable.
    let dismissed = session
        .act(
            &tab,
            BrowserAction::HandleDialog {
                accept: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&dismissed), "dismissal: {dismissed:?}");
    assert_eq!(dismissed.verification.check, "dialog-closed");
    let other = rref(&session, &tab, "@other_action").await;
    let outcome = session
        .act(
            &tab,
            click(
                other,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    session.close().await.expect("close");
}

/// Gate: stale + ambiguous targets rejected 100%.
#[tokio::test]
async fn m3_stale_and_ambiguous_rejected() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    // Stale: bind on one page, navigate away (alias gone), act with old ref.
    session
        .navigate(&format!("{base}/form-flow.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let stale = rref(&session, &tab, "@first_name").await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let outcome = session
        .act(
            &tab,
            click(
                stale,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    assert!(
        matches!(
            outcome.execution,
            Err(ref f) if matches!(
                f.kind,
                ExecutionFailureKind::StaleTarget | ExecutionFailureKind::TargetNotFound
            )
        ),
        "execution: {:?}",
        outcome.execution
    );
    // Ambiguous: valid id, wrong alias → refused, never guessed.
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let real = rref(&session, &tab, "@increment").await;
    let confused = ElementRef::new(real.id, "@other_action", real.generation);
    let outcome = session
        .act(
            &tab,
            click(
                confused,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    assert!(
        matches!(
            outcome.execution,
            Err(ref f) if f.kind == ExecutionFailureKind::AmbiguousTarget
        ),
        "execution: {:?}",
        outcome.execution
    );
    session.close().await.expect("close");
}

/// Gate: occluded target not falsely successful 100% (+ recovery by caller).
#[tokio::test]
async fn m3_occluded_not_successful() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/overlay-intercept.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let buried = rref(&session, &tab, "@buried_action").await;
    let outcome = session
        .act(
            &tab,
            click(
                buried,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    assert!(
        matches!(
            outcome.execution,
            Err(ref f) if f.kind == ExecutionFailureKind::TargetOccluded
        ),
        "execution: {:?}",
        outcome.execution
    );
    assert_eq!(
        outcome.attempts, 3,
        "permanent occlusion stops at the bound"
    );
    assert_ne!(outcome.verification.status, VerificationStatus::Success);
    // Caller dismisses the veil, then the same intent succeeds.
    let dismiss = rref(&session, &tab, "@dismiss_veil").await;
    let dismissed = session
        .act(
            &tab,
            click(
                dismiss,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&dismissed));
    let buried = rref(&session, &tab, "@buried_action").await;
    let outcome = session
        .act(
            &tab,
            click(
                buried,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    session.close().await.expect("close");
}

/// Gate: no-effect click classified 100% (mechanics ok, effect disproven).
#[tokio::test]
async fn m3_no_effect_classified() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-no-effect.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let dead = rref(&session, &tab, "@does_nothing").await;
    let outcome = session
        .act(
            &tab,
            click(
                dead,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(
        outcome.execution.is_ok(),
        "mechanics ran: {:?}",
        outcome.execution
    );
    assert!(!outcome.succeeded());
    assert_eq!(outcome.verification.status, VerificationStatus::Failure);
    assert_eq!(outcome.verification.check, "no-effect");
    session.close().await.expect("close");
}

/// Gate: an ongoing spinner does not hold settling open.
#[tokio::test]
async fn m3_infinite_spinner_does_not_block_settling() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/infinite-spinner.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let start = rref(&session, &tab, "@start_task").await;
    let started = Instant::now();
    let outcome = session
        .act(
            &tab,
            click(
                start,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;

    assert!(succeeded(&outcome), "outcome: {outcome:?}");
    assert!(started.elapsed() < Duration::from_secs(4));
    session.close().await.expect("close");
}

/// Gate: bounded retries — transient cover recovers, permanent cover stops.
#[tokio::test]
async fn m3_bounded_retries() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    // Transient veil (800ms): mechanical retries ride it out.
    session
        .navigate(&format!("{base}/delayed-overlay.html?ms=800"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let go = rref(&session, &tab, "@go_now").await;
    let outcome = session
        .act(
            &tab,
            click(
                go,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome), "outcome: {outcome:?}");
    assert!(
        outcome.attempts >= 1 && outcome.attempts <= 3,
        "attempts: {}",
        outcome.attempts
    );
    // Permanent veil (30s): retries stop at the bound, no stranding.
    session
        .navigate(&format!("{base}/delayed-overlay.html?ms=30000"))
        .await
        .expect("nav");
    let go = rref(&session, &tab, "@go_now").await;
    let outcome = session
        .act(
            &tab,
            click(
                go,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    assert_eq!(
        outcome.attempts, 3,
        "must stop at the bound, got {}",
        outcome.attempts
    );
    assert_eq!(session.pending_commands().await, 0, "no stranded requests");
    session.close().await.expect("close");
}

/// Gate: executor usable after recoverable failure 100%.
#[tokio::test]
async fn m3_usable_after_failure() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    // Validation blocks the submit: classified failure, not a hang.
    session
        .navigate(&format!("{base}/validation-error.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let join = rref(&session, &tab, "@join").await;
    let outcome = session
        .act(
            &tab,
            click(
                join,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    // Fill the field, resubmit: full success on the confirmation page.
    let email = rref(&session, &tab, "@email").await;
    let typed = session
        .act(
            &tab,
            BrowserAction::Type {
                target: email,
                text: "a@b.co".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&typed));
    let join = rref(&session, &tab, "@join").await;
    let outcome = session
        .act(
            &tab,
            click(
                join,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    let after = session.observe().await.expect("observe");
    assert!(
        after.url.contains("confirmation.html"),
        "url: {}",
        after.url
    );
    // Node-swap staleness: old backend dies, executor fails cleanly and
    // stays usable on the stable control.
    session
        .navigate(&format!("{base}/stale-after-rerender.html"))
        .await
        .expect("nav");
    let victim = rref(&session, &tab, "@victim_input").await;
    session
        .execute(&tab, "document.getElementById('swap').click(); 'swapped'")
        .await
        .expect("swap");
    let outcome = session
        .act(
            &tab,
            BrowserAction::Type {
                target: victim,
                text: "x".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    // Healed by reacquire (same generation, same signals) or cleanly failed:
    // either way the executor must remain usable afterwards.
    eprintln!(
        "swap outcome: succeeded={} attempts={}",
        outcome.succeeded(),
        outcome.attempts
    );
    let stable = rref(&session, &tab, "@stable_input").await;
    let outcome = session
        .act(
            &tab,
            BrowserAction::Type {
                target: stable,
                text: "fine".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    session.close().await.expect("close");
}

/// Gate: verification determinism — identical state → identical result.
#[tokio::test]
async fn m3_verification_deterministic() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/click-success.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let target = rref(&session, &tab, "@increment").await;
    let outcome = session
        .act(
            &tab,
            click(
                target,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    // Re-verify the recorded transition twice: identical verdicts.
    let before = session.observe().await.expect("observe");
    let delta = session.observe_delta(&tab).await.expect("delta");
    let side = browser_agent_core::verification_side_effects();
    let v1 = browser_agent_core::verify_for_test(
        &ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
        "click",
        &before,
        &before,
        &delta,
        &side,
    );
    let v2 = browser_agent_core::verify_for_test(
        &ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
        "click",
        &before,
        &before,
        &delta,
        &side,
    );
    assert_eq!(v1, v2);
    session.close().await.expect("close");
}

/// Gate: first browser-action contract test — deterministic end-to-end flow,
/// no LLM: fill form → submit → confirmation.
#[tokio::test]
async fn m3_end_to_end_form_flow() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/form-flow.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let start = std::time::Instant::now();

    let first = rref(&session, &tab, "@first_name").await;
    let o = session
        .act(
            &tab,
            BrowserAction::Type {
                target: first,
                text: "Mallik".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&o), "type first: {o:?}");

    let email = rref(&session, &tab, "@email").await;
    let o = session
        .act(
            &tab,
            BrowserAction::Type {
                target: email,
                text: "m@x.co".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&o), "type email: {o:?}");

    let state = rref(&session, &tab, "@state").await;
    let o = session
        .act(
            &tab,
            BrowserAction::Select {
                target: state,
                value: "ka".into(),
                by: browser_agent_executor::SelectBy::Value,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&o), "select: {o:?}");

    let terms = rref(&session, &tab, "@accept_terms").await;
    let o = session
        .act(
            &tab,
            BrowserAction::Check {
                target: terms,
                checked: true,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&o), "check: {o:?}");

    let go = rref(&session, &tab, "@continue").await;
    let o = session
        .act(
            &tab,
            click(
                go,
                ExpectedEffect::AnyOf(vec![EffectExpectation::UrlChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&o), "submit: {o:?}");

    let after = session.observe().await.expect("observe");
    assert!(
        after.url.contains("confirmation.html"),
        "url: {}",
        after.url
    );
    assert!(
        after
            .elements
            .iter()
            .any(|e| e.text.as_deref() == Some("Account created")
                || e.accessible_name.as_deref() == Some("Account created")),
        "confirmation heading missing"
    );
    eprintln!(
        "[metrics] e2e_form_flow_ms={:.0}",
        start.elapsed().as_secs_f64() * 1000.0
    );
    session.close().await.expect("close");
}

/// Gate: custom combobox + contenteditable + frame actions.
#[tokio::test]
async fn m3_custom_controls_and_frames() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;

    // Custom dropdown: open, choose Mango by label.
    session
        .navigate(&format!("{base}/custom-combobox.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let combo = rref(&session, &tab, "@fruit").await;
    let outcome = session
        .act(
            &tab,
            BrowserAction::Select {
                target: combo,
                value: "Mango".into(),
                by: browser_agent_executor::SelectBy::Label,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome), "custom combo: {outcome:?}");

    // Contenteditable typing.
    session
        .navigate(&format!("{base}/contenteditable.html"))
        .await
        .expect("nav");
    let note = rref(&session, &tab, "@note_editor").await;
    let outcome = session
        .act(
            &tab,
            BrowserAction::Type {
                target: note,
                text: "hello".into(),
                clear: true,
                submit: false,
                expected_effect: ExpectedEffect::Unspecified,
            },
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome), "contenteditable: {outcome:?}");

    // Frame action: click the button inside the iframe.
    session
        .navigate(&format!("{base}/frame-action.html"))
        .await
        .expect("nav");
    let bump = rref(&session, &tab, "@bump").await;
    let outcome = session
        .act(
            &tab,
            click(
                bump,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome), "frame click: {outcome:?}");
    session.close().await.expect("close");
}

/// Gate: disabled-then-enabled is terminal fast (M3 does not wait out the
/// world; strategy waits belong to M4+), then succeeds once enabled.
#[tokio::test]
async fn m3_disabled_is_terminal_fast() {
    let _guard = M3_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/button-disabled-then-enabled.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let late = rref(&session, &tab, "@not_yet").await;
    let start = std::time::Instant::now();
    let outcome = session
        .act(
            &tab,
            click(
                late,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(!outcome.succeeded());
    assert!(
        matches!(
            outcome.execution,
            Err(ref f) if f.kind == ExecutionFailureKind::TargetDisabled
        ),
        "execution: {:?}",
        outcome.execution
    );
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "disabled must fail fast, took {:?}",
        start.elapsed()
    );
    // Once enabled, the same intent succeeds.
    tokio::time::sleep(Duration::from_millis(900)).await;
    let late = rref(&session, &tab, "@ready_now").await;
    let outcome = session
        .act(
            &tab,
            click(
                late,
                ExpectedEffect::AnyOf(vec![EffectExpectation::AnyElementChanged]),
            ),
            ActOptions::default(),
        )
        .await;
    assert!(succeeded(&outcome));
    session.close().await.expect("close");
}
