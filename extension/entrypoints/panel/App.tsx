import { useEffect, useMemo, useState } from "react";
import {
  PROTOCOL_VERSION,
  type ExtensionSnapshot,
  type PendingApproval,
  type TimelineEvent,
} from "../../src/protocol";

const EMPTY_SNAPSHOT: ExtensionSnapshot = {
  host: "disconnected",
  hostError: null,
  protocolReady: false,
  session: null,
  events: [],
  pendingApproval: null,
  openAiKeyConfigured: false,
  settingsError: null,
  selectedTab: null,
  attachment: null,
};

type BackgroundErrorResponse = {
  snapshot: ExtensionSnapshot;
  error?: string;
};
type DispatchResult = ExtensionSnapshot & { error?: string };

function App() {
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const [task, setTask] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [panelError, setPanelError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoConnect, setAutoConnect] = useState(false);

  useEffect(() => {
    const port = chrome.runtime.connect({ name: "browski-panel" });
    port.onMessage.addListener((message: { snapshot?: ExtensionSnapshot }) => {
      if (message.snapshot) {
        setSnapshot(message.snapshot);
      }
    });

    void chrome.runtime
      .sendMessage({ type: "panel.snapshot" })
      .then((result) => {
        if (isSnapshot(result)) {
          setSnapshot(result);
        }
      })
      .catch(() => undefined);

    void chrome.storage.local.get("autoConnectNativeHost").then((value) => {
      const enabled = value.autoConnectNativeHost === true;
      setAutoConnect(enabled);
      if (enabled) {
        void chrome.runtime.sendMessage({ type: "host.connect" }).catch(() => undefined);
      }
    });

    return () => port.disconnect();
  }, []);

  const orderedEvents = useMemo(
    () => [...snapshot.events].sort((a, b) => b.sequence - a.sequence),
    [snapshot.events],
  );

  async function dispatch(message: Record<string, unknown>): Promise<DispatchResult> {
    setPanelError(null);
    setBusy(true);
    try {
      const result = await chrome.runtime.sendMessage(message);
      if (isPanelResponse(result)) {
        setSnapshot(result.snapshot);
        if (result.error) {
          setPanelError(result.error);
        }
        return { ...result.snapshot, error: result.error };
      }
      if (isSnapshot(result)) {
        setSnapshot(result);
        return result;
      }
      throw new Error("The extension background did not return a valid response.");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setPanelError(detail);
      return { ...snapshot, error: detail };
    } finally {
      setBusy(false);
    }
  }

  async function saveAutoConnect(enabled: boolean): Promise<void> {
    setAutoConnect(enabled);
    await chrome.storage.local.set({ autoConnectNativeHost: enabled });
    if (enabled && snapshot.host === "disconnected") {
      await dispatch({ type: "host.connect" });
    }
  }

  async function submitTask(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = await dispatch({ type: "task.submit", task });
    if (!result.error) {
      setTask("");
    }
  }

  async function respondToApproval(
    approval: PendingApproval,
    approved: boolean,
  ): Promise<void> {
    await dispatch({
      type: "approval.respond",
      approvalId: approval.approvalId,
      approved,
    });
  }

  async function controlTask(control: "pause" | "resume" | "stop"): Promise<void> {
    await dispatch({ type: "task.control", control });
  }

  async function saveApiKey(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = await dispatch({ type: "credentials.set", apiKey });
    if (!result.error) {
      setApiKey("");
    }
  }

  const hostLabel = hostStatusLabel(snapshot.host, snapshot.protocolReady);
  const canSubmitTask = Boolean(
    snapshot.protocolReady &&
    snapshot.session &&
    snapshot.session.status !== "running" &&
    snapshot.session.status !== "awaiting_approval",
  );

  return (
    <main className="panel-shell">
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            B
          </span>
          <div>
            <p className="eyebrow">BROWSKI</p>
            <h1>Browser companion</h1>
          </div>
        </div>
        <span className={`connection-state state-${snapshot.host}`}>
          <span className="state-dot" aria-hidden="true" />
          {hostLabel}
        </span>
      </header>

      <section className="runtime-strip" aria-labelledby="runtime-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">LOCAL RUNTIME</p>
            <h2 id="runtime-heading">Session connection</h2>
          </div>
          <span className="protocol-badge">Protocol v{PROTOCOL_VERSION}</span>
        </div>

        <p className="muted-copy">
          {snapshot.protocolReady
            ? snapshot.session
              ? `Session ${snapshot.session.sessionId}`
              : "Host connected. Waiting for a runtime session."
            : "Connect the local Native Messaging host to see runtime sessions."}
        </p>
        {snapshot.hostError && <p className="inline-error">{snapshot.hostError}</p>}
        <div className="button-row">
          {snapshot.host === "connected" ? (
            <button
              className="button button-secondary"
              onClick={() => void dispatch({ type: "host.disconnect" })}
              disabled={busy}
            >
              Disconnect host
            </button>
          ) : (
            <button
              className="button button-primary"
              onClick={() => void dispatch({ type: "host.connect" })}
              disabled={busy || snapshot.host === "connecting"}
            >
              {snapshot.host === "connecting" ? "Connecting…" : "Connect runtime host"}
            </button>
          )}
        </div>
      </section>

      <section className="tab-section" aria-labelledby="tab-heading">
        <div className="section-heading compact-heading">
          <div>
            <p className="eyebrow">BROWSER TAB</p>
            <h2 id="tab-heading">Transport attachment</h2>
          </div>
          <span className={`text-state ${snapshot.attachment ? "text-state-on" : ""}`}>
            {snapshot.attachment?.state ??
              (snapshot.selectedTab ? "Ready to confirm" : "Not attached")}
          </span>
        </div>
        <p className="muted-copy">
          {snapshot.attachment?.message ??
            "Capture the active tab, review its origin, then confirm attachment."}
        </p>
        {snapshot.selectedTab && !snapshot.attachment && (
          <div className="selection-review">
            <span className="selection-label">Selected tab origin</span>
            <code>{snapshot.selectedTab.origin}</code>
            <span className="tab-reference">
              Tab <code>#{snapshot.selectedTab.tabId}</code> · selection stays fixed if tabs
              change
            </span>
          </div>
        )}
        {snapshot.attachment && (
          <div className="selection-review">
            <span className="selection-label">Attached tab origin</span>
            <code>{snapshot.attachment.origin}</code>
            <span className="tab-reference">
              Tab <code>#{snapshot.attachment.tabId}</code>
            </span>
          </div>
        )}
        <div className="button-row">
          {snapshot.attachment && snapshot.attachment.state !== "error" ? (
            <button
              className="button button-secondary"
              onClick={() => void dispatch({ type: "tab.detach" })}
              disabled={busy}
            >
              Detach tab
            </button>
          ) : snapshot.attachment?.state === "error" ? (
            <button
              className="button button-secondary"
              onClick={() => void dispatch({ type: "tab.detach" })}
              disabled={busy}
            >
              Clear attachment error
            </button>
          ) : snapshot.selectedTab ? (
            <>
              <button
                className="button button-primary"
                onClick={() => void dispatch({ type: "tab.attachSelected" })}
                disabled={!snapshot.protocolReady || busy}
              >
                Confirm and attach
              </button>
              <button
                className="button button-secondary"
                onClick={() => void dispatch({ type: "tab.captureActive" })}
                disabled={!snapshot.protocolReady || busy}
              >
                Choose current tab
              </button>
              <button
                className="button button-secondary"
                onClick={() => void dispatch({ type: "tab.clearSelection" })}
                disabled={busy}
              >
                Clear selection
              </button>
            </>
          ) : (
            <button
              className="button button-secondary"
              onClick={() => void dispatch({ type: "tab.captureActive" })}
              disabled={!snapshot.protocolReady || busy}
            >
              Capture active tab
            </button>
          )}
        </div>
        {!snapshot.session && (
          <p className="footnote">
            Attaching a tab creates a local runtime session for that browser tab.
          </p>
        )}
      </section>

      {snapshot.pendingApproval && (
        <ApprovalPanel
          approval={snapshot.pendingApproval}
          busy={busy}
          onRespond={respondToApproval}
        />
      )}

      <section className="task-section" aria-labelledby="task-heading">
        <div className="section-heading compact-heading">
          <div>
            <p className="eyebrow">TASK</p>
            <h2 id="task-heading">Send to runtime</h2>
          </div>
          {snapshot.session && <StatusTag status={snapshot.session.status} />}
        </div>
        <form onSubmit={(event) => void submitTask(event)}>
          <label htmlFor="task-input">Task instruction</label>
          <textarea
            id="task-input"
            value={task}
            onChange={(event) => setTask(event.target.value)}
            placeholder="Available after a runtime session connects"
            maxLength={4000}
            disabled={!canSubmitTask || busy}
            rows={4}
          />
          <div className="form-footer">
            <span className="character-count">{task.length}/4000</span>
            <button
              type="submit"
              className="button button-primary"
              disabled={!canSubmitTask || busy || task.trim().length === 0}
            >
              Send task
            </button>
          </div>
        </form>
        <p className="footnote">
          Task status comes from the runtime. Sending a request does not mean it succeeded.
        </p>
        {snapshot.session && snapshot.events.some((event) => event.runId) && (
          <div className="button-row task-controls" aria-label="Task controls">
            {snapshot.session.status === "running" && (
              <button
                className="button button-secondary"
                onClick={() => void controlTask("pause")}
                disabled={busy}
              >
                Pause
              </button>
            )}
            {snapshot.session.status === "idle" && (
              <button
                className="button button-secondary"
                onClick={() => void controlTask("resume")}
                disabled={busy}
              >
                Resume
              </button>
            )}
            {["running", "idle"].includes(snapshot.session.status) && (
              <button
                className="button button-danger"
                onClick={() => void controlTask("stop")}
                disabled={busy}
              >
                Stop
              </button>
            )}
          </div>
        )}
      </section>

      {panelError && (
        <p className="inline-error panel-error" role="alert">
          {panelError}
        </p>
      )}

      <section className="timeline-section" aria-labelledby="timeline-heading">
        <div className="section-heading compact-heading">
          <div>
            <p className="eyebrow">RUNTIME EVENTS</p>
            <h2 id="timeline-heading">Timeline</h2>
          </div>
          <span className="event-count">{orderedEvents.length}</span>
        </div>
        {orderedEvents.length === 0 ? (
          <p className="empty-state">No runtime events yet.</p>
        ) : (
          <ol className="timeline-list">
            {orderedEvents.map((event) => (
              <TimelineRow key={event.eventId} event={event} />
            ))}
          </ol>
        )}
      </section>

      <details className="settings-section">
        <summary>Settings and transport details</summary>
        <div className="settings-content">
          <div className="credential-setting">
            <div className="setting-heading">
              <span>OpenAI API key</span>
              <span className="text-state">
                {snapshot.openAiKeyConfigured ? "Configured" : "Not configured"}
              </span>
            </div>
            <form onSubmit={(event) => void saveApiKey(event)}>
              <label htmlFor="openai-key">Configure key on this device</label>
              <input
                id="openai-key"
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                maxLength={4096}
                placeholder="Paste an API key"
                disabled={!snapshot.protocolReady || busy}
              />
              <div className="button-row">
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={!snapshot.protocolReady || busy || apiKey.length === 0}
                >
                  Save securely
                </button>
                {snapshot.openAiKeyConfigured && (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void dispatch({ type: "credentials.clear" })}
                    disabled={busy || !snapshot.protocolReady}
                  >
                    Remove key
                  </button>
                )}
              </div>
            </form>
            <p className="footnote">
              The key is sent only to the authenticated local runtime and stored in the
              operating system keyring. It is never saved in extension storage or sent to
              page scripts.
            </p>
            {snapshot.settingsError && (
              <p className="inline-error" role="alert">
                {snapshot.settingsError}
              </p>
            )}
          </div>
          <label className="setting-toggle">
            <input
              type="checkbox"
              checked={autoConnect}
              onChange={(event) => void saveAutoConnect(event.target.checked)}
            />
            <span>Connect to the runtime host when this panel opens</span>
          </label>
          <dl className="settings-list">
            <div>
              <dt>Native host</dt>
              <dd>
                <code>com.browski.runtime</code>
              </dd>
            </div>
            <div>
              <dt>Transport</dt>
              <dd>Chrome Native Messaging</dd>
            </div>
            <div>
              <dt>Tab bridge</dt>
              <dd>Active-tab, allowlisted debugger messages</dd>
            </div>
          </dl>
          <p className="footnote">
            Browser control stays in the shared Rust runtime. Chrome shows a debugger
            permission warning when you attach a tab.
          </p>
        </div>
      </details>

      <footer className="panel-footer">
        <span>Local companion</span>
        <span>v0.1 · protocol {PROTOCOL_VERSION}</span>
      </footer>
    </main>
  );
}

function ApprovalPanel({
  approval,
  busy,
  onRespond,
}: {
  approval: PendingApproval;
  busy: boolean;
  onRespond: (approval: PendingApproval, approved: boolean) => Promise<void>;
}) {
  return (
    <section className="approval-panel" aria-labelledby="approval-heading">
      <div className="approval-topline">
        <p className="eyebrow">USER APPROVAL REQUIRED</p>
        <span className={`risk-tag risk-${approval.risk}`}>{approval.risk} risk</span>
      </div>
      <h2 id="approval-heading">{approval.title}</h2>
      <p>{approval.summary}</p>
      <div className="button-row approval-actions">
        <button
          className="button button-primary"
          onClick={() => void onRespond(approval, true)}
          disabled={busy}
        >
          Approve action
        </button>
        <button
          className="button button-secondary"
          onClick={() => void onRespond(approval, false)}
          disabled={busy}
        >
          Deny action
        </button>
      </div>
      <p className="footnote">The runtime ties this choice to its pending checkpoint.</p>
    </section>
  );
}

function StatusTag({ status }: { status: string }) {
  return <span className={`status-tag status-${status}`}>{formatStatus(status)}</span>;
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  return (
    <li className={`timeline-item event-${event.status}`}>
      <span className="timeline-marker" aria-hidden="true" />
      <div className="timeline-copy">
        <div className="timeline-title-line">
          <h3>{event.label}</h3>
          <time dateTime={event.createdAt}>{formatTime(event.createdAt)}</time>
        </div>
        {event.detail && <p>{event.detail}</p>}
      </div>
    </li>
  );
}

function hostStatusLabel(
  status: ExtensionSnapshot["host"],
  protocolReady: boolean,
): string {
  if (status === "connected" && protocolReady) return "Connected";
  if (status === "connected") return "Negotiating";
  if (status === "connecting") return "Connecting";
  if (status === "error") return "Connection error";
  return "Disconnected";
}

function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function isSnapshot(value: unknown): value is ExtensionSnapshot {
  return typeof value === "object" && value !== null && "host" in value;
}

function isPanelResponse(value: unknown): value is BackgroundErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "snapshot" in value &&
    isSnapshot(value.snapshot)
  );
}

export default App;
