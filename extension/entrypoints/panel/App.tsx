import { ActionTimeline } from "../../components/ActionTimeline";
import { ConfirmationCard } from "../../components/ConfirmationCard";
import { ConnectionStatus } from "../../components/ConnectionStatus";
import { SettingsPanel } from "../../components/SettingsPanel";
import { TabAttachment } from "../../components/TabAttachment";
import { EngineControls } from "../../components/EngineControls";
import { TaskComposer } from "../../components/TaskComposer";
import {
  PROTOCOL_VERSION,
  type PendingApproval,
  type RuntimeSettingsUpdate,
} from "../../src/protocol";
import { useRuntimeConnection } from "./useRuntimeConnection";

function App() {
  const extensionVersion = chrome.runtime.getManifest().version;
  const { snapshot, panelError, busy, autoConnect, dispatch, saveAutoConnect } =
    useRuntimeConnection();

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

  async function saveRuntimeSettings(settings: RuntimeSettingsUpdate): Promise<void> {
    await dispatch({ type: "settings.update", ...settings });
  }

  return (
    <main className="panel-shell">
      <header className="panel-header">
        <ConnectionStatus snapshot={snapshot} busy={busy} onDispatch={dispatch} />
        {(snapshot.runtimeSettings?.engine ?? "legacy") === "legacy" && (
          <TabAttachment snapshot={snapshot} busy={busy} onDispatch={dispatch} />
        )}
      </header>
      <div className="panel-scroll-area">
        {snapshot.pendingApproval && (
          <ConfirmationCard
            approval={snapshot.pendingApproval}
            busy={busy}
            onRespond={respondToApproval}
          />
        )}
        {snapshot.session?.taskLabel && (
          <section className="task-context" aria-label="Current task">
            <span className="task-context-marker" aria-hidden="true" />
            <p>{snapshot.session.taskLabel}</p>
          </section>
        )}
        <ActionTimeline events={snapshot.events} status={snapshot.session?.status} />
        {panelError && (
          <p className="inline-error panel-error" role="alert">
            {panelError}
          </p>
        )}
        <SettingsPanel
          snapshot={snapshot}
          busy={busy}
          autoConnect={autoConnect}
          onDispatch={dispatch}
          onSaveAutoConnect={saveAutoConnect}
          onSaveRuntimeSettings={saveRuntimeSettings}
        />
        <footer className="panel-footer">
          <span>Local companion</span>
          <span>
            v{extensionVersion} · protocol {PROTOCOL_VERSION}
          </span>
        </footer>
      </div>
      <EngineControls
        settings={snapshot.runtimeSettings}
        disabled={
          !snapshot.protocolReady ||
          busy ||
          ["running", "paused", "awaiting_approval"].includes(
            snapshot.session?.status ?? "",
          )
        }
        onSave={saveRuntimeSettings}
      />
      <TaskComposer
        protocolReady={
          snapshot.protocolReady &&
          (snapshot.runtimeSettings?.engine && snapshot.runtimeSettings.engine !== "legacy"
            ? true
            : Boolean(snapshot.attachment && snapshot.attachment.state !== "error"))
        }
        engine={snapshot.runtimeSettings?.engine ?? "legacy"}
        session={snapshot.session}
        events={snapshot.events}
        busy={busy}
        onDispatch={dispatch}
      />
    </main>
  );
}

export default App;
