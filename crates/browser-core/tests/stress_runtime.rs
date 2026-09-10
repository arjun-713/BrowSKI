//! Milestone-1 stress suite: the runtime must be boringly reliable.
//!
//! Gates (see `docs/development/roadmap.md` M1):
//!
//! | Test                           | Gate                              |
//! | sequential navigation          | 100/100                           |
//! | cross-tab create/navigate/close| 100 cycles                        |
//! | rapid tab creation             | 25+ tabs, all tracked, all closed |
//! | repeated frame attach/detach   | zero state corruption             |
//! | browser shutdown               | zero orphaned Chromium processes  |
//! | failed navigation              | runtime remains usable            |
//! | tab closed externally          | detected correctly                |
//! | browser killed externally      | deterministic disconnect event    |
//! | CDP command timeout            | no deadlocked pending request     |
//! | concurrent CDP commands        | correlation remains correct       |
//!
//! All tests serialize on [`STRESS_LOCK`] (parallel leak/process assertions
//! would otherwise interfere) and use a local fixture server (no external
//! network). Tests print `[metrics]` timing lines; collect them for the M1
//! report. Without a Chrome binary the tests skip loudly (pass) instead of
//! failing.

use browser_agent_core::{BrowserEvent, BrowserSession};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::broadcast;

// ---------------------------------------------------------------------------
// support
// ---------------------------------------------------------------------------

static STRESS_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn require_chrome() -> bool {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return false;
    }
    true
}

/// p50/p95/p99 in milliseconds.
fn percentiles(mut samples: Vec<Duration>) -> (usize, f64, f64, f64) {
    samples.sort_unstable();
    let n = samples.len();
    let pct = |p: f64| {
        if n == 0 {
            return 0.0;
        }
        let idx = ((p * n as f64).ceil() as usize)
            .saturating_sub(1)
            .min(n - 1);
        samples[idx].as_secs_f64() * 1000.0
    };
    (n, pct(0.5), pct(0.95), pct(0.99))
}

fn report_metrics(name: &str, samples: Vec<Duration>) {
    let (n, p50, p95, p99) = percentiles(samples);
    eprintln!("[metrics] {name} count={n} p50={p50:.1}ms p95={p95:.1}ms p99={p99:.1}ms");
}

/// Minimal local HTTP fixture server. Routes: `/hello`, `/other`.
async fn fixture_server() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                break;
            };
            tokio::spawn(async move {
                use tokio::io::{AsyncReadExt, AsyncWriteExt};
                let mut buf = Vec::new();
                let mut tmp = [0u8; 4096];
                // Read until end of headers (or 32KB cap).
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") && buf.len() < 32 * 1024 {
                    match stream.read(&mut tmp).await {
                        Ok(0) | Err(_) => break,
                        Ok(n) => buf.extend_from_slice(&tmp[..n]),
                    }
                }
                let request = String::from_utf8_lossy(&buf);
                let path = request
                    .lines()
                    .next()
                    .and_then(|l| l.split_whitespace().nth(1))
                    .unwrap_or("/");
                let (title, heading) = match path.split('?').next().unwrap_or(path) {
                    "/other" => ("Fixture Other", "other page"),
                    _ => ("Fixture Hello", "hello page"),
                };
                let body = format!(
                    "<!doctype html><html><head><title>{title}</title></head>\
                     <body><h1>{heading}</h1><div id=\"probe\">ready</div></body></html>"
                );
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\
                     Content-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = stream.write_all(response.as_bytes()).await;
            });
        }
    });
    base
}

async fn wait_for_browser_event(
    rx: &mut broadcast::Receiver<BrowserEvent>,
    timeout: Duration,
    mut pred: impl FnMut(&BrowserEvent) -> bool,
) -> Option<BrowserEvent> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        match tokio::time::timeout(remaining, rx.recv()).await {
            Ok(Ok(ev)) => {
                if pred(&ev) {
                    return Some(ev);
                }
            }
            Ok(Err(broadcast::error::RecvError::Lagged(_))) => continue,
            _ => break,
        }
    }
    None
}

/// Count OS processes whose command line contains `pattern`.
fn count_processes(pattern: &str) -> usize {
    std::process::Command::new("pgrep")
        .args(["-c", "-f", pattern])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0)
}

fn chrome_pattern(session: &BrowserSession) -> String {
    // Unique per session: the remote-debugging port is in every chrome cmdline.
    let base = session.debugger_base_url();
    let port = base.rsplit(':').next().unwrap_or("").trim_end_matches('/');
    format!("remote-debugging-port={port}")
}

fn proc_fds() -> usize {
    std::fs::read_dir("/proc/self/fd")
        .map(|d| d.count())
        .unwrap_or(0)
}

fn proc_rss_mb() -> f64 {
    std::fs::read_to_string("/proc/self/statm")
        .ok()
        .and_then(|s| {
            s.split_whitespace()
                .nth(1)
                .and_then(|v| v.parse::<f64>().ok())
        })
        .map(|pages| pages * 4096.0 / 1_048_576.0)
        .unwrap_or(0.0)
}

// ---------------------------------------------------------------------------
// gates
// ---------------------------------------------------------------------------

/// Gate: 100/100 sequential navigations.
#[tokio::test]
async fn stress_sequential_navigation_100() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    let hello = format!("{base}/hello");
    let other = format!("{base}/other");
    let mut times = Vec::with_capacity(100);
    for i in 0..100 {
        let url = if i % 2 == 0 { &hello } else { &other };
        let start = Instant::now();
        session
            .navigate(url)
            .await
            .expect("sequential navigation must succeed");
        times.push(start.elapsed());
    }
    let snap = session.observe().await.expect("observe");
    assert!(
        snap.url.starts_with(&other),
        "unexpected final url {}",
        snap.url
    );
    assert_eq!(snap.state_generation, 100);
    report_metrics("sequential_navigation", times);
    session.close().await.expect("close");
}

/// Gate: 100 cross-tab create/navigate/close cycles.
#[tokio::test]
async fn stress_cross_tab_cycles_100() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let hello = format!("{base}/hello");
    let session = BrowserSession::launch().await.expect("launch");
    let baseline = session.tabs().await.len();
    let mut rx = session.events();
    let mut created = 0usize;
    let mut destroyed = 0usize;
    let mut times = Vec::with_capacity(100);
    for _ in 0..100 {
        let start = Instant::now();
        let tab = session.new_tab(Some(&hello)).await.expect("new tab");
        session.observe_tab(&tab).await.expect("observe tab");
        session.close_tab(&tab).await.expect("close tab");
        times.push(start.elapsed());
        assert_eq!(session.tabs().await.len(), baseline, "tab leaked");
    }
    // Drain bus: every cycle must have produced create+destroy.
    while let Ok(ev) = rx.try_recv() {
        match ev {
            BrowserEvent::TargetCreated { .. } => created += 1,
            BrowserEvent::TargetDestroyed { .. } => destroyed += 1,
            _ => {}
        }
    }
    assert!(created >= 100, "missing TargetCreated events: {created}");
    assert!(
        destroyed >= 100,
        "missing TargetDestroyed events: {destroyed}"
    );
    report_metrics("cross_tab_cycle", times);
    session.close().await.expect("close");
}

/// Gate: 25+ rapid tabs, all tracked, all closed.
#[tokio::test]
async fn stress_rapid_tab_creation_25() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    let baseline = session.tabs().await.len();
    let mut tabs = Vec::new();
    for _ in 0..25 {
        tabs.push(
            session
                .new_tab(Some(&format!("{base}/hello")))
                .await
                .expect("new tab"),
        );
    }
    let listed = session.tabs().await;
    assert_eq!(listed.len(), baseline + 25, "tabs missing from registry");
    assert!(listed.iter().all(|t| t.has_session), "tab without session");
    for tab in &tabs {
        session.close_tab(tab).await.expect("close tab");
    }
    assert_eq!(session.tabs().await.len(), baseline);
    session.close().await.expect("close");
}

/// Gate: 50 iframe attach/detach cycles leave zero state corruption.
#[tokio::test]
async fn stress_frame_attach_detach() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    session
        .navigate(&format!("{base}/hello"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let mut rx = session.events();

    let churn = r#"
        (async () => {
            for (let i = 0; i < 50; i++) {
                await new Promise((resolve, reject) => {
                    const f = document.createElement('iframe');
                    f.src = '/hello';
                    const timer = setTimeout(() => reject(new Error('iframe timeout')), 10000);
                    f.onload = () => { clearTimeout(timer); f.remove(); resolve(); };
                    f.onerror = () => { clearTimeout(timer); reject(new Error('iframe error')); };
                    document.body.appendChild(f);
                });
            }
            return 'churned-50';
        })()
    "#;
    // Relative iframe src resolves against the page URL (same fixture server).
    let result = session.execute(&tab, churn).await.expect("churn executes");
    assert_eq!(result.as_str(), Some("churned-50"));

    // Registry must settle back to exactly the main frame.
    let deadline = Instant::now() + Duration::from_secs(15);
    let settled = loop {
        let tabs = session.tabs().await;
        let current = tabs.iter().find(|t| t.id == tab).expect("tab present");
        if current.frames == 1 {
            break true;
        }
        if Instant::now() > deadline {
            break false;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    };
    assert!(settled, "frame registry did not settle to main frame only");

    let mut attached = 0usize;
    let mut detached = 0usize;
    while let Ok(ev) = rx.try_recv() {
        match ev {
            BrowserEvent::FrameAttached { .. } => attached += 1,
            BrowserEvent::FrameDetached { .. } => detached += 1,
            _ => {}
        }
    }
    assert!(attached >= 50, "missing FrameAttached events: {attached}");
    assert!(detached >= 50, "missing FrameDetached events: {detached}");
    eprintln!("[metrics] frame_churn attached={attached} detached={detached}");
    session.close().await.expect("close");
}

/// Gate: shutdown leaves zero orphaned Chromium processes.
#[tokio::test]
async fn stress_shutdown_leaves_no_orphans() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let session = BrowserSession::launch().await.expect("launch");
    let pattern = chrome_pattern(&session);
    assert!(
        count_processes(&pattern) >= 1,
        "browser process not found while alive"
    );
    session.close().await.expect("close");
    let deadline = Instant::now() + Duration::from_secs(10);
    while count_processes(&pattern) > 0 && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    assert_eq!(
        count_processes(&pattern),
        0,
        "orphaned Chromium processes remain"
    );
}

/// Gate: after a failed navigation the runtime remains usable.
#[tokio::test]
async fn stress_failed_navigation_stays_usable() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    // Guaranteed-unresolvable host (RFC 2606 `.invalid`).
    let failed = session.navigate("http://nonexistent.invalid/").await;
    eprintln!("failed-nav outcome (either is acceptable): {failed:?}");
    // The runtime must still work afterwards.
    session
        .navigate(&format!("{base}/hello"))
        .await
        .expect("usable after failure");
    let snap = session.observe().await.expect("observe");
    assert_eq!(snap.title.as_deref(), Some("Fixture Hello"));
    assert!(session.is_live());
    session.close().await.expect("close");
}

/// Gate: a tab closed *externally* (HTTP API, bypassing the session) is
/// detected via TargetDestroyed and removed from the registry.
#[tokio::test]
async fn stress_external_tab_close_detected() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    let tab = session
        .new_tab(Some(&format!("{base}/hello")))
        .await
        .expect("new tab");
    let target = session
        .tabs()
        .await
        .iter()
        .find(|t| t.id == tab)
        .expect("tab listed")
        .target
        .clone();
    let mut rx = session.events();
    browser_agent_cdp::close_target_http(session.debugger_base_url(), &target)
        .await
        .expect("external close");
    let ev = wait_for_browser_event(
        &mut rx,
        Duration::from_secs(10),
        |e| matches!(e, BrowserEvent::TargetDestroyed { tab: t } if *t == tab),
    )
    .await;
    assert!(ev.is_some(), "TargetDestroyed not detected");
    assert!(
        !session.tabs().await.iter().any(|t| t.id == tab),
        "tab not removed"
    );
    session.close().await.expect("close");
}

/// Gate: killing the browser externally produces a deterministic
/// disconnect event; further commands fail terminally, not by hanging.
#[tokio::test]
async fn stress_browser_killed_externally() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let session = BrowserSession::launch().await.expect("launch");
    let pid = session.browser_pid().expect("owned process has a pid");
    let mut rx = session.events();
    let status = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .status();
    assert!(status.is_ok_and(|s| s.success()), "kill -9 failed");
    let ev = wait_for_browser_event(&mut rx, Duration::from_secs(15), |e| {
        matches!(e, BrowserEvent::ConnectionLost)
    })
    .await;
    assert!(ev.is_some(), "no deterministic disconnect event");
    assert!(!session.is_live(), "session still claims liveness");
    assert_eq!(
        session.pending_commands().await,
        0,
        "pending requests stranded"
    );
    let err = session.observe().await.unwrap_err();
    assert!(
        err.is_terminal(),
        "post-kill error must be terminal, got {err:?}"
    );
    // Drop path must not hang or resurrect anything.
    drop(session);
}

/// Gate: 50 concurrent commands correlate responses correctly.
#[tokio::test]
async fn stress_concurrent_commands_correlate() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = Arc::new(BrowserSession::launch().await.expect("launch"));
    session
        .navigate(&format!("{base}/hello"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let start = Instant::now();
    let mut handles = Vec::new();
    for i in 0..50u32 {
        let (session, tab) = (Arc::clone(&session), tab.clone());
        let expr = format!("{i} * 2");
        handles.push(tokio::spawn(async move {
            session.execute(&tab, &expr).await.map(|v| (i, v))
        }));
    }
    let mut times = Vec::with_capacity(50);
    for h in handles {
        let (i, v) = h.await.expect("task panicked").expect("command failed");
        assert_eq!(
            v.as_u64(),
            Some((i * 2) as u64),
            "response mismatch for {i}"
        );
        times.push(start.elapsed());
    }
    assert_eq!(session.pending_commands().await, 0);
    report_metrics("concurrent_command", times);
    Arc::try_unwrap(session)
        .map_err(|_| "session still shared")
        .unwrap()
        .close()
        .await
        .expect("close");
}

/// Gate: reconnecting to the same browser preserves tabs and usability.
#[tokio::test]
async fn stress_reconnect_preserves_session() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = BrowserSession::launch().await.expect("launch");
    let hello = format!("{base}/hello");
    session.navigate(&hello).await.expect("nav");
    let before = session.tabs().await;
    assert!(!before.is_empty());
    session.reconnect().await.expect("reconnect");
    let after = session.tabs().await;
    assert_eq!(after.len(), before.len(), "tabs lost across reconnect");
    assert!(
        after.iter().all(|t| t.has_session),
        "tab without session after reconnect"
    );
    session
        .navigate(&format!("{base}/other"))
        .await
        .expect("nav after reconnect");
    let snap = session.observe().await.expect("observe");
    assert_eq!(snap.title.as_deref(), Some("Fixture Other"));
    session.close().await.expect("close");
}

/// Gate: dialog opening is detected as an event (not a hang).
#[tokio::test]
async fn stress_dialog_opened_detected() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let base = fixture_server().await;
    let session = Arc::new(BrowserSession::launch().await.expect("launch"));
    session
        .navigate(&format!("{base}/hello"))
        .await
        .expect("nav");
    let tab = session.active_tab().await.expect("active").id;
    let mut rx = session.events();
    // `alert` blocks the evaluate promise until dismissed: run it in the
    // background, dismiss on the event, then join.
    let alert = tokio::spawn({
        let (session, tab) = (Arc::clone(&session), tab.clone());
        async move { session.execute(&tab, "alert('hi')").await }
    });
    let ev = wait_for_browser_event(
        &mut rx,
        Duration::from_secs(10),
        |e| matches!(e, BrowserEvent::DialogOpened { tab: t, .. } if *t == tab),
    )
    .await;
    assert!(ev.is_some(), "DialogOpened not detected");
    if let BrowserEvent::DialogOpened {
        dialog_type,
        message,
        ..
    } = ev.expect("event present")
    {
        assert_eq!(dialog_type, "alert");
        assert_eq!(message, "hi");
    }
    session
        .handle_dialog(&tab, true)
        .await
        .expect("dismiss dialog");
    let result = tokio::time::timeout(Duration::from_secs(15), alert)
        .await
        .expect("alert task join timeout")
        .expect("alert task panicked")
        .expect("evaluate failed");
    assert!(
        result.is_null(),
        "alert evaluates to undefined, got {result}"
    );
    Arc::try_unwrap(session)
        .map_err(|_| "session still shared")
        .unwrap()
        .close()
        .await
        .expect("close");
}

/// Resource report: fds + RSS across launch/close cycles (soft bounds,
///
/// the point is the printed numbers for the M1 report).
#[tokio::test]
async fn stress_resource_growth_report() {
    let _guard = STRESS_LOCK.lock().await;
    if !require_chrome() {
        return;
    }
    let fds_before = proc_fds();
    let rss_before = proc_rss_mb();
    for _ in 0..3 {
        let session = BrowserSession::launch().await.expect("launch");
        session.navigate("about:blank").await.expect("nav");
        session.close().await.expect("close");
    }
    // Let reaping settle.
    tokio::time::sleep(Duration::from_secs(2)).await;
    let fds_after = proc_fds();
    let rss_after = proc_rss_mb();
    eprintln!(
        "[metrics] resources fds_before={fds_before} fds_after={fds_after} \
         rss_before={rss_before:.1}MB rss_after={rss_after:.1}MB"
    );
    assert!(
        fds_after <= fds_before + 8,
        "fd leak suspected: {fds_before} -> {fds_after}"
    );
    assert!(
        rss_after <= rss_before + 150.0,
        "rss growth suspected: {rss_before:.1} -> {rss_after:.1}MB"
    );
}
