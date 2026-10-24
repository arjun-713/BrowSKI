import { useEffect, useState, type FormEvent } from "react";
import {
  PROTOCOL_VERSION,
  editableRuntimeSettings,
  type ExtensionSnapshot,
  type RuntimeSettingsUpdate,
} from "../src/protocol";
import { EngineSettingsFields } from "./EngineSettingsFields";
import { TabAttachment } from "./TabAttachment";
import { Icon } from "./Icon";

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
  const [draft, setDraft] = useState<RuntimeSettingsUpdate | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const settings = snapshot.runtimeSettings;
  useEffect(() => {
    if (settings) setDraft(editableRuntimeSettings(settings));
  }, [settings]);

  const active = ["running", "paused", "awaiting_approval"].includes(
    snapshot.session?.status ?? "",
  );
  const disabled = !snapshot.protocolReady || busy || saving || active || !draft;
  const changed =
    settings &&
    draft &&
    JSON.stringify(editableRuntimeSettings(settings)) !== JSON.stringify(draft);
  const valid =
    !draft ||
    [draft.textModel, draft.layaCheckpoint, draft.jevEndpoint].every(
      (value) => value === undefined || value.trim().length > 0,
    );

  function update(patch: Partial<RuntimeSettingsUpdate>): void {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setNotice(null);
  }

  async function save(): Promise<void> {
    if (!draft || !valid) return;
    setSaving(true);
    try {
      await onSaveRuntimeSettings(draft);
      setNotice("Settings saved for your next task.");
    } catch {
      setNotice("Settings could not be saved. Check the connection and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function saveKey(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = await onDispatch({ type: "credentials.set", apiKey });
    if (!result.error) setApiKey("");
  }

  return (
    <div className="settings-content">
      <section className="settings-group" aria-labelledby="engine-settings-heading">
        <h2 id="engine-settings-heading">Engine and model</h2>
        {!snapshot.protocolReady ? (
          <p className="footnote">
            Connect the local runtime to read and change your agent settings.
          </p>
        ) : !draft ? (
          <p className="footnote">{snapshot.settingsError ?? "Loading settings…"}</p>
        ) : (
          <>
            <EngineSettingsFields settings={draft} disabled={disabled} onChange={update} />
            <label htmlFor="runtime-privacy">Privacy mode</label>
            <select
              id="runtime-privacy"
              value={draft.privacyMode}
              disabled={disabled}
              onChange={(event) =>
                update({
                  privacyMode: event.target.value as RuntimeSettingsUpdate["privacyMode"],
                })
              }
            >
              <option value="standard">Standard</option>
              <option value="privacy_first">Privacy first</option>
              <option value="offline">Offline</option>
            </select>
            <p className="footnote">
              General needs Standard mode to use OpenAI. Stricter modes keep hosted
              inference unavailable.
            </p>
            <label htmlFor="runtime-trace-level">Debug capture</label>
            <select
              id="runtime-trace-level"
              value={draft.traceLevel}
              disabled={disabled}
              onChange={(event) =>
                update({
                  traceLevel: event.target.value as RuntimeSettingsUpdate["traceLevel"],
                })
              }
            >
              <option value="standard">Off · standard events</option>
              <option value="detailed">On · developer detail</option>
            </select>
            <p className="footnote">
              Developer detail enables bounded diagnostic capture in the local runtime.
            </p>
            <div className="safety-note">
              <Icon name="checkCircle" size={16} />
              <p>
                Risky actions <strong>always require your approval</strong>. This cannot be
                disabled here.
              </p>
            </div>
            {!valid && (
              <p className="inline-error" role="alert">
                Model, checkpoint and endpoint values must not be empty.
              </p>
            )}
            <button
              className="button button-primary settings-save"
              disabled={disabled || !changed || !valid}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : "Save settings"}
            </button>
            {active && (
              <p className="footnote">Finish or stop this task before changing settings.</p>
            )}
            {notice && (
              <p className="footnote" role="status">
                {notice}
              </p>
            )}
          </>
        )}
      </section>
      <section className="settings-group" aria-labelledby="credentials-heading">
        <div className="setting-heading">
          <h2 id="credentials-heading">OpenAI API key</h2>
          <span className="text-state">
            {snapshot.openAiKeyConfigured ? "Configured" : "Not configured"}
          </span>
        </div>
        <form onSubmit={(event) => void saveKey(event)}>
          <label htmlFor="openai-key">
            {snapshot.openAiKeyConfigured ? "Replace API key" : "API key"}
          </label>
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
              className="button button-secondary"
              type="submit"
              disabled={!snapshot.protocolReady || busy || !apiKey.trim()}
            >
              Save securely
            </button>
            {snapshot.openAiKeyConfigured && (
              <button
                className="text-button"
                type="button"
                disabled={busy || !snapshot.protocolReady}
                onClick={() => void onDispatch({ type: "credentials.clear" })}
              >
                Remove key
              </button>
            )}
          </div>
        </form>
        <p className="footnote">
          Stored by the local runtime in your operating system keyring. The extension never
          saves or displays your key.
        </p>
      </section>
      <section className="settings-group" aria-labelledby="connection-heading">
        <div className="setting-heading">
          <h2 id="connection-heading">Connection</h2>
          <span className="text-state">
            {snapshot.protocolReady ? "Connected" : "Disconnected"}
          </span>
        </div>
        <p className="footnote">BROWSKI uses the local runtime on this computer.</p>
        <button
          className="button button-secondary"
          disabled={busy || snapshot.host === "connecting"}
          onClick={() =>
            void onDispatch({
              type: snapshot.host === "connected" ? "host.disconnect" : "host.connect",
            })
          }
        >
          {snapshot.host === "connected" ? "Disconnect runtime" : "Connect runtime"}
        </button>
        <label className="setting-toggle">
          <input
            type="checkbox"
            checked={autoConnect}
            onChange={(event) => void onSaveAutoConnect(event.target.checked)}
          />
          <span>Connect automatically when the panel opens</span>
        </label>
        {snapshot.hostError && (
          <p className="inline-error" role="alert">
            {snapshot.hostError}
          </p>
        )}
      </section>
      <details className="settings-group advanced-settings">
        <summary>Advanced</summary>
        {draft && (
          <>
            <label htmlFor="advanced-engine">Compatibility engine</label>
            <select
              id="advanced-engine"
              value={draft.engine ?? "legacy"}
              disabled={disabled}
              onChange={(event) =>
                update({ engine: event.target.value as RuntimeSettingsUpdate["engine"] })
              }
            >
              <option value="general">General</option>
              <option value="fast">Fast</option>
              <option value="legacy">Legacy · explicit attachment</option>
            </select>
            {draft.engine === "fast" && (
              <>
                <label htmlFor="runtime-fast-provider">Fast provider</label>
                <select
                  id="runtime-fast-provider"
                  value={draft.fastProvider ?? "laya"}
                  disabled={disabled}
                  onChange={(event) =>
                    update({
                      fastProvider: event.target
                        .value as RuntimeSettingsUpdate["fastProvider"],
                    })
                  }
                >
                  <option value="laya">Laya · local</option>
                  <option value="jev">Jev · hosted</option>
                </select>
              </>
            )}
            <label htmlFor="runtime-laya-checkpoint">Local Laya checkpoint</label>
            <input
              id="runtime-laya-checkpoint"
              value={draft.layaCheckpoint ?? ""}
              maxLength={1000}
              disabled={disabled}
              onChange={(event) => update({ layaCheckpoint: event.target.value })}
            />
            {draft.fastProvider === "jev" && (
              <>
                <label htmlFor="runtime-jev-endpoint">Jev endpoint</label>
                <input
                  id="runtime-jev-endpoint"
                  type="url"
                  value={draft.jevEndpoint ?? ""}
                  maxLength={1000}
                  disabled={disabled}
                  onChange={(event) => update({ jevEndpoint: event.target.value })}
                />
                <p className="footnote">
                  Jev needs paid usage permission and TYPESAFE_API_KEY configured in the
                  runtime environment.
                </p>
              </>
            )}
            {(draft.engine ?? "legacy") === "legacy" && (
              <>
                <label htmlFor="runtime-effort">Default reasoning effort</label>
                <select
                  id="runtime-effort"
                  value={draft.effort}
                  disabled={disabled}
                  onChange={(event) =>
                    update({
                      effort: event.target.value as RuntimeSettingsUpdate["effort"],
                    })
                  }
                >
                  <option value="none">None</option>
                  <option value="low">Low</option>
                </select>
                <label htmlFor="runtime-laya">Laya comparison</label>
                <select
                  id="runtime-laya"
                  value={draft.layaMode}
                  disabled={disabled}
                  onChange={(event) =>
                    update({
                      layaMode: event.target.value as RuntimeSettingsUpdate["layaMode"],
                    })
                  }
                >
                  <option value="disabled">Disabled</option>
                  <option value="shadow">Shadow only</option>
                </select>
              </>
            )}
          </>
        )}
        {(settings?.engine ?? "general") === "legacy" && (
          <TabAttachment snapshot={snapshot} busy={busy} onDispatch={onDispatch} />
        )}
        <p className="footnote">
          General uses your current tab and leaves your tabs open. Fast uses an isolated
          task browser. Legacy uses an explicitly attached tab through Chrome’s debugger
          bridge.
        </p>
      </details>
      <section className="settings-group about-settings" aria-labelledby="about-heading">
        <h2 id="about-heading">About BROWSKI</h2>
        <dl className="settings-list">
          <div>
            <dt>Version</dt>
            <dd>{chrome.runtime.getManifest().version}</dd>
          </div>
          <div>
            <dt>Protocol</dt>
            <dd>{PROTOCOL_VERSION}</dd>
          </div>
          <div>
            <dt>Transport</dt>
            <dd>Local Native Messaging</dd>
          </div>
        </dl>
      </section>
      {snapshot.settingsError && (
        <p className="inline-error" role="alert">
          {snapshot.settingsError}
        </p>
      )}
    </div>
  );
}
