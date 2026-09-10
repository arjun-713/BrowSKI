//! Chromium process ownership: discovery, launch flags, endpoint readiness,
//! teardown.
//!
//! The process is killed and its profile directory removed on drop, so an
//! abandoned session can never leak a browser. Explicit [`LaunchedChrome`]
//! handling (via `close`-style `take()`) is preferred; `Drop` is the backstop.

use crate::error::CdpError;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Locate a Chromium/Chrome binary.
pub fn find_chrome_binary() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("CHROME_PATH") {
        let pb = PathBuf::from(&p);
        if pb.exists() {
            return Some(pb);
        }
    }
    for candidate in [
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ] {
        if candidate.contains('/') {
            let pb = PathBuf::from(candidate);
            if pb.exists() {
                return Some(pb);
            }
        } else if let Ok(path) = which_candidate(candidate) {
            return Some(path);
        }
    }
    None
}

fn which_candidate(name: &str) -> Result<PathBuf, ()> {
    let path = std::env::var_os("PATH").ok_or(())?;
    for dir in std::env::split_paths(&path) {
        let full = dir.join(name);
        if full.exists() {
            return Ok(full);
        }
    }
    Err(())
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(19_000 + (std::process::id() % 10_000) as u16)
}

/// A launched Chromium process with a remote-debugging endpoint.
pub struct LaunchedChrome {
    child: Child,
    /// Temporary user-data dir (removed on drop).
    pub profile_dir: PathBuf,
    pub port: u16,
}

impl LaunchedChrome {
    /// Launch headless Chromium. `headless=true` uses `--headless=new`.
    pub async fn launch(headless: bool) -> Result<Self, CdpError> {
        let binary = find_chrome_binary().ok_or(CdpError::ChromeNotFound)?;
        let port = free_port();
        let profile_dir =
            std::env::temp_dir().join(format!("browser-agent-{}-{port}", std::process::id()));
        std::fs::create_dir_all(&profile_dir).map_err(|e| CdpError::Spawn(e.to_string()))?;

        let mut args: Vec<String> = vec![
            format!("--remote-debugging-port={port}"),
            "--no-sandbox".into(),
            "--disable-gpu".into(),
            "--disable-dev-shm-usage".into(),
            "--no-first-run".into(),
            "--no-default-browser-check".into(),
            format!("--user-data-dir={}", profile_dir.display()),
            "about:blank".into(),
        ];
        if headless {
            args.push("--headless=new".into());
        }
        // Extra stability flags for CI/containers.
        args.push("--disable-extensions".into());
        args.push("--mute-audio".into());

        let mut cmd = Command::new(&binary);
        cmd.args(&args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let child = cmd.spawn().map_err(|e| CdpError::Spawn(e.to_string()))?;
        let this = Self {
            child,
            profile_dir,
            port,
        };
        this.wait_for_endpoint(Duration::from_secs(20)).await?;
        Ok(this)
    }

    pub fn debugger_base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    /// OS pid of the browser process (telemetry, leak assertions, tests).
    pub fn pid(&self) -> Option<u32> {
        // `Child::id` panics post-`wait` on some platforms; guard via try.
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.child.id())).ok()
    }

    async fn wait_for_endpoint(&self, timeout: Duration) -> Result<(), CdpError> {
        let client = reqwest::Client::new();
        let url = format!("{}/json/version", self.debugger_base_url());
        let start = Instant::now();
        while start.elapsed() < timeout {
            if let Ok(resp) = client.get(&url).send().await {
                if resp.status().is_success() {
                    return Ok(());
                }
            }
            tokio::time::sleep(Duration::from_millis(150)).await;
        }
        Err(CdpError::EndpointTimeout { port: self.port })
    }
}

impl Drop for LaunchedChrome {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.profile_dir);
    }
}
