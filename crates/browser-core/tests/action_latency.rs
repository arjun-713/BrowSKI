//! Opt-in local browser latency study for deterministic observation and actions.
//!
//! Run with:
//! `cargo test -p browser-agent-core --test action_latency -- --ignored --nocapture`

use browser_agent_core::BrowserSession;
use browser_agent_element_registry::ElementRef;
use browser_agent_executor::{ActOptions, BrowserAction};
use browser_agent_verification::ExpectedEffect;
use std::time::Instant;

const WARMUP_SAMPLES: usize = 5;
const MEASURED_SAMPLES: usize = 40;

fn percentile(samples: &[u64], percentile: usize) -> u64 {
    let mut sorted = samples.to_vec();
    sorted.sort_unstable();
    let rank = percentile.saturating_mul(sorted.len()).div_ceil(100);
    sorted[rank.saturating_sub(1).min(sorted.len() - 1)]
}

fn summary(samples: &[u64]) -> serde_json::Value {
    serde_json::json!({
        "n": samples.len(),
        "p50_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
        "p99_ms": percentile(samples, 99),
    })
}

#[tokio::test]
#[ignore = "manual local Chromium latency study"]
async fn report_observation_and_action_phase_latency() {
    let chrome =
        browser_agent_cdp::find_chrome_binary().expect("latency study requires Chrome or Chromium");
    assert!(chrome.is_file(), "browser binary is not a file: {chrome:?}");

    let session = BrowserSession::launch()
        .await
        .expect("launch browser for local latency study");
    let page = "data:text/html,<main><label><input id=ready type=checkbox>Ready</label></main>";
    session
        .navigate(page)
        .await
        .expect("navigate to local data page");
    let tab = session.active_tab().await.expect("active tab").id;

    let mut observation_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut total_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut pre_observation_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut target_resolution_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut action_execution_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut recovery_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut settle_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut post_observation_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut delta_samples = Vec::with_capacity(MEASURED_SAMPLES);
    let mut verification_samples = Vec::with_capacity(MEASURED_SAMPLES);

    for index in 0..WARMUP_SAMPLES + MEASURED_SAMPLES {
        let observation_start = Instant::now();
        let snapshot = session
            .observe_tab(&tab)
            .await
            .expect("observe benchmark page");
        let observation_ms = observation_start.elapsed().as_millis() as u64;
        let target = snapshot
            .by_ref("@ready")
            .expect("resolve Ready checkbox from semantic observation");
        let target = ElementRef::new(target.id, "@ready", target.generation);
        let outcome = session
            .act(
                &tab,
                BrowserAction::Check {
                    target,
                    checked: index % 2 == 0,
                    expected_effect: ExpectedEffect::Unspecified,
                },
                ActOptions::default(),
            )
            .await;
        assert!(outcome.succeeded(), "benchmark action failed: {outcome:?}");

        if index < WARMUP_SAMPLES {
            continue;
        }

        observation_samples.push(observation_ms);
        total_samples.push(outcome.elapsed_ms);
        pre_observation_samples.push(outcome.timings.pre_observation_ms);
        target_resolution_samples.push(outcome.timings.target_resolution_ms);
        action_execution_samples.push(outcome.timings.action_execution_ms);
        recovery_samples.push(outcome.timings.mechanical_recovery_ms);
        settle_samples.push(outcome.timings.settle_ms);
        post_observation_samples.push(outcome.timings.post_observation_ms);
        delta_samples.push(outcome.timings.delta_ms);
        verification_samples.push(outcome.timings.verification_ms);
    }

    let report = serde_json::json!({
        "study": "local_deterministic_browser_action_latency",
        "browser_binary": chrome,
        "warmup_samples": WARMUP_SAMPLES,
        "measured_samples": MEASURED_SAMPLES,
        "duration_ms": {
            "external_observation": summary(&observation_samples),
            "action_total": summary(&total_samples),
            "pre_observation": summary(&pre_observation_samples),
            "target_resolution": summary(&target_resolution_samples),
            "action_execution": summary(&action_execution_samples),
            "mechanical_recovery": summary(&recovery_samples),
            "settle": summary(&settle_samples),
            "post_observation": summary(&post_observation_samples),
            "delta": summary(&delta_samples),
            "verification": summary(&verification_samples),
        },
        "note": "local data URL and deterministic checkbox; no model or network calls",
    });
    println!("[latency-study] {report}");

    session.close().await.expect("close benchmark browser");
}
