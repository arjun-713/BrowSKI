import { useEffect, useState, type FormEvent } from "react";
import {
  PROTOCOL_VERSION,
  type ExtensionSnapshot,
  type RuntimeSettingsUpdate,
} from "../src/protocol";

export function SettingsPanel({
  snapshot,
  busy,
  autoConnect,
  onDispatch,
  onSaveAutoConnect,
  onSaveRuntimeSettings,
}: {
  snapshot: ExtensionSnapshot;
  busy: boolean;
  autoConnect: boolean;
  onDispatch: (message: Record<string, unknown>) => Promise<{ error?: string }>;
  onSaveAutoConnect: (enabled: boolean) => Promise<void>;
  onSaveRuntimeSettings: (settings: RuntimeSettingsUpdate) => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [runtimeDraft, setRuntimeDraft] = useState<RuntimeSettingsUpdate | null>(null);
  const [savingRuntimeSettings, setSavingRuntimeSettings] = useState(false);
  const runtimeSettings = snapshot.runtimeSettings;

  useEffect(() => {
    if (runtimeSettings) {
      setRuntimeDraft({
        effort: runtimeSettings.effort,
        privacyMode: runtimeSettings.privacyMode,
        layaMode: runtimeSettings.layaMode,
        traceLevel: runtimeSettings.traceLevel,
      });
    }
  }, [runtimeSettings]);

  async function saveApiKey(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = await onDispatch({ type: "credentials.set", apiKey });
    if (!result.error) {
      setApiKey("");
    }
  }

  async function saveRuntimeSettings(): Promise<void> {
    if (!runtimeDraft) {
      return;
    }
    setSavingRuntimeSettings(true);
    try {
      await onSaveRuntimeSettings(runtimeDraft);
    } finally {
      setSavingRuntimeSettings(false);
    }
  }

  function updateRuntimeSetting<Key extends keyof RuntimeSettingsUpdate>(
    key: Key,
    value: RuntimeSettingsUpdate[Key],
  ): void {
    setRuntimeDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  const hasActiveTask = ["running", "paused", "awaiting_approval"].includes(
    snapshot.session?.status ?? "",
  );
  const runtimeSettingsChanged = Boolean(
    runtimeSettings &&
    runtimeDraft &&
    (runtimeSettings.effort !== runtimeDraft.effort ||
      runtimeSettings.privacyMode !== runtimeDraft.privacyMode ||
      runtimeSettings.layaMode !== runtimeDraft.layaMode ||
      runtimeSettings.traceLevel !== runtimeDraft.traceLevel),
  );
  const runtimeSettingsDisabled =
    !snapshot.protocolReady ||
    busy ||
    savingRuntimeSettings ||
    hasActiveTask ||
    !runtimeDraft;

  return (
    <details className="settings-section">
      <summary>Settings and transport details</summary>
      <div className="settings-content">
        <section className="runtime-settings" aria-labelledby="runtime-settings-heading">
          <div className="setting-heading">
            <span id="runtime-settings-heading">Runtime settings</span>
            {runtimeSettings && <span className="text-state">Connected</span>}
          </div>
          {!snapshot.protocolReady ? (
            <p className="footnote">
              Connect the runtime host to read and change settings.
            </p>
          ) : !runtimeSettings ? (
            <p className="footnote">
              {snapshot.settingsError ?? "Loading runtime settings…"}
            </p>
          ) : (
            <>
              <label htmlFor="runtime-effort">Default reasoning effort</label>
              <select
                id="runtime-effort"
                value={runtimeDraft?.effort ?? ""}
                onChange={(event) =>
                  updateRuntimeSetting(
                    "effort",
                    event.target.value as RuntimeSettingsUpdate["effort"],
                  )
                }
                disabled={runtimeSettingsDisabled}
              >
                <option value="none">None</option>
                <option value="low">Low</option>
              </select>

              <label htmlFor="runtime-privacy">Privacy mode</label>
              <select
                id="runtime-privacy"
                value={runtimeDraft?.privacyMode ?? ""}
                onChange={(event) =>
                  updateRuntimeSetting(
                    "privacyMode",
                    event.target.value as RuntimeSettingsUpdate["privacyMode"],
                  )
                }
                disabled={runtimeSettingsDisabled}
              >
                <option value="standard">Standard</option>
                <option value="privacy_first">Privacy first</option>
                <option value="offline">Offline</option>
              </select>

              <label htmlFor="runtime-laya">Laya comparison</label>
              <select
                id="runtime-laya"
                value={runtimeDraft?.layaMode ?? ""}
                onChange={(event) =>
                  updateRuntimeSetting(
                    "layaMode",
                    event.target.value as RuntimeSettingsUpdate["layaMode"],
                  )
                }
                disabled={runtimeSettingsDisabled}
              >
                <option value="disabled">Disabled</option>
                <option value="shadow">Shadow only</option>
              </select>
              <p className="footnote">Laya never selects or executes browser actions.</p>

              <label htmlFor="runtime-trace-level">Trace detail</label>
              <select
                id="runtime-trace-level"
                value={runtimeDraft?.traceLevel ?? ""}
                onChange={(event) =>
                  updateRuntimeSetting(
                    "traceLevel",
                    event.target.value as RuntimeSettingsUpdate["traceLevel"],
                  )
                }
                disabled={runtimeSettingsDisabled}
              >
                <option value="standard">Normal</option>
                <option value="detailed">Developer detail</option>
              </select>

              <div className="setting-heading runtime-readonly-setting">
                <span>High-risk confirmation</span>
                <span className="text-state text-state-on">
                  {runtimeSettings.confirmHighRiskActions
                    ? "Always required"
                    : "Unavailable"}
                </span>
              </div>
              <p className="footnote">
                High-risk actions always require your confirmation and cannot be disabled
                here.
              </p>

              <div className="setting-heading runtime-readonly-setting">
                <span>Browser transport</span>
                <span className="text-state">
                  {runtimeSettings.extensionTransport === "native_host"
                    ? "Attached browser through Chrome Native Messaging"
                    : "Disabled in CLI configuration"}
                </span>
              </div>
              <p className="footnote">
                Change browser transport from the local CLI configuration.
              </p>

              <div className="button-row">
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => void saveRuntimeSettings()}
                  disabled={runtimeSettingsDisabled || !runtimeSettingsChanged}
                >
                  Save runtime settings
                </button>
                {hasActiveTask && (
                  <span className="footnote">
                    Finish or stop the active task before changing runtime settings.
                  </span>
                )}
              </div>
              <p className="footnote">
                Changes apply to the next task. Complexity checks may temporarily raise
                effort when needed.
              </p>
            </>
          )}
          {snapshot.settingsError && (
            <p className="inline-error" role="alert">
              {snapshot.settingsError}
            </p>
          )}
        </section>

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
                  onClick={() => void onDispatch({ type: "credentials.clear" })}
                  disabled={busy || !snapshot.protocolReady}
                >
                  Remove key
                </button>
              )}
            </div>
          </form>
          <p className="footnote">
            The key is sent only to the authenticated local runtime and stored in the
            operating system keyring. It is never saved in extension storage or sent to page
            scripts.
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
            onChange={(event) => void onSaveAutoConnect(event.target.checked)}
          />
          <span>Connect to the runtime host when this panel opens</span>
        </label>
        <dl className="settings-list">
          <div>
            <dt>Protocol</dt>
            <dd>Version {PROTOCOL_VERSION}</dd>
          </div>
          {snapshot.session && (
            <div>
              <dt>Session reference</dt>
              <dd>
                <code>{snapshot.session.sessionId}</code>
              </dd>
            </div>
          )}
          {snapshot.attachment && (
            <div>
              <dt>Attached Chrome tab</dt>
              <dd>#{snapshot.attachment.tabId}</dd>
            </div>
          )}
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
  );
}
