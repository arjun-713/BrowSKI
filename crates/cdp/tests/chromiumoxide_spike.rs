//! chromiumoxide comparison spike (Milestone 1, ADR-002).
//!
//! Run with:
//!
//! ```sh
//! cargo test -p browser-agent-cdp --features transport-chromiumoxide \
//!     --test chromiumoxide_spike -- --nocapture
//! ```
//!
//! Runs the same workload class as `browser-core`'s stress suite through
//! chromiumoxide's native API (it owns its transport, so a shared-trait
//! comparison would defeat the purpose) and prints `[oxide-metrics]` lines
//! in the same shape. Static comparison (dependency weight, build time,
//! maintenance) goes into the ADR-002 M1 update. This spike is NOT part of
//! the runtime and must never gain dependents.

#![cfg(feature = "transport-chromiumoxide")]

use chromiumoxide::{Browser, BrowserConfig};
use futures_util::StreamExt;
use std::time::{Duration, Instant};

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

fn report(name: &str, samples: Vec<Duration>) {
    let (n, p50, p95, p99) = percentiles(samples);
    eprintln!("[oxide-metrics] {name} count={n} p50={p50:.1}ms p95={p95:.1}ms p99={p99:.1}ms");
}

/// Local fixture server (same shape as the stress suite's).
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
                let title = if path.starts_with("/other") {
                    "Fixture Other"
                } else {
                    "Fixture Hello"
                };
                let body = format!(
                    "<!doctype html><html><head><title>{title}</title></head>\
                     <body><h1>hi</h1></body></html>"
                );
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n\
                     Connection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = stream.write_all(response.as_bytes()).await;
            });
        }
    });
    base
}

#[tokio::test]
async fn oxide_workload_comparison() {
    if browser_agent_cdp::find_chrome_binary().is_none() {
        eprintln!("SKIP: no Chrome/Chromium binary found");
        return;
    }
    let base = fixture_server().await;
    let hello = format!("{base}/hello");
    let other = format!("{base}/other");

    let start = Instant::now();
    let (mut browser, mut handler) = Browser::launch(
        BrowserConfig::builder()
            .no_sandbox()
            .build()
            .expect("oxide config"),
    )
    .await
    .expect("oxide launch");
    eprintln!(
        "[oxide-metrics] launch_ms={:.0}",
        start.elapsed().as_secs_f64() * 1000.0
    );
    let pump = tokio::spawn(async move { while handler.next().await.is_some() {} });

    // 20 sequential navigations + title reads.
    let page = browser
        .new_page("about:blank")
        .await
        .expect("oxide new page");
    let mut nav_times = Vec::with_capacity(20);
    for i in 0..20 {
        let url = if i % 2 == 0 { &hello } else { &other };
        let t = Instant::now();
        page.goto(url).await.expect("oxide goto");
        let title = page.get_title().await.expect("oxide title");
        nav_times.push(t.elapsed());
        assert!(
            title.as_deref().is_some_and(|t| t.starts_with("Fixture")),
            "title: {title:?}"
        );
    }
    report("sequential_navigation", nav_times);

    // 10 tab create/navigate/close cycles.
    let mut cycle_times = Vec::with_capacity(10);
    for _ in 0..10 {
        let t = Instant::now();
        let p = browser.new_page(&hello).await.expect("oxide new page");
        p.get_title().await.expect("oxide title");
        p.close().await.expect("oxide close page");
        cycle_times.push(t.elapsed());
    }
    report("cross_tab_cycle", cycle_times);

    // 20 concurrent evaluates.
    let t_all = Instant::now();
    let mut handles = Vec::new();
    for i in 0..20u32 {
        let page = page.clone();
        handles.push(tokio::spawn(async move {
            let v: u32 = page
                .evaluate(format!("{i} * 2"))
                .await
                .expect("eval")
                .into_value()
                .expect("u32");
            assert_eq!(v, i * 2);
        }));
    }
    for h in handles {
        h.await.expect("join");
    }
    eprintln!(
        "[oxide-metrics] concurrent_20_total_ms={:.1}",
        t_all.elapsed().as_secs_f64() * 1000.0
    );

    page.close().await.expect("oxide close");
    browser.close().await.expect("oxide browser close");
    pump.await.expect("handler pump");
}
