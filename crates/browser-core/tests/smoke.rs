//! Launch Chromium, navigate to example.com, read back title. Run with:
//!
//! ```sh
//! cargo test -p browser-agent-core --test smoke
//! ```
//!
//! Requires a Chrome/Chromium binary and network access to example.com.
//! Without a binary the test skips loudly instead of failing (local runs).

use browser_agent_core::BrowserSession;

#[tokio::test]
async fn smoke_navigate_and_observe() {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return;
    }
    let session = BrowserSession::launch()
        .await
        .expect("failed to launch chromium; is Chrome installed?");
    session
        .navigate("https://example.com")
        .await
        .expect("navigation to example.com failed");
    let snapshot = session.observe().await.expect("observe failed");
    assert!(
        snapshot.url.starts_with("https://example.com"),
        "unexpected url: {}",
        snapshot.url
    );
    let title = snapshot.title.unwrap_or_default();
    assert!(
        title.to_lowercase().contains("example"),
        "unexpected title: {title}"
    );
    session.close().await.expect("close failed");
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
}

#[tokio::test]
async fn smoke_capture_viewport_png_is_bounded() {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return;
    }
    let session = BrowserSession::launch()
        .await
        .expect("failed to launch chromium; is Chrome installed?");
    session
        .navigate("data:text/html,<title>Screenshot</title><main>Visible</main>")
        .await
        .expect("navigation to local data URL failed");
    let tab = session
        .active_tab()
        .await
        .expect("active tab missing after navigation");

    let screenshot = session
        .capture_viewport_screenshot(&tab.id)
        .await
        .expect("viewport capture failed");

    assert!(screenshot.starts_with("iVBOR"), "expected a base64 PNG");
    assert!(
        screenshot.len() <= 5_600_000,
        "encoded image exceeded bound"
    );
    session.close().await.expect("close failed");
}
