import { ActionTimeline } from "../../components/ActionTimeline";
import { ConfirmationCard } from "../../components/ConfirmationCard";
import { ConnectionStatus } from "../../components/ConnectionStatus";
import { SettingsPanel } from "../../components/SettingsPanel";
import { TabAttachment } from "../../components/TabAttachment";
import { TaskComposer } from "../../components/TaskComposer";
import {
  PROTOCOL_VERSION,
  type PendingApproval,
  type RuntimeSettingsUpdate,
} from "../../src/protocol";
import { useRuntimeConnection } from "./useRuntimeConnection";

function App() {
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
      <ConnectionStatus snapshot={snapshot} busy={busy} onDispatch={dispatch} />
      <TabAttachment snapshot={snapshot} busy={busy} onDispatch={dispatch} />
      {snapshot.pendingApproval && (
        <ConfirmationCard
          approval={snapshot.pendingApproval}
          busy={busy}
          onRespond={respondToApproval}
        />
      )}
      <TaskComposer
        protocolReady={snapshot.protocolReady}
        session={snapshot.session}
        events={snapshot.events}
        busy={busy}
        onDispatch={dispatch}
      />
      {panelError && (
        <p className="inline-error panel-error" role="alert">
          {panelError}
        </p>
      )}
      <ActionTimeline events={snapshot.events} />
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
        <span>v0.1 · protocol {PROTOCOL_VERSION}</span>
      </footer>
    </main>
  );
}

export default App;
