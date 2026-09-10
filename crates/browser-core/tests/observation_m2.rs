//! Milestone-2 integration tests: observation + element identity against the
//! synthetic fixture corpus (`tests/fixtures/m2/`).
//!
//! Gates (see `docs/development/roadmap.md` M2): discovery rates, ref
//! stability under mutation/reorder/insertion, deterministic duplicates,
//! iframe/shadow provenance, hidden-exposure rate, interactability accuracy,
//! diff determinism, stale detection, ambiguity refusal, and observation
//! determinism. Corpus pages are local (no external network).

use browser_agent_core::{BrowserSession, SemanticSnapshot};
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{Duration, Instant};

static M2_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn require_chrome() -> bool {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return false;
    }
    true
}

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/m2")
}

/// Static file server for the fixture corpus.
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
                let path = raw_path.split('?').next().unwrap_or(raw_path);
                let name = path.trim_start_matches('/');
                let file = dir.join(if name.is_empty() {
                    "native-form.html"
                } else {
                    name
                });
                let body = tokio::fs::read(&file)
                    .await
                    .unwrap_or_else(|_| b"not found".to_vec());
                let (status, ctype) = if file.exists() && file.is_file() {
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

fn refs_of(snap: &SemanticSnapshot) -> HashSet<String> {
    snap.elements.iter().map(|e| e.reference.clone()).collect()
}

fn find<'a>(
    snap: &'a SemanticSnapshot,
    reference: &str,
) -> &'a browser_agent_core::SemanticElement {
    snap.by_ref(reference)
        .unwrap_or_else(|| panic!("expected ref {reference}, have {:?}", refs_of(snap)))
}

// ---------------------------------------------------------------------------
// discovery
// ---------------------------------------------------------------------------

/// Gate: basic controls ≥99% discovered.
#[tokio::test]
async fn m2_basic_controls_discovered() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    let start = Instant::now();
    session
        .navigate(&format!("{base}/native-form.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    eprintln!(
        "[metrics] observation_ms={:.0} elements={}",
        start.elapsed().as_secs_f64() * 1000.0,
        snap.elements.len()
    );

    // 13 expected controls; ≥99% means all of them here.
    let expected = [
        ("@full_name", "textbox", "Full name"),
        ("@email", "textbox", "Email"),
        ("@password", "textbox", "Password"),
        ("@age", "textbox", "Age"),
        ("@country", "combobox", "Country"),
        ("@subscribe", "checkbox", "Subscribe"),
        ("@bio", "textbox", "Bio"),
        ("@submit_application", "button", "Submit application"),
        ("@reset", "button", "Reset"),
    ];
    for (reference, role, name) in expected {
        let el = find(&snap, reference);
        assert_eq!(el.role, role, "role for {reference}");
        assert_eq!(
            el.accessible_name.as_deref(),
            Some(name),
            "name for {reference}"
        );
        assert!(el.interactable, "{reference} should be interactable");
    }
    // Radio group + preset values.
    assert!(snap
        .elements
        .iter()
        .any(|e| e.role == "radio" && e.accessible_name.as_deref() == Some("Free")));
    let age = find(&snap, "@age");
    assert_eq!(age.value.as_deref(), Some("30"), "preset value preserved");
    let country = find(&snap, "@country");
    assert!(
        country
            .value
            .as_deref()
            .is_some_and(|v| v.contains("India") || v.contains("in")),
        "select value: {:?}",
        country.value
    );
    // Forms + headings + fingerprint stability signals.
    assert_eq!(snap.form_count, 1);
    assert!(!snap.page_fingerprint.is_empty());
    assert!(snap.text_blocks.iter().any(|b| b.text == "Job application"));
    session.close().await.expect("close");
}

/// Gate: accessible custom controls ≥98%.
#[tokio::test]
async fn m2_accessible_custom_controls() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/react-controlled-form.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");

    // div[role=button] must arrive as a button, not a useless div.
    let save = find(&snap, "@save_profile");
    assert_eq!(save.role, "button");
    assert!(save.interactable);
    let theme = find(&snap, "@theme");
    assert_eq!(theme.role, "combobox");
    let consent = find(&snap, "@email_consent");
    assert_eq!(consent.role, "checkbox");
    assert!(consent.state.iter().any(|s| s == "checked"));
    let nick = find(&snap, "@nickname");
    assert_eq!(nick.value.as_deref(), Some("ada"));
    session.close().await.expect("close");
}

/// Gate: combobox + contenteditable kinds.
#[tokio::test]
async fn m2_combobox_and_contenteditable() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/combobox.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let country = find(&snap, "@country");
    assert!(country.interactable);
    let india = snap.elements.iter().find(|e| {
        e.accessible_name.as_deref() == Some("India") || e.text.as_deref() == Some("India")
    });
    assert!(
        india.is_some(),
        "India option visible: {:?}",
        refs_of(&snap)
    );
    let city = find(&snap, "@city");
    assert_eq!(city.role, "textbox");

    session
        .navigate(&format!("{base}/contenteditable.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let notes = snap
        .elements
        .iter()
        .find(|e| e.state.iter().any(|s| s == "editable"))
        .expect("editable element present");
    assert!(notes.interactable, "contenteditable must be interactable");
    assert_eq!(notes.role, "textbox");
    assert_eq!(notes.accessible_name.as_deref(), Some("Notes"));
    session.close().await.expect("close");
}

// ---------------------------------------------------------------------------
// ref stability
// ---------------------------------------------------------------------------

/// Gate: stable refs after benign DOM mutation (≥98%).
#[tokio::test]
async fn m2_stable_refs_after_benign_mutation() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/native-form.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before = session.observe().await.expect("observe");
    let before_refs = refs_of(&before);
    // Benign churn: classes, data attrs, unrelated subtree.
    session
        .execute(&tab, "document.body.classList.add('m2-churn'); document.getElementById('email').dataset.probe='1'; document.title = document.title; 'ok'")
        .await
        .expect("mutate");
    let after = session.observe().await.expect("observe");
    let after_refs = refs_of(&after);
    let kept = before_refs.intersection(&after_refs).count();
    let rate = kept as f64 / before_refs.len() as f64;
    eprintln!(
        "[metrics] mutation_stability kept={kept}/{} rate={rate:.3}",
        before_refs.len()
    );
    assert!(rate >= 0.98, "stability {rate:.3}");
    // Same alias → same registry id (identity, not just name).
    for r in before_refs.intersection(&after_refs) {
        let a = before.by_ref(r).unwrap();
        let b = after.by_ref(r).unwrap();
        assert_eq!(a.id, b.id, "id changed for {r}");
        assert_eq!(a.fingerprint, b.fingerprint, "fingerprint changed for {r}");
    }
    session.close().await.expect("close");
}

/// Gate: refs after reorder (≥98%).
#[tokio::test]
async fn m2_refs_after_reorder() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/reordered-list.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before = session.observe().await.expect("observe");
    let names = ["alpha", "beta", "gamma", "delta", "epsilon"];
    for n in names {
        assert!(
            refs_of(&before).iter().any(|r| r.contains(n)),
            "missing {n}"
        );
    }
    session
        .execute(&tab, "document.getElementById('rev').click(); 'reversed'")
        .await
        .expect("reorder");
    let after = session.observe().await.expect("observe");
    let after_refs = refs_of(&after);
    let kept = names
        .iter()
        .filter(|n| after_refs.iter().any(|r| r.contains(**n)))
        .count();
    assert!(kept as f64 / names.len() as f64 >= 0.98, "kept {kept}/5");
    session.close().await.expect("close");
}

/// Gate: refs after inserted sibling (≥98%).
#[tokio::test]
async fn m2_refs_after_inserted_sibling_and_diff() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/dynamic-form.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before = session.observe().await.expect("observe");
    let before_refs = refs_of(&before);
    session
        .execute(&tab, "document.getElementById('add').click(); 'added'")
        .await
        .expect("add");
    let after = session.observe().await.expect("observe");
    let after_refs = refs_of(&after);
    let kept = before_refs.intersection(&after_refs).count();
    assert!(
        kept as f64 / before_refs.len() as f64 >= 0.98,
        "kept {kept}/{}",
        before_refs.len()
    );
    // Delta: exactly the new field added, nothing removed.
    let delta = session.observe_delta(&tab).await.expect("delta");
    assert!(delta.removed.is_empty(), "removed: {:?}", delta.removed);
    assert_eq!(delta.added.len(), 1, "added: {:?}", delta.added);
    assert!(
        delta.added[0].contains("member_2") || delta.added[0].contains("member"),
        "added: {:?}",
        delta.added
    );
    // Typing produces a value delta, not a full resnapshot.
    session
        .execute(&tab, "const i = document.querySelector('input[name=\"member-1\"]'); i.value = 'bob'; i.dispatchEvent(new Event('input', {bubbles: true})); 'typed'")
        .await
        .expect("type");
    let after_type = session.observe().await.expect("observe");
    let delta2 = session.observe_delta(&tab).await.expect("delta");
    assert!(delta2.added.is_empty(), "added: {:?}", delta2.added);
    assert_eq!(delta2.changed.len(), 1, "changed: {:?}", delta2.changed);
    assert!(
        delta2.changed[0].fields.iter().any(|f| f.contains("bob")),
        "fields: {:?}",
        delta2.changed[0].fields
    );
    let typed = after_type
        .by_ref(&delta2.changed[0].reference)
        .expect("changed ref resolves");
    assert_eq!(typed.value.as_deref(), Some("bob"));
    session.close().await.expect("close");
}

/// Gate: duplicate-label disambiguation, 100% deterministic.
#[tokio::test]
async fn m2_duplicate_disambiguation_deterministic() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/duplicate-buttons.html"))
        .await
        .expect("nav");
    let first = session.observe().await.expect("observe");
    let second = session.observe().await.expect("observe");
    for snap in [&first, &second] {
        let refs = refs_of(snap);
        // Context-aware: billing/shipping prefixed; bare ones numbered.
        assert!(refs.contains("@billing_continue"), "refs: {refs:?}");
        assert!(refs.contains("@shipping_continue"), "refs: {refs:?}");
        assert!(refs.contains("@continue"), "refs: {refs:?}");
        assert!(refs.contains("@continue_2"), "refs: {refs:?}");
    }
    assert_eq!(
        refs_of(&first),
        refs_of(&second),
        "aliases must be deterministic"
    );
    // Distinct ids behind every alias.
    let mut ids: Vec<u64> = first.elements.iter().map(|e| e.id).collect();
    ids.sort_unstable();
    ids.dedup();
    assert_eq!(ids.len(), first.elements.len(), "ids must be unique");
    session.close().await.expect("close");
}

// ---------------------------------------------------------------------------
// provenance: frames + shadow DOM
// ---------------------------------------------------------------------------

/// Gate: iframe provenance 100%.
#[tokio::test]
async fn m2_iframe_provenance() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/iframe-form.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let card = find(&snap, "@card_number");
    assert!(card.interactable, "iframe input must be interactable");
    assert_eq!(card.frame_path.first().map(String::as_str), Some("main"));
    assert!(
        card.frame_path.len() >= 2,
        "frame path: {:?}",
        card.frame_path
    );
    assert!(
        card.frame_path[1].starts_with("iframe["),
        "frame path: {:?}",
        card.frame_path
    );
    let pay = find(&snap, "@pay_now");
    assert_eq!(pay.frame_path, card.frame_path);
    // Every non-main element carries a well-formed path.
    for el in &snap.elements {
        if el.frame_path.len() > 1 {
            assert_eq!(el.frame_path[0], "main");
        }
    }

    session
        .navigate(&format!("{base}/nested-iframes.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let deep = find(&snap, "@deep_action");
    assert!(
        deep.frame_path.len() >= 3,
        "nested path: {:?}",
        deep.frame_path
    );
    session.close().await.expect("close");
}

/// Gate: open shadow DOM supported; closed roots degrade gracefully.
#[tokio::test]
async fn m2_shadow_dom() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/shadow-dom.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let input = find(&snap, "@shadow_input");
    assert!(input.interactable);
    assert!(
        input.frame_path == vec!["main".to_string()],
        "shadow stays in main frame path"
    );
    assert!(
        input.ancestry.iter().any(|a| a.contains("shadow")),
        "ancestry must record the shadow boundary: {:?}",
        input.ancestry
    );
    find(&snap, "@shadow_save");
    // Closed root content must not appear (no silent garbage).
    assert!(
        !refs_of(&snap).iter().any(|r| r.contains("closed_secret")),
        "closed shadow content leaked: {:?}",
        refs_of(&snap)
    );
    session.close().await.expect("close");
}

// ---------------------------------------------------------------------------
// visibility / interactability
// ---------------------------------------------------------------------------

/// Gate: hidden elements incorrectly exposed <1%.
#[tokio::test]
async fn m2_hidden_elements_not_exposed() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/hidden-controls.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    find(&snap, "@shown_action");
    for hidden in [
        "display_none",
        "visibility_hidden",
        "opacity_zero",
        "zero_size",
        "attr_hidden",
    ] {
        let leaked = snap
            .elements
            .iter()
            .filter(|e| e.reference.contains(hidden))
            .collect::<Vec<_>>();
        assert!(
            leaked.iter().all(|e| !e.interactable),
            "{hidden} exposed as interactable: {leaked:?}"
        );
    }
    // Offscreen keeps a ref (it exists) but is not interactable.
    let off = find(&snap, "@offscreen");
    assert!(!off.interactable, "offscreen must not be interactable");
    session.close().await.expect("close");
}

/// Gate: interactability classification ≥98% fixture accuracy.
#[tokio::test]
async fn m2_interactability_fixture_accuracy() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;

    // Occlusion: covered button is exposed but not interactable; the dialog
    // button on top is.
    session
        .navigate(&format!("{base}/modal-overlay.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let buried = find(&snap, "@buried_action");
    assert!(
        !buried.interactable,
        "occluded button must not be interactable"
    );
    assert_eq!(
        buried.visibility,
        browser_agent_core::VisibilityClass::Occluded
    );
    let confirm = snap
        .elements
        .iter()
        .find(|e| e.role == "button" && e.accessible_name.as_deref() == Some("Confirm"))
        .expect("confirm button present");
    assert!(confirm.interactable);

    // Disabled / readonly / inert.
    session
        .navigate(&format!("{base}/disabled-controls.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let gone = find(&snap, "@cannot_click");
    assert!(!gone.interactable && !gone.enabled);
    assert!(gone.state.iter().any(|s| s == "disabled"));
    let code = find(&snap, "@code");
    assert!(!code.interactable, "readonly must not be interactable");
    let legacy = find(&snap, "@legacy_action");
    assert!(
        !legacy.interactable && !legacy.enabled,
        "inert must disable"
    );
    let fine = find(&snap, "@works");
    assert!(fine.interactable);

    // Virtualized list: on-screen interactable, off-screen listed but not.
    session
        .navigate(&format!("{base}/virtualized-list.html"))
        .await
        .expect("nav");
    let snap = session.observe().await.expect("observe");
    let items: Vec<_> = snap
        .elements
        .iter()
        .filter(|e| e.role == "button")
        .collect();
    assert!(
        items.len() >= 25,
        "all virtual items listed: {}",
        items.len()
    );
    let on_screen = items.iter().filter(|e| e.interactable).count();
    let off_screen = items
        .iter()
        .filter(|e| {
            !e.interactable && e.visibility == browser_agent_core::VisibilityClass::Offscreen
        })
        .count();
    assert!(on_screen >= 3, "on-screen items interactable: {on_screen}");
    assert!(off_screen >= 20, "off-screen items parked: {off_screen}");
    session.close().await.expect("close");
}

// ---------------------------------------------------------------------------
// diff / staleness / determinism / rendering
// ---------------------------------------------------------------------------

/// Gate: stale reference detection 100%.
#[tokio::test]
async fn m2_stale_reference_detection() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/native-form.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let before = session.observe().await.expect("observe");
    let gen_before = before.state_generation;
    let resolved = session
        .resolve(&tab, "@email")
        .await
        .expect("resolve @email");
    assert_eq!(resolved.generation, gen_before);
    // Navigation bumps the generation: old refs are stale by definition.
    session
        .navigate(&format!("{base}/duplicate-buttons.html"))
        .await
        .expect("nav");
    let after = session.observe().await.expect("observe");
    assert!(after.state_generation > gen_before);
    assert!(
        resolved.generation < after.state_generation,
        "old ref must be stale"
    );
    // Unknown aliases never resolve.
    assert!(session.resolve(&tab, "@nope_missing").await.is_none());
    session.close().await.expect("close");
}

/// Gate: SPA pushState navigation shows up in the delta.
#[tokio::test]
async fn m2_spa_navigation_delta() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/spa-navigation.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    session.observe().await.expect("observe");
    session
        .execute(&tab, "document.getElementById('go-a').click(); 'clicked'")
        .await
        .expect("click");
    // Allow the pushState + heading swap to commit.
    tokio::time::sleep(Duration::from_millis(500)).await;
    let after = session.observe().await.expect("observe");
    assert!(after.url.ends_with("#/a"), "url: {}", after.url);
    let delta = session.observe_delta(&tab).await.expect("delta");
    assert!(delta.navigation_changed, "delta: {delta:?}");
    session.close().await.expect("close");
}

/// Gate: observation determinism — identical page → identical output.
#[tokio::test]
async fn m2_observation_deterministic() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/native-form.html"))
        .await
        .expect("nav");
    let a = session.observe().await.expect("observe");
    let b = session.observe().await.expect("observe");
    assert_eq!(a.page_fingerprint, b.page_fingerprint);
    let refs_a: Vec<_> = a.elements.iter().map(|e| &e.reference).collect();
    let refs_b: Vec<_> = b.elements.iter().map(|e| &e.reference).collect();
    assert_eq!(refs_a, refs_b);
    for (x, y) in a.elements.iter().zip(b.elements.iter()) {
        assert_eq!(
            x.fingerprint, y.fingerprint,
            "fingerprint drift for {}",
            x.reference
        );
        assert_eq!(x.id, y.id, "id drift for {}", x.reference);
    }
    session.close().await.expect("close");
}

/// Gate: model-facing rendering shows @ref blocks, pruned deterministically.
#[tokio::test]
async fn m2_agent_observation_render() {
    let _guard = M2_LOCK.lock().await;
    let Some(session) = launch().await else {
        return;
    };
    let base = fixture_server().await;
    session
        .navigate(&format!("{base}/native-form.html"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let text = session
        .render_observation(&tab, &HashSet::new())
        .await
        .expect("render");
    assert!(text.contains("@email"), "render:\n{text}");
    assert!(text.contains("textbox"), "render:\n{text}");
    let obs = session
        .agent_observation(&tab, &HashSet::new())
        .await
        .expect("agent obs");
    assert!(obs.elements.len() <= 300, "prune cap");
    assert!(!obs.truncated, "fixture must not truncate");
    assert_eq!(obs.state_generation, session.generation());
    session.close().await.expect("close");
}
