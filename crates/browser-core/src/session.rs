//! [`BrowserSession`]: one owned Chromium (or an attached external one),
//! one persistent transport, a tab/frame registry, and a typed event bus.
//!
//! All browser I/O flows through [`CdpTransport`](browser_agent_cdp::CdpTransport);
//! the session adds lifecycle (launch/attach/reconnect/close), the
//! [`TabRegistry`](crate::model::TabRegistry) view, and the
//! [`BrowserEvent`](crate::events::BrowserEvent) projection.

use crate::error::BrowserRuntimeError;
use crate::events::BrowserEvent;
use crate::model::{Tab, TabRegistry};
use browser_agent_cdp::{
    browser_ws_url, list_targets, CdpError, CdpEvent, CdpSessionId, CdpTransport, LaunchedChrome,
    OwnedTab, PersistentTransport, TabId, TargetId, DEFAULT_COMMAND_TIMEOUT,
};
use browser_agent_element_registry::ElementRegistry;
use browser_agent_observation::{AgentObservation, SemanticSnapshot, SnapshotDelta};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{broadcast, RwLock};

static SESSION_COUNTER: AtomicU64 = AtomicU64::new(1);

const EVENT_CHANNEL_CAPACITY: usize = 1024;
const ATTACH_WAIT: Duration = Duration::from_secs(15);
const REMOVAL_WAIT: Duration = Duration::from_secs(10);
const POLL_INTERVAL: Duration = Duration::from_millis(50);
const MAX_VIEWPORT_SCREENSHOT_BASE64_BYTES: usize = 5_600_000;
const MAX_ATTACHED_TABS: usize = 8;
const MAX_ATTACHED_TAB_URL_BYTES: usize = 2048;

/// Options for [`BrowserSession::launch_with_options`].
#[derive(Debug, Clone)]
pub struct LaunchOptions {
    pub headless: bool,
    pub navigation_timeout: Duration,
    pub command_timeout: Duration,
}

impl Default for LaunchOptions {
    fn default() -> Self {
        Self {
            headless: true,
            navigation_timeout: Duration::from_secs(30),
            command_timeout: DEFAULT_COMMAND_TIMEOUT,
        }
    }
}

/// Point-in-time tab snapshot for callers.
#[derive(Debug, Clone, serde::Serialize)]
pub struct TabInfo {
    pub id: TabId,
    pub target: TargetId,
    pub title: String,
    pub url: String,
    pub frames: usize,
    pub has_session: bool,
    pub crashed: bool,
}

impl From<&Tab> for TabInfo {
    fn from(tab: &Tab) -> Self {
        Self {
            id: tab.id.clone(),
            target: tab.target.clone(),
            title: tab.title.clone(),
            url: tab.url.clone(),
            frames: tab.frames.len(),
            has_session: tab.session.is_some(),
            crashed: tab.crashed,
        }
    }
}

/// A live browser session: owned Chromium (or attached external), one
/// persistent CDP transport, tab/frame registry, typed event bus.
///
/// All `&self` methods are safe to call concurrently; commanding and event
/// handling never touch a socket directly.
pub struct BrowserSession {
    session_id: String,
    mode: SessionMode,
    initial_attached_target: Option<TargetId>,
    chrome: Option<LaunchedChrome>,
    base_url: String,
    transport: RwLock<Arc<dyn CdpTransport>>,
    tabs: Arc<RwLock<TabRegistry>>,
    event_tx: broadcast::Sender<BrowserEvent>,
    generation: Arc<AtomicU64>,
    navigation_timeout: Duration,
    command_timeout: Duration,
    closed: Arc<AtomicBool>,
    pump: tokio::sync::Mutex<Option<tokio::task::JoinHandle<()>>>,
    registries: Arc<RwLock<HashMap<TargetId, ElementRegistry>>>,
    snapshots: Arc<RwLock<HashMap<TargetId, SemanticSnapshot>>>,
    deltas: Arc<RwLock<HashMap<TargetId, SnapshotDelta>>>,
    dialog_open_flag: Arc<AtomicBool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionMode {
    Managed,
    Attached,
}

impl BrowserSession {
    /// Launch headless Chromium with default options.
    pub async fn launch() -> Result<Self, BrowserRuntimeError> {
        Self::launch_with_options(LaunchOptions::default()).await
    }

    pub async fn launch_with_options(options: LaunchOptions) -> Result<Self, BrowserRuntimeError> {
        let chrome = LaunchedChrome::launch(options.headless)
            .await
            .map_err(|e| BrowserRuntimeError::LaunchFailure(e.to_string()))?;
        let base_url = chrome.debugger_base_url();
        Self::attach(base_url, Some(chrome), options).await
    }

    /// Attach to an already-running Chromium (no owned process; `close`
    /// disconnects but does not kill the browser).
    pub async fn connect_to(debugger_base_url: &str) -> Result<Self, BrowserRuntimeError> {
        Self::connect_to_with_options(debugger_base_url, LaunchOptions::default()).await
    }

    pub async fn connect_to_with_options(
        debugger_base_url: &str,
        options: LaunchOptions,
    ) -> Result<Self, BrowserRuntimeError> {
        Self::attach(debugger_base_url.to_string(), None, options).await
    }

    /// Create a session around an already attached browser tab transport.
    ///
    /// The caller owns browser attachment and supplies the single tab and CDP
    /// session authorized by that attachment. This skips managed-browser
    /// discovery and target auto-attach; observation and execution still use
    /// the same `BrowserSession` implementation.
    pub async fn from_attached_transport(
        transport: Arc<dyn CdpTransport>,
        target: TargetId,
        cdp_session: CdpSessionId,
        session_id: Option<String>,
        title: String,
        url: String,
        options: LaunchOptions,
    ) -> Result<Self, BrowserRuntimeError> {
        let id = SESSION_COUNTER.fetch_add(1, Ordering::SeqCst);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let mut tabs = TabRegistry::new();
        tabs.upsert_target(target.clone(), title.clone(), url.clone());
        tabs.bind_session(cdp_session.clone(), target.clone());
        tabs.set_active(target.clone());
        let session = Self {
            session_id: session_id.unwrap_or_else(|| id.to_string()),
            mode: SessionMode::Attached,
            initial_attached_target: Some(target.clone()),
            chrome: None,
            base_url: String::new(),
            transport: RwLock::new(transport.clone()),
            tabs: Arc::new(RwLock::new(tabs)),
            event_tx,
            generation: Arc::new(AtomicU64::new(0)),
            navigation_timeout: options.navigation_timeout,
            command_timeout: options.command_timeout,
            closed: Arc::new(AtomicBool::new(false)),
            pump: tokio::sync::Mutex::new(None),
            registries: Arc::new(RwLock::new(HashMap::new())),
            snapshots: Arc::new(RwLock::new(HashMap::new())),
            deltas: Arc::new(RwLock::new(HashMap::new())),
            dialog_open_flag: Arc::new(AtomicBool::new(false)),
        };
        session.spawn_pump().await;
        for method in ["Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"] {
            transport
                .command_in_session(&cdp_session, method, serde_json::json!({}))
                .await
                .map_err(|error| BrowserRuntimeError::from_cdp(error, None))?;
        }
        browser_agent_telemetry::TraceEvent::new(
            "browser.session.attach",
            format!("attached browser session {} ready", session.session_id),
        )
        .with_session(session.session_id.clone())
        .emit();
        Ok(session)
    }

    async fn attach(
        base_url: String,
        chrome: Option<LaunchedChrome>,
        options: LaunchOptions,
    ) -> Result<Self, BrowserRuntimeError> {
        let ws_url = browser_ws_url(&base_url)
            .await
            .map_err(|e| BrowserRuntimeError::LaunchFailure(e.to_string()))?;
        let transport: Arc<dyn CdpTransport> = Arc::new(
            PersistentTransport::connect(&ws_url, options.command_timeout)
                .await
                .map_err(|e| BrowserRuntimeError::LaunchFailure(e.to_string()))?,
        );
        let id = SESSION_COUNTER.fetch_add(1, Ordering::SeqCst);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let session = Self {
            session_id: id.to_string(),
            mode: SessionMode::Managed,
            initial_attached_target: None,
            chrome,
            base_url,
            transport: RwLock::new(Arc::clone(&transport)),
            tabs: Arc::new(RwLock::new(TabRegistry::new())),
            event_tx,
            generation: Arc::new(AtomicU64::new(0)),
            navigation_timeout: options.navigation_timeout,
            command_timeout: options.command_timeout,
            closed: Arc::new(AtomicBool::new(false)),
            pump: tokio::sync::Mutex::new(None),
            registries: Arc::new(RwLock::new(HashMap::new())),
            snapshots: Arc::new(RwLock::new(HashMap::new())),
            deltas: Arc::new(RwLock::new(HashMap::new())),
            dialog_open_flag: Arc::new(AtomicBool::new(false)),
        };
        session.spawn_pump().await;
        // Pump first: no event loss after this point. initialize() then
        // explicitly attaches existing targets (deterministic: the session
        // id comes back in the command response) and enables auto-attach
        // only for *future* targets.
        session.initialize(transport.as_ref()).await?;
        session.wait_for_first_tab().await?;
        browser_agent_telemetry::TraceEvent::new(
            "browser.session.launch",
            format!("browser session {} ready", session.session_id),
        )
        .with_session(session.session_id.clone())
        .emit();
        Ok(session)
    }

    /// Enable discovery, auto-attach future targets, then adopt existing
    /// page targets — first by waiting for their `attachedToTarget` events
    /// (the pump is already running, so nothing is missed), falling back to
    /// explicit `Target.attachToTarget` (synchronous session id) if an event
    /// does not arrive. Auto-attach-first avoids double sessions in the
    /// common case.
    async fn initialize(&self, transport: &dyn CdpTransport) -> Result<(), BrowserRuntimeError> {
        transport
            .command(
                "Target.setDiscoverTargets",
                serde_json::json!({"discover": true}),
            )
            .await
            .map_err(|e| BrowserRuntimeError::from_cdp(e, None))?;
        transport
            .command(
                "Target.setAutoAttach",
                serde_json::json!({
                    "autoAttach": true,
                    "waitForDebuggerOnStart": false,
                    "flatten": true,
                }),
            )
            .await
            .map_err(|e| BrowserRuntimeError::from_cdp(e, None))?;
        let targets = list_targets(&self.base_url)
            .await
            .map_err(|e| BrowserRuntimeError::LaunchFailure(e.to_string()))?;
        for t in targets.iter().filter(|t| t.target_type == "page") {
            let target = TargetId::from(t.id.clone());
            self.tabs
                .write()
                .await
                .upsert_target(target.clone(), t.title.clone(), t.url.clone());
            if self
                .wait_for_session(&target, Duration::from_secs(5))
                .await
                .is_err()
            {
                // No auto-attach event arrived; attach explicitly.
                match transport
                    .command(
                        "Target.attachToTarget",
                        serde_json::json!({"targetId": target.as_str(), "flatten": true}),
                    )
                    .await
                {
                    Ok(res) => {
                        let session =
                            res.get("sessionId")
                                .and_then(Value::as_str)
                                .ok_or_else(|| {
                                    BrowserRuntimeError::Cdp(CdpError::Unexpected(
                                        "attachToTarget missing sessionId".into(),
                                    ))
                                })?;
                        self.adopt_session(
                            CdpSessionId::from(session),
                            target,
                            t.title.clone(),
                            t.url.clone(),
                        )
                        .await?;
                    }
                    Err(CdpError::Protocol { message, .. }) if message.contains("already") => {
                        // Raced with auto-attach; the event binds it shortly.
                        self.wait_for_session(&target, Duration::from_secs(5))
                            .await?;
                    }
                    Err(e) => return Err(BrowserRuntimeError::from_cdp(e, Some(&target))),
                }
            }
        }
        Ok(())
    }

    /// Record a bound session: registry upsert + bind, domain enables,
    /// active-tab default, `TargetCreated` emission. Shared by explicit
    /// attach (startup/reconnect) and the pump's attachedToTarget handler.
    async fn adopt_session(
        &self,
        session: CdpSessionId,
        target: TargetId,
        title: String,
        url: String,
    ) -> Result<(), BrowserRuntimeError> {
        adopt_session_into(
            &self.tabs,
            &self.event_tx,
            &self.transport.read().await.clone(),
            session,
            target,
            title,
            url,
        )
        .await
    }

    async fn wait_for_session(
        &self,
        target: &TargetId,
        timeout: Duration,
    ) -> Result<(), BrowserRuntimeError> {
        let start = Instant::now();
        while start.elapsed() < timeout {
            if self
                .tabs
                .read()
                .await
                .get(target)
                .is_some_and(|t| t.session.is_some())
            {
                return Ok(());
            }
            tokio::time::sleep(POLL_INTERVAL).await;
        }
        Err(BrowserRuntimeError::TargetClosed(target.clone()))
    }

    async fn spawn_pump(&self) {
        let transport = self.transport.read().await.clone();
        let mut rx = transport.subscribe();
        let tabs = Arc::clone(&self.tabs);
        let event_tx = self.event_tx.clone();
        let session_id = self.session_id.clone();
        let closed = Arc::clone(&self.closed);
        let dialog_open = Arc::clone(&self.dialog_open_flag);
        let generation = Arc::clone(&self.generation);
        let handle = tokio::spawn(async move {
            let mut downloads: HashMap<String, (TabId, String)> = HashMap::new();
            let mut lagged_total = 0u64;
            let debug_pump = std::env::var("BROWSER_AGENT_PUMP_DEBUG").is_ok();
            loop {
                match rx.recv().await {
                    Ok(cdp_event) => {
                        if closed.load(Ordering::SeqCst) {
                            break;
                        }
                        if debug_pump {
                            eprintln!("[pump] {}", cdp_event.kind());
                        }
                        pump_one(
                            &tabs,
                            &event_tx,
                            &session_id,
                            &transport,
                            &closed,
                            &dialog_open,
                            &generation,
                            &mut downloads,
                            cdp_event,
                        )
                        .await;
                    }
                    // Slow consumer: skip missed events, NEVER exit. Exiting
                    // here silently wedges the registry (M2 lesson).
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        lagged_total += n;
                        tracing::warn!(
                            "browser event pump lagged by {n} events ({lagged_total} total)"
                        );
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        });
        *self.pump.lock().await = Some(handle);
    }

    async fn wait_for_first_tab(&self) -> Result<(), BrowserRuntimeError> {
        let start = Instant::now();
        while start.elapsed() < ATTACH_WAIT {
            {
                let tabs = self.tabs.read().await;
                if tabs.tabs().iter().any(|t| t.session.is_some()) {
                    return Ok(());
                }
            }
            tokio::time::sleep(POLL_INTERVAL).await;
        }
        Err(BrowserRuntimeError::LaunchFailure(
            "no page target attached within timeout".into(),
        ))
    }

    // -- introspection --------------------------------------------------

    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }

    /// False after `close`, drop-shutdown, or a lost connection.
    pub fn is_live(&self) -> bool {
        !self.closed.load(Ordering::SeqCst)
    }

    /// OS pid of the owned browser process, if any.
    pub fn browser_pid(&self) -> Option<u32> {
        self.chrome.as_ref().and_then(|c| c.pid())
    }

    /// Debugger HTTP base URL (tests use it for *external* operations).
    pub fn debugger_base_url(&self) -> &str {
        &self.base_url
    }

    /// Subscribe to session-level browser events.
    pub fn events(&self) -> broadcast::Receiver<BrowserEvent> {
        self.event_tx.subscribe()
    }

    /// Number of commands currently awaiting a response.
    pub async fn pending_commands(&self) -> usize {
        self.transport.read().await.pending_commands()
    }

    // -- observer collaborators (crate-internal) --------------------------

    pub(crate) async fn tab_session_pub(
        &self,
        tab: &TabId,
    ) -> Result<(TargetId, CdpSessionId), BrowserRuntimeError> {
        self.tab_session(tab).await
    }

    pub(crate) async fn transport_pub(&self) -> Arc<dyn CdpTransport> {
        self.transport.read().await.clone()
    }

    pub(crate) fn registries_map(&self) -> &Arc<RwLock<HashMap<TargetId, ElementRegistry>>> {
        &self.registries
    }

    pub(crate) fn snapshots_map(&self) -> &Arc<RwLock<HashMap<TargetId, SemanticSnapshot>>> {
        &self.snapshots
    }

    pub(crate) fn deltas_map(&self) -> &Arc<RwLock<HashMap<TargetId, SnapshotDelta>>> {
        &self.deltas
    }

    pub(crate) async fn evaluate_in(
        &self,
        session: &CdpSessionId,
        expression: &str,
    ) -> Result<Value, BrowserRuntimeError> {
        self.evaluate(session, expression).await
    }

    pub(crate) fn dialog_open(&self) -> bool {
        self.dialog_open_flag.load(Ordering::SeqCst)
    }

    pub(crate) async fn tab_ids_pub(&self) -> Vec<TabId> {
        self.tabs
            .read()
            .await
            .tabs()
            .iter()
            .map(|t| t.id.clone())
            .collect()
    }

    // -- tabs -----------------------------------------------------------

    pub async fn tabs(&self) -> Vec<TabInfo> {
        self.tabs
            .read()
            .await
            .tabs()
            .iter()
            .map(TabInfo::from)
            .collect()
    }

    pub async fn active_tab(&self) -> Option<TabInfo> {
        self.tabs.read().await.active().map(TabInfo::from)
    }

    pub async fn activate_tab(&self, tab: &TabId) -> Result<(), BrowserRuntimeError> {
        let target = TargetId::from(tab.as_str().to_string());
        if !self.tabs.read().await.contains(&target) {
            return Err(BrowserRuntimeError::TargetClosed(target));
        }
        if self.mode == SessionMode::Attached {
            let transport = self.transport.read().await.clone();
            transport
                .activate_owned_tab(&target)
                .await
                .map_err(|error| BrowserRuntimeError::from_cdp(error, Some(&target)))?;
        } else {
            self.cmd(
                None,
                "Target.activateTarget",
                serde_json::json!({"targetId": target.as_str()}),
            )
            .await?;
        }
        self.tabs.write().await.set_active(target);
        Ok(())
    }

    /// Create a tab (optionally already navigated) and wait for attach.
    pub async fn new_tab(&self, url: Option<&str>) -> Result<TabId, BrowserRuntimeError> {
        self.require_live()?;
        if self.mode == SessionMode::Attached {
            let Some(url) = url else {
                return Err(BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
                    "attached browser tabs require an explicit HTTP or HTTPS URL".to_string(),
                )));
            };
            validate_owned_tab_url(url)?;
            if self.tabs.read().await.len() >= MAX_ATTACHED_TABS {
                return Err(BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
                    "the attachment-owned tab limit has been reached".to_string(),
                )));
            }
            let transport = self.transport.read().await.clone();
            let owned = transport
                .create_owned_tab(url)
                .await
                .map_err(|error| BrowserRuntimeError::from_cdp(error, None))?;
            return self.adopt_owned_tab(transport, owned).await;
        }
        let params = match url {
            Some(u) => serde_json::json!({"url": u}),
            None => serde_json::json!({"url": "about:blank"}),
        };
        let result = self.cmd(None, "Target.createTarget", params).await?;
        let target_id = result
            .get("targetId")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                BrowserRuntimeError::Cdp(CdpError::Unexpected("missing targetId".into()))
            })?;
        let target = TargetId::from(target_id);
        let start = Instant::now();
        while start.elapsed() < ATTACH_WAIT {
            {
                let tabs = self.tabs.read().await;
                if tabs.get(&target).is_some_and(|t| t.session.is_some()) {
                    return Ok(TabId::from(target_id.to_string()));
                }
                if self.closed.load(Ordering::SeqCst) {
                    return Err(BrowserRuntimeError::ConnectionLost);
                }
            }
            tokio::time::sleep(POLL_INTERVAL).await;
        }
        Err(BrowserRuntimeError::Cdp(CdpError::Timeout(ATTACH_WAIT)))
    }

    /// Close a tab and wait for its removal from the registry.
    pub async fn close_tab(&self, tab: &TabId) -> Result<(), BrowserRuntimeError> {
        let target = TargetId::from(tab.as_str().to_string());
        if !self.tabs.read().await.contains(&target) {
            return Ok(()); // already gone: idempotent
        }
        if self.mode == SessionMode::Attached {
            if self.initial_attached_target.as_ref() == Some(&target) {
                return Err(BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
                    "the initially attached user tab cannot be closed by the agent".to_string(),
                )));
            }
            let transport = self.transport.read().await.clone();
            transport
                .close_owned_tab(&target)
                .await
                .map_err(|error| BrowserRuntimeError::from_cdp(error, Some(&target)))?;
            let start = Instant::now();
            while start.elapsed() < REMOVAL_WAIT {
                if !self.tabs.read().await.contains(&target) {
                    return Ok(());
                }
                tokio::time::sleep(POLL_INTERVAL).await;
            }
            return Err(BrowserRuntimeError::Cdp(CdpError::Timeout(REMOVAL_WAIT)));
        }
        match self
            .cmd(
                None,
                "Target.closeTarget",
                serde_json::json!({"targetId": target.as_str()}),
            )
            .await
        {
            Ok(_) => {}
            Err(BrowserRuntimeError::ProtocolError { .. }) => {} // "no target": treat as gone
            Err(e) => return Err(e),
        }
        let start = Instant::now();
        while start.elapsed() < REMOVAL_WAIT {
            if !self.tabs.read().await.contains(&target) {
                return Ok(());
            }
            tokio::time::sleep(POLL_INTERVAL).await;
        }
        Err(BrowserRuntimeError::Cdp(CdpError::Timeout(REMOVAL_WAIT)))
    }

    // -- navigation / observation / execution ---------------------------

    /// Navigate the active tab and wait for load. The main-frame navigation
    /// event advances the generation once the document actually changes.
    pub async fn navigate(&self, url: &str) -> Result<(), BrowserRuntimeError> {
        let tab = self
            .active_tab()
            .await
            .ok_or(BrowserRuntimeError::NoActiveTab)?;
        self.navigate_tab(&tab.id, url).await
    }

    pub async fn navigate_tab(&self, tab: &TabId, url: &str) -> Result<(), BrowserRuntimeError> {
        let (target, session) = self.tab_session(tab).await?;
        let _ = self.event_tx.send(BrowserEvent::NavigationStarted {
            tab: tab.clone(),
            url: url.to_string(),
        });
        let result = self
            .cmd(
                Some(&session),
                "Page.navigate",
                serde_json::json!({"url": url}),
            )
            .await;
        if let Err(e) = result {
            return Err(self.contextualize(e, Some(&target)).await);
        }
        if let Err(e) = self.wait_for_ready(&session, Some(url)).await {
            return Err(BrowserRuntimeError::NavigationFailed {
                url: url.to_string(),
                reason: e.to_string(),
            });
        }
        {
            let mut tabs = self.tabs.write().await;
            if let Some(t) = tabs.get_mut(&target) {
                t.url = url.to_string();
            }
        }
        let _ = self.event_tx.send(BrowserEvent::NavigationCompleted {
            tab: tab.clone(),
            url: url.to_string(),
        });
        browser_agent_telemetry::TraceEvent::new(
            "browser.navigate.done",
            format!("navigated to {url}"),
        )
        .with_session(self.session_id.clone())
        .emit();
        Ok(())
    }

    /// Observe the active tab (URL + title in M1; full snapshot in M2).
    pub async fn observe(&self) -> Result<SemanticSnapshot, BrowserRuntimeError> {
        let tab = self
            .active_tab()
            .await
            .ok_or(BrowserRuntimeError::NoActiveTab)?;
        self.observe_tab(&tab.id).await
    }

    /// Verify that the active tab's CDP session answers a bounded, read-only
    /// layout query. The response is checked locally and discarded.
    pub async fn probe_connection(&self) -> Result<(), BrowserRuntimeError> {
        let tab = self
            .active_tab()
            .await
            .ok_or(BrowserRuntimeError::NoActiveTab)?;
        let (_target, session) = self.tab_session(&tab.id).await?;
        let response = self
            .cmd(
                Some(&session),
                "Page.getLayoutMetrics",
                serde_json::json!({}),
            )
            .await?;
        if !response.get("layoutViewport").is_some_and(Value::is_object) {
            return Err(BrowserRuntimeError::InvalidResponse {
                method: "Page.getLayoutMetrics".to_string(),
            });
        }
        Ok(())
    }

    pub async fn observe_tab(&self, tab: &TabId) -> Result<SemanticSnapshot, BrowserRuntimeError> {
        crate::observer::observe_full(self, tab).await
    }

    /// Capture the visible viewport as transient base64 PNG data.
    ///
    /// Full-page capture is deliberately excluded: callers should request
    /// vision only after semantic observation is insufficient.
    pub async fn capture_viewport_screenshot(
        &self,
        tab: &TabId,
    ) -> Result<String, BrowserRuntimeError> {
        let (_, session) = self.tab_session(tab).await?;
        let result = self
            .cmd(
                Some(&session),
                "Page.captureScreenshot",
                serde_json::json!({
                    "format": "png",
                    "fromSurface": true,
                    "captureBeyondViewport": false,
                }),
            )
            .await?;
        let data = result.get("data").and_then(Value::as_str).ok_or_else(|| {
            BrowserRuntimeError::Cdp(CdpError::Unexpected(
                "Page.captureScreenshot missing base64 data".into(),
            ))
        })?;
        if data.len() > MAX_VIEWPORT_SCREENSHOT_BASE64_BYTES {
            return Err(BrowserRuntimeError::Cdp(CdpError::Unexpected(
                "viewport screenshot exceeds the 4 MiB encoded image limit".into(),
            )));
        }
        Ok(data.to_owned())
    }

    /// Incremental delta vs the previous snapshot of a tab.
    pub async fn observe_delta(&self, tab: &TabId) -> Result<SnapshotDelta, BrowserRuntimeError> {
        let target = TargetId::from(tab.as_str().to_string());
        self.require_live()?;
        Ok(self
            .deltas
            .read()
            .await
            .get(&target)
            .cloned()
            .unwrap_or_default())
    }

    /// Model-facing pruned observation for a tab.
    pub async fn agent_observation(
        &self,
        tab: &TabId,
        memory_refs: &HashSet<String>,
    ) -> Result<AgentObservation, BrowserRuntimeError> {
        let snapshot = self.observe_tab(tab).await?;
        let delta = self.observe_delta(tab).await?;
        let changed: HashSet<String> = delta
            .changed
            .iter()
            .map(|c| c.reference.clone())
            .chain(delta.added)
            .collect();
        Ok(browser_agent_observation::prune(
            &snapshot,
            &changed,
            memory_refs,
        ))
    }

    /// Rendered model-facing text for a tab (`@ref` blocks).
    pub async fn render_observation(
        &self,
        tab: &TabId,
        memory_refs: &HashSet<String>,
    ) -> Result<String, BrowserRuntimeError> {
        Ok(browser_agent_observation::render_text(
            &self.agent_observation(tab, memory_refs).await?,
        ))
    }

    /// Resolve a model-facing alias to its registry identity in a tab.
    /// Returns `None` for unknown or dropped refs. Compare `generation`
    /// against the current one for staleness (M4 agent use).
    pub async fn resolve(
        &self,
        tab: &TabId,
        alias: &str,
    ) -> Option<browser_agent_element_registry::ElementRef> {
        let target = TargetId::from(tab.as_str().to_string());
        self.registries
            .read()
            .await
            .get(&target)?
            .lookup_alias(alias)
    }

    /// Perform one structured action with verification: typed intent →
    /// state transition → proof. See `crate::act`.
    pub async fn act(
        &self,
        tab: &TabId,
        action: browser_agent_executor::BrowserAction,
        options: browser_agent_executor::ActOptions,
    ) -> browser_agent_executor::ActionOutcome {
        crate::act::act_on(self, tab, action, options).await
    }

    /// Evaluate a JS expression in a tab; returns the parsed value.
    pub async fn execute(
        &self,
        tab: &TabId,
        expression: &str,
    ) -> Result<Value, BrowserRuntimeError> {
        let (target, session) = self.tab_session(tab).await?;
        self.evaluate(&session, expression)
            .await
            .map_err(|e| self.map_err_sync(e, Some(&target)))
    }

    /// Accept or dismiss a JavaScript dialog in a tab.
    pub async fn handle_dialog(
        &self,
        tab: &TabId,
        accept: bool,
    ) -> Result<(), BrowserRuntimeError> {
        let (target, session) = self.tab_session(tab).await?;
        self.cmd(
            Some(&session),
            "Page.handleJavaScriptDialog",
            serde_json::json!({"accept": accept}),
        )
        .await
        .map(|_| ())
        .map_err(|e| self.map_err_sync(e, Some(&target)))
    }

    // -- reconnect / close ----------------------------------------------

    /// Drop the current transport and reconnect to the same browser endpoint,
    /// re-running discovery + auto-attach and re-adopting live targets.
    /// The browser process (if owned) is untouched.
    pub async fn reconnect(&self) -> Result<(), BrowserRuntimeError> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(BrowserRuntimeError::SessionClosed);
        }
        if self.mode == SessionMode::Attached {
            return Err(BrowserRuntimeError::ConnectionLost);
        }
        let ws_url = browser_ws_url(&self.base_url)
            .await
            .map_err(|_| BrowserRuntimeError::ConnectionLost)?;
        let fresh: Arc<dyn CdpTransport> = Arc::new(
            PersistentTransport::connect(&ws_url, self.command_timeout)
                .await
                .map_err(|e| BrowserRuntimeError::from_cdp(e, None))?,
        );
        let old = {
            let mut guard = self.transport.write().await;
            std::mem::replace(&mut *guard, Arc::clone(&fresh))
        };
        old.close().await;
        // Forget sessions bound to the dead transport; tabs/frames survive
        // (same browser) and are re-bound below.
        {
            let mut tabs = self.tabs.write().await;
            for tab in tabs.tabs() {
                if let Some(session) = tab.session.clone() {
                    tabs.unbind_session(&session);
                }
            }
        }
        // Restart the pump against the fresh transport *before* initialize
        // so auto-attach events cannot be missed.
        if let Some(handle) = self.pump.lock().await.take() {
            handle.abort();
        }
        self.spawn_pump().await;
        self.initialize(fresh.as_ref()).await?;
        // Wait until at least one tab is usable again.
        let start = Instant::now();
        while start.elapsed() < ATTACH_WAIT {
            {
                let tabs = self.tabs.read().await;
                if !tabs.is_empty() && tabs.tabs().iter().any(|t| t.session.is_some()) {
                    if tabs.active().is_none() {
                        drop(tabs);
                        let mut tabs = self.tabs.write().await;
                        if let Some(first) = tabs.tabs().first() {
                            let target = first.target.clone();
                            tabs.set_active(target);
                        }
                    }
                    return Ok(());
                }
            }
            tokio::time::sleep(POLL_INTERVAL).await;
        }
        Err(BrowserRuntimeError::ConnectionLost)
    }

    /// Graceful shutdown: ask the browser to close, stop transport + pump,
    /// kill a still-owned process. Dropping the session is the backstop.
    pub async fn close(mut self) -> Result<(), BrowserRuntimeError> {
        self.shutdown().await;
        self.chrome.take();
        Ok(())
    }

    async fn shutdown(&mut self) {
        self.closed.store(true, Ordering::SeqCst);
        if let Some(handle) = self.pump.lock().await.take() {
            handle.abort();
        }
        let transport = self.transport.read().await.clone();
        if self.mode == SessionMode::Attached {
            // The extension attachment is user-owned. Ask the extension to
            // detach every session debugger while preserving all browser tabs.
            let _ =
                tokio::time::timeout(Duration::from_secs(5), transport.detach_owned_tabs()).await;
        } else {
            // Best-effort graceful browser exit first; the owned-process kill
            // in `chrome.take()` (Drop) finishes the job if anything lingers.
            let _ = tokio::time::timeout(
                Duration::from_secs(5),
                transport.command("Browser.close", Value::Null),
            )
            .await;
        }
        transport.close().await;
        let _ = self.event_tx.send(BrowserEvent::ConnectionLost);
    }

    async fn adopt_owned_tab(
        &self,
        transport: Arc<dyn CdpTransport>,
        owned: OwnedTab,
    ) -> Result<TabId, BrowserRuntimeError> {
        let target = owned.target;
        let session = owned.session;
        let mut tabs = self.tabs.write().await;
        if tabs.len() >= MAX_ATTACHED_TABS {
            drop(tabs);
            let _ = transport.close_owned_tab(&target).await;
            return Err(BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
                "the attachment-owned tab limit has been reached".to_string(),
            )));
        }
        if tabs.contains(&target) {
            return Err(BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
                "the extension returned a duplicate owned-tab identity".to_string(),
            )));
        }
        tabs.upsert_target(target.clone(), owned.title, owned.url);
        tabs.bind_session(session.clone(), target.clone());
        drop(tabs);
        for method in ["Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"] {
            transport
                .command_in_session(&session, method, serde_json::json!({}))
                .await
                .map_err(|error| BrowserRuntimeError::from_cdp(error, Some(&target)))?;
        }
        let tab = TabId::from(target.as_str().to_string());
        let _ = self
            .event_tx
            .send(BrowserEvent::TargetCreated { tab: tab.clone() });
        Ok(tab)
    }

    // -- internals ------------------------------------------------------

    fn require_live(&self) -> Result<(), BrowserRuntimeError> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(BrowserRuntimeError::SessionClosed);
        }
        Ok(())
    }

    async fn tab_session(
        &self,
        tab: &TabId,
    ) -> Result<(TargetId, CdpSessionId), BrowserRuntimeError> {
        self.require_live()?;
        let target = TargetId::from(tab.as_str().to_string());
        let tabs = self.tabs.read().await;
        match tabs.get(&target) {
            Some(t) => match t.session.clone() {
                Some(session) => Ok((target, session)),
                None => Err(BrowserRuntimeError::TargetClosed(target)),
            },
            None => Err(BrowserRuntimeError::TargetClosed(target)),
        }
    }

    async fn cmd(
        &self,
        session: Option<&CdpSessionId>,
        method: &str,
        params: Value,
    ) -> Result<Value, BrowserRuntimeError> {
        let transport = self.transport.read().await.clone();
        let result = match session {
            Some(s) => transport.command_in_session(s, method, params).await,
            None => transport.command(method, params).await,
        };
        match result {
            Ok(v) => Ok(v),
            Err(e) => {
                if e.is_connection_fatal() {
                    self.closed.store(true, Ordering::SeqCst);
                }
                Err(BrowserRuntimeError::from_cdp(
                    e,
                    self.active_target().await.as_ref(),
                ))
            }
        }
    }

    async fn active_target(&self) -> Option<TargetId> {
        self.tabs.read().await.active().map(|t| t.target.clone())
    }

    async fn contextualize(
        &self,
        err: BrowserRuntimeError,
        target: Option<&TargetId>,
    ) -> BrowserRuntimeError {
        if err.is_terminal() {
            self.closed.store(true, Ordering::SeqCst);
        }
        match err {
            BrowserRuntimeError::Cdp(cdp) => BrowserRuntimeError::from_cdp(cdp, target),
            other => other,
        }
    }

    fn map_err_sync(
        &self,
        err: BrowserRuntimeError,
        target: Option<&TargetId>,
    ) -> BrowserRuntimeError {
        if err.is_terminal() {
            self.closed.store(true, Ordering::SeqCst);
        }
        match err {
            BrowserRuntimeError::Cdp(cdp) => BrowserRuntimeError::from_cdp(cdp, target),
            other => other,
        }
    }

    async fn evaluate(
        &self,
        session: &CdpSessionId,
        expression: &str,
    ) -> Result<Value, BrowserRuntimeError> {
        let result = self
            .cmd(
                Some(session),
                "Runtime.evaluate",
                serde_json::json!({
                    "expression": expression,
                    "returnByValue": true,
                    "awaitPromise": true,
                }),
            )
            .await?;
        let res = result.get("result").ok_or_else(|| {
            BrowserRuntimeError::Cdp(CdpError::Unexpected(
                "Runtime.evaluate missing result.result".into(),
            ))
        })?;
        if res.get("subtype").and_then(Value::as_str) == Some("error") {
            let desc = res
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or("js error");
            return Err(BrowserRuntimeError::ProtocolError {
                code: -1,
                message: format!("page JS error: {desc}"),
            });
        }
        Ok(res.get("value").cloned().unwrap_or(Value::Null))
    }

    async fn wait_for_ready(
        &self,
        session: &CdpSessionId,
        expect_url: Option<&str>,
    ) -> Result<(), BrowserRuntimeError> {
        let start = Instant::now();
        while start.elapsed() < self.navigation_timeout {
            let state = self
                .evaluate(session, "document.readyState")
                .await
                .unwrap_or(Value::Null);
            let href = self
                .evaluate(session, "window.location.href")
                .await
                .unwrap_or(Value::Null);
            // Fast-fail: Chrome committed an error page (DNS refused, etc.).
            // Waiting out the full timeout here only wastes a run's budget.
            if href
                .as_str()
                .is_some_and(|u| u.starts_with("chrome-error://"))
            {
                return Err(BrowserRuntimeError::NavigationFailed {
                    url: expect_url.unwrap_or("").to_string(),
                    reason: format!("browser committed error page: {href}"),
                });
            }
            let ready = state.as_str() == Some("complete");
            let url_ok = match expect_url {
                Some(prefix) => href.as_str().is_some_and(|u| {
                    u.trim_end_matches('/')
                        .starts_with(prefix.trim_end_matches('/'))
                        || prefix
                            .trim_end_matches('/')
                            .starts_with(u.trim_end_matches('/'))
                }),
                None => true,
            };
            if ready && url_ok {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        Err(BrowserRuntimeError::Cdp(CdpError::Timeout(
            self.navigation_timeout,
        )))
    }
}

impl Drop for BrowserSession {
    fn drop(&mut self) {
        self.closed.store(true, Ordering::SeqCst);
        // `LaunchedChrome::drop` kills an owned process; the transport's
        // `Drop` aborts reader/writer tasks. Pump handles are aborted here
        // (best effort: no async in Drop).
        if let Ok(mut pump) = self.pump.try_lock() {
            if let Some(handle) = pump.take() {
                handle.abort();
            }
        }
        self.chrome.take();
    }
}

fn validate_owned_tab_url(value: &str) -> Result<(), BrowserRuntimeError> {
    let invalid = || {
        BrowserRuntimeError::Cdp(CdpError::ExtensionBridge(
            "attached tab URLs must be bounded, credential-free HTTP or HTTPS URLs".to_string(),
        ))
    };
    if value.is_empty()
        || value.len() > MAX_ATTACHED_TAB_URL_BYTES
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(invalid());
    }
    let authority = value
        .strip_prefix("https://")
        .or_else(|| value.strip_prefix("http://"))
        .and_then(|remainder| remainder.split(['/', '?', '#']).next())
        .filter(|authority| !authority.is_empty() && !authority.contains('@'));
    if authority.is_none() {
        return Err(invalid());
    }
    Ok(())
}

/// Shared adoption logic for explicit attach and the event pump.
#[allow(clippy::too_many_arguments)]
async fn adopt_session_into(
    tabs: &Arc<RwLock<TabRegistry>>,
    event_tx: &broadcast::Sender<BrowserEvent>,
    transport: &Arc<dyn CdpTransport>,
    session: CdpSessionId,
    target: TargetId,
    title: String,
    url: String,
) -> Result<(), BrowserRuntimeError> {
    let tab_id = TabId::from(target.as_str().to_string());
    {
        let mut tabs = tabs.write().await;
        tabs.upsert_target(target.clone(), title, url);
        tabs.bind_session(session.clone(), target.clone());
        if tabs.active().is_none() {
            tabs.set_active(target.clone());
        }
    }
    // Domain enables for the fresh session. DOM/CSS enables are required
    // for the observer's box-model and computed-style queries (M2).
    // Domain enables run as a BACKGROUND task: the pump must never await
    // network I/O inline, or one swallowed response (observed: Chrome
    // occasionally never answers CSS.enable on a fresh session) wedges all
    // lifecycle processing behind a 30s timeout. A genuinely broken session
    // surfaces through its commands instead. Sequential on purpose: burst
    // enables on fresh sessions correlate with swallowed responses.
    {
        let transport = Arc::clone(transport);
        let session = session.clone();
        let target = target.clone();
        tokio::spawn(async move {
            for method in ["Page.enable", "Runtime.enable", "DOM.enable", "CSS.enable"] {
                if let Err(e) = transport
                    .command_in_session(&session, method, Value::Null)
                    .await
                {
                    tracing::warn!("domain enable {method} failed for {target}: {e}");
                }
            }
        });
    }
    let _ = event_tx.send(BrowserEvent::TargetCreated { tab: tab_id });
    Ok(())
}

/// Translate one transport event into registry updates + session events.
#[allow(clippy::too_many_arguments)]
async fn pump_one(
    tabs: &Arc<RwLock<TabRegistry>>,
    event_tx: &broadcast::Sender<BrowserEvent>,
    _session_id: &str,
    transport: &Arc<dyn CdpTransport>,
    closed: &Arc<AtomicBool>,
    dialog_open: &Arc<AtomicBool>,
    generation: &Arc<AtomicU64>,
    downloads: &mut HashMap<String, (TabId, String)>,
    event: CdpEvent,
) {
    match event {
        CdpEvent::AttachedToTarget { session, target } => {
            if target.target_type != "page" {
                return;
            }
            if let Err(e) = adopt_session_into(
                tabs,
                event_tx,
                transport,
                session,
                target.target_id.clone(),
                target.title.clone(),
                target.url.clone(),
            )
            .await
            {
                tracing::warn!("failed to adopt attached target: {e}");
            }
        }
        CdpEvent::DetachedFromTarget { session, .. } => {
            tabs.write().await.unbind_session(&session);
        }
        CdpEvent::TargetCreated { target } => {
            if target.target_type != "page" {
                return;
            }
            tabs.write().await.upsert_target(
                target.target_id.clone(),
                target.title.clone(),
                target.url.clone(),
            );
        }
        CdpEvent::TargetDestroyed { target_id } => {
            let removed = tabs.write().await.remove_target(&target_id);
            if let Some(tab) = removed {
                let _ = event_tx.send(BrowserEvent::TargetDestroyed { tab: tab.id });
            }
        }
        CdpEvent::TargetInfoChanged { target } => {
            if target.target_type == "page" {
                tabs.write()
                    .await
                    .upsert_target(target.target_id, target.title, target.url);
            }
        }
        CdpEvent::FrameAttached {
            session, frame_id, ..
        } => {
            // NOTE: resolve-then-branch (never `if let` directly on a lock
            // guard): scrutinee temporaries live through the body and would
            // deadlock `write()` below against our own read guard.
            let target = tabs.read().await.target_for_session(&session).cloned();
            if let Some(target) = target {
                let tab_id = TabId::from(target.as_str().to_string());
                tabs.write()
                    .await
                    .attach_frame(&target, frame_id.clone(), false);
                let _ = event_tx.send(BrowserEvent::FrameAttached {
                    tab: tab_id,
                    frame: frame_id,
                });
            }
        }
        CdpEvent::FrameDetached {
            session, frame_id, ..
        } => {
            let target = tabs.read().await.target_for_session(&session).cloned();
            if let Some(target) = target {
                let tab_id = TabId::from(target.as_str().to_string());
                tabs.write().await.detach_frame(&target, &frame_id);
                let _ = event_tx.send(BrowserEvent::FrameDetached {
                    tab: tab_id,
                    frame: frame_id,
                });
            }
        }
        CdpEvent::FrameNavigated { session, frame } => {
            // Main frame (no parent) navigations update the tab URL and
            // complete the navigation lifecycle for external navigations.
            // They also bump the generation: refs from before any navigation
            // (including click-triggered ones) are stale by definition.
            if frame.parent_id.is_none() {
                generation.fetch_add(1, Ordering::SeqCst);
                let target = tabs.read().await.target_for_session(&session).cloned();
                if let Some(target) = target {
                    let tab_id = TabId::from(target.as_str().to_string());
                    {
                        let mut tabs = tabs.write().await;
                        tabs.attach_frame(&target, frame.id.clone(), true);
                        if let Some(tab) = tabs.get_mut(&target) {
                            tab.url = frame.url.clone();
                        }
                    }
                    let _ = event_tx.send(BrowserEvent::NavigationCompleted {
                        tab: tab_id,
                        url: frame.url,
                    });
                }
            }
        }
        CdpEvent::FrameStartedLoading { .. }
        | CdpEvent::FrameStoppedLoading { .. }
        | CdpEvent::LoadEventFired { .. }
        | CdpEvent::ExecutionContextsCleared { .. }
        | CdpEvent::Unknown { .. } => {}
        CdpEvent::DialogOpening {
            session,
            dialog_type,
            message,
            ..
        } => {
            dialog_open.store(true, Ordering::SeqCst);
            let target = tabs.read().await.target_for_session(&session).cloned();
            if let Some(target) = target {
                let tab_id = TabId::from(target.as_str().to_string());
                let _ = event_tx.send(BrowserEvent::DialogOpened {
                    tab: tab_id,
                    dialog_type,
                    message,
                });
            }
        }
        CdpEvent::DialogClosed { session } => {
            dialog_open.store(false, Ordering::SeqCst);
            if let Some(target) = tabs.read().await.target_for_session(&session).cloned() {
                let _ = event_tx.send(BrowserEvent::DialogClosed {
                    tab: TabId::from(target.as_str().to_string()),
                });
            }
        }
        CdpEvent::DownloadWillBegin {
            session,
            guid,
            url,
            suggested_filename,
        } => {
            let target = tabs.read().await.target_for_session(&session).cloned();
            if let Some(target) = target {
                let tab_id = TabId::from(target.as_str().to_string());
                downloads.insert(guid.clone(), (tab_id.clone(), suggested_filename.clone()));
                let _ = event_tx.send(BrowserEvent::DownloadStarted {
                    tab: tab_id,
                    filename: suggested_filename,
                    url,
                });
            }
        }
        CdpEvent::DownloadProgress { guid, state, .. } => {
            if state == "completed" {
                if let Some((tab, filename)) = downloads.remove(&guid) {
                    let _ = event_tx.send(BrowserEvent::DownloadCompleted { tab, filename });
                }
            }
        }
        CdpEvent::TargetCrashed { session, .. } => {
            let target = match session {
                Some(s) => tabs.read().await.target_for_session(&s).cloned(),
                None => None,
            };
            if let Some(target) = target {
                let tab_id = TabId::from(target.as_str().to_string());
                if let Some(tab) = tabs.write().await.get_mut(&target) {
                    tab.crashed = true;
                }
                let _ = event_tx.send(BrowserEvent::PageCrashed { tab: tab_id });
            }
        }
        CdpEvent::ConnectionLost => {
            // Terminal: no further command can succeed. Mark it here so
            // `is_live()` flips deterministically with the event.
            closed.store(true, Ordering::SeqCst);
            let _ = event_tx.send(BrowserEvent::ConnectionLost);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::future::Future;
    use std::pin::Pin;
    use std::sync::atomic::AtomicUsize;
    use std::sync::Mutex;

    struct MockTransport {
        events: broadcast::Sender<CdpEvent>,
        commands: Mutex<Vec<String>>,
        detach_owned_tabs_calls: AtomicUsize,
    }

    impl MockTransport {
        fn new() -> Self {
            let (events, _) = broadcast::channel(8);
            Self {
                events,
                commands: Mutex::new(Vec::new()),
                detach_owned_tabs_calls: AtomicUsize::new(0),
            }
        }
    }

    impl CdpTransport for MockTransport {
        fn command<'a>(
            &'a self,
            method: &'a str,
            _params: Value,
        ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
            Box::pin(async move {
                self.commands.lock().unwrap().push(method.to_string());
                if method == "Page.getLayoutMetrics" {
                    Ok(serde_json::json!({"layoutViewport": {}}))
                } else {
                    Ok(Value::Null)
                }
            })
        }

        fn command_in_session<'a>(
            &'a self,
            _session: &'a CdpSessionId,
            method: &'a str,
            params: Value,
        ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
            self.command(method, params)
        }

        fn command_with_timeout<'a>(
            &'a self,
            session: Option<&'a CdpSessionId>,
            method: &'a str,
            params: Value,
            _timeout: Duration,
        ) -> Pin<Box<dyn Future<Output = Result<Value, CdpError>> + Send + 'a>> {
            match session {
                Some(session) => self.command_in_session(session, method, params),
                None => self.command(method, params),
            }
        }

        fn subscribe(&self) -> broadcast::Receiver<CdpEvent> {
            self.events.subscribe()
        }

        fn is_connected(&self) -> bool {
            true
        }

        fn pending_commands(&self) -> usize {
            0
        }

        fn detach_owned_tabs<'a>(
            &'a self,
        ) -> Pin<Box<dyn Future<Output = Result<(), CdpError>> + Send + 'a>> {
            Box::pin(async move {
                self.detach_owned_tabs_calls.fetch_add(1, Ordering::SeqCst);
                Ok(())
            })
        }

        fn close<'a>(&'a self) -> Pin<Box<dyn Future<Output = ()> + Send + 'a>> {
            Box::pin(async {})
        }
    }

    #[test]
    fn launch_options_defaults() {
        let opts = LaunchOptions::default();
        assert!(opts.headless);
        assert_eq!(opts.navigation_timeout, Duration::from_secs(30));
    }

    #[tokio::test]
    async fn attached_transport_seeds_one_tab_and_enables_page_domains() {
        let transport = Arc::new(MockTransport::new());
        let commands = &transport.commands;
        let session = BrowserSession::from_attached_transport(
            transport.clone(),
            TargetId::from("tab-17"),
            CdpSessionId::from("attachment-17"),
            None,
            "Search results".to_string(),
            "https://example.test/results".to_string(),
            LaunchOptions::default(),
        )
        .await
        .unwrap();

        let tabs = session.tabs().await;
        assert_eq!(tabs.len(), 1);
        assert_eq!(tabs[0].id.as_str(), "tab-17");
        assert_eq!(tabs[0].title, "Search results");
        assert_eq!(tabs[0].url, "https://example.test/results");
        assert_eq!(
            *commands.lock().unwrap(),
            ["Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"]
        );
        session.probe_connection().await.unwrap();
        assert_eq!(
            commands.lock().unwrap().last().map(String::as_str),
            Some("Page.getLayoutMetrics")
        );
        assert!(matches!(
            session.reconnect().await,
            Err(BrowserRuntimeError::ConnectionLost)
        ));

        assert!(session.close_tab(&TabId::from("tab-17")).await.is_err());

        session.close().await.unwrap();
        assert_eq!(transport.detach_owned_tabs_calls.load(Ordering::SeqCst), 1);
        assert!(!commands
            .lock()
            .unwrap()
            .contains(&"Browser.close".to_string()));
    }

    #[tokio::test]
    async fn connection_probe_works_for_managed_sessions() {
        let transport = Arc::new(MockTransport::new());
        let target = TargetId::from("managed-tab");
        let cdp_session = CdpSessionId::from("managed-session");
        let mut registry = TabRegistry::new();
        registry.upsert_target(
            target.clone(),
            "Managed".into(),
            "https://example.test".into(),
        );
        registry.bind_session(cdp_session, target.clone());
        registry.set_active(target);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_CAPACITY);
        let session = BrowserSession {
            session_id: "managed-session".into(),
            mode: SessionMode::Managed,
            initial_attached_target: None,
            chrome: None,
            base_url: String::new(),
            transport: RwLock::new(transport.clone()),
            tabs: Arc::new(RwLock::new(registry)),
            event_tx,
            generation: Arc::new(AtomicU64::new(0)),
            navigation_timeout: LaunchOptions::default().navigation_timeout,
            command_timeout: LaunchOptions::default().command_timeout,
            closed: Arc::new(AtomicBool::new(false)),
            pump: tokio::sync::Mutex::new(None),
            registries: Arc::new(RwLock::new(HashMap::new())),
            snapshots: Arc::new(RwLock::new(HashMap::new())),
            deltas: Arc::new(RwLock::new(HashMap::new())),
            dialog_open_flag: Arc::new(AtomicBool::new(false)),
        };

        session.probe_connection().await.unwrap();
        assert_eq!(
            *transport.commands.lock().unwrap(),
            ["Page.getLayoutMetrics"]
        );
    }
}
