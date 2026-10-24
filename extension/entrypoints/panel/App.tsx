import { useEffect, useRef, useState } from "react";
import { ActionTimeline } from "../../components/ActionTimeline";
import { ConfirmationCard } from "../../components/ConfirmationCard";
import { EmptyState } from "../../components/EmptyState";
import { Icon } from "../../components/Icon";
import { ResultCard } from "../../components/ResultCard";
import { SettingsPanel } from "../../components/SettingsPanel";
import { TaskComposer } from "../../components/TaskComposer";
import type {
  PendingApproval,
  RuntimeSettingsUpdate,
  TaskResult,
} from "../../src/protocol";
import { canStartTask } from "../../src/run-controls";
import { useRuntimeConnection, type DispatchResult } from "./useRuntimeConnection";

type Receipt = { result: TaskResult; task: string };

function App() {
  const { snapshot, panelError, busy, autoConnect, dispatch, saveAutoConnect } =
    useRuntimeConnection();
  const [view, setView] = useState<"thread" | "settings" | "history">("thread");
  const [draft, setDraft] = useState({ id: 0, text: "" });
  const [dismissedRun, setDismissedRun] = useState<string | null>(null);
  const [history, setHistory] = useState<Receipt[]>([]);
  const [selectedReceipt, setSelectedReceipt] = useState<Receipt | null>(null);
  const scrollArea = useRef<HTMLDivElement>(null);
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const submittedTask = useRef<string | null>(null);
  const session = snapshot.session;
  const active = Boolean(session && !canStartTask(session.status));
  const engine = snapshot.runtimeSettings?.engine ?? "general";
  const runKey = session?.runId ?? session?.updatedAt ?? "";
  const showRun = Boolean(
    (session?.taskLabel || active || snapshot.pendingApproval) &&
    (active || dismissedRun !== runKey),
  );
  const result = snapshot.lastResult;
  const currentResult =
    result &&
    result.sessionId === session?.sessionId &&
    (!session.runId || result.runId === session.runId) &&
    !active
      ? result
      : undefined;
  const events = snapshot.events.filter(
    (event) => !session?.runId || event.runId === session.runId,
  );

  useEffect(() => {
    if (!result) return;
    setHistory((items) => {
      const key = result.runId ?? result.finishedAt;
      if (items.some((item) => (item.result.runId ?? item.result.finishedAt) === key))
        return items;
      return [
        { result, task: submittedTask.current ?? session?.taskLabel ?? "Browser task" },
        ...items,
      ].slice(0, 12);
    });
  }, [result, session?.taskLabel]);

  useEffect(() => {
    if (snapshot.pendingApproval) {
      setView("thread");
      setSelectedReceipt(null);
    }
  }, [snapshot.pendingApproval]);

  useEffect(() => {
    const element = scrollArea.current;
    if (element && element.scrollHeight - element.scrollTop - element.clientHeight < 240) {
      element.scrollTo?.({ top: element.scrollHeight, behavior: "instant" });
    }
  }, [events.length, currentResult, snapshot.pendingApproval]);

  useEffect(() => {
    if (view !== "thread") pageHeading.current?.focus();
  }, [view]);

  function fillComposer(text: string): void {
    setSelectedReceipt(null);
    setView("thread");
    setDraft((current) => ({ id: current.id + 1, text }));
    requestAnimationFrame(() => document.getElementById("task-input")?.focus());
  }

  function newTask(): void {
    setDismissedRun(runKey);
    fillComposer("");
  }

  async function dispatchTask(message: Record<string, unknown>): Promise<DispatchResult> {
    if (message.type !== "task.submit" || typeof message.task !== "string")
      return dispatch(message);
    const previousTask = submittedTask.current;
    submittedTask.current = message.task;
    const response = await dispatch(message);
    if (response.error) submittedTask.current = previousTask;
    return response;
  }

  async function respondToApproval(
    approval: PendingApproval,
    approved: boolean,
  ): Promise<void> {
    const response = await dispatch({
      type: "approval.respond",
      approvalId: approval.approvalId,
      approved,
    });
    if (response.error) throw new Error(response.error);
  }

  async function saveRuntimeSettings(settings: RuntimeSettingsUpdate): Promise<void> {
    const response = await dispatch({ type: "settings.update", ...settings });
    if (response.error) throw new Error(response.error);
  }

  let statusLabel = "Ready";
  if (!snapshot.protocolReady)
    statusLabel = snapshot.host === "connecting" ? "Connecting" : "Offline";
  else if (active)
    statusLabel =
      session?.status === "running"
        ? "Working"
        : session?.status === "paused"
          ? "Paused"
          : "Approval";

  let headState = "idle";
  if (!snapshot.protocolReady) headState = "offline";
  else if (active) headState = session?.status ?? "running";

  return (
    <main className="panel-shell">
      <header className="panel-header" data-state={headState}>
        <div className="brand-lockup">
          <span className="brand-mark">
            <Icon name="brand" size={19} />
          </span>
          <h1>BROWSKI</h1>
        </div>
        <span className={`status-pill ${active ? "status-active" : ""}`}>
          <span className="state-dot" />
          {statusLabel}
        </span>
        <nav className="header-actions" aria-label="Panel navigation">
          <button
            className="icon-button"
            aria-label="New task"
            title="New task"
            disabled={active}
            onClick={newTask}
          >
            <Icon name="plus" />
          </button>
          <button
            className="icon-button"
            aria-label="Task history"
            title="Task history"
            aria-pressed={view === "history"}
            onClick={() => setView(view === "history" ? "thread" : "history")}
          >
            <Icon name="history" />
          </button>
          <button
            className="icon-button"
            aria-label="Settings"
            title="Settings"
            aria-pressed={view === "settings"}
            onClick={() => setView(view === "settings" ? "thread" : "settings")}
          >
            <Icon name="settings" />
          </button>
        </nav>
        <div className="print-head" aria-hidden="true">
          <span />
        </div>
      </header>
      {view !== "thread" && (
        <div className="page-heading">
          <button
            className="icon-button"
            aria-label="Back to task"
            onClick={() => setView("thread")}
          >
            <Icon name="back" />
          </button>
          <h2 ref={pageHeading} tabIndex={-1}>
            {view === "settings" ? "Settings" : "Task history"}
          </h2>
        </div>
      )}
      <div ref={scrollArea} className="panel-scroll-area">
        <div hidden={view !== "thread"} className="thread-view">
          {selectedReceipt && !active ? (
            <div className="tape">
              <article className="user-message" aria-label="Your task">
                <p>{selectedReceipt.task}</p>
              </article>
              <ResultCard
                key={selectedReceipt.result.finishedAt}
                result={selectedReceipt.result}
                disabled={active}
                onRunAgain={() => fillComposer(selectedReceipt.task)}
              />
            </div>
          ) : showRun ? (
            <div className="tape">
              <article className="user-message" aria-label="Your task">
                <p>{session?.taskLabel}</p>
              </article>
              <ActionTimeline
                events={events}
                status={session?.status}
                busy={busy}
                onControl={(control) => void dispatch({ type: "task.control", control })}
              />
              {snapshot.pendingApproval && (
                <ConfirmationCard
                  key={snapshot.pendingApproval.approvalId}
                  approval={snapshot.pendingApproval}
                  pageUrl={[...events].reverse().find((event) => event.pageUrl)?.pageUrl}
                  busy={busy}
                  onRespond={respondToApproval}
                />
              )}
              {currentResult && (
                <ResultCard
                  key={currentResult.finishedAt}
                  result={currentResult}
                  disabled={busy}
                  onRunAgain={() =>
                    fillComposer(submittedTask.current ?? session?.taskLabel ?? "")
                  }
                />
              )}
            </div>
          ) : (
            <EmptyState
              snapshot={snapshot}
              busy={busy}
              onExample={fillComposer}
              onSettings={() => setView("settings")}
              onConnect={() => void dispatch({ type: "host.connect" })}
            />
          )}
          {!snapshot.protocolReady && showRun && (
            <div className="thread-notice" role="status">
              <p>The runtime disconnected. Reconnect to check this task’s status.</p>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void dispatch({ type: "host.connect" })}
              >
                Retry connection
              </button>
            </div>
          )}
        </div>
        {view === "settings" && (
          <SettingsPanel
            snapshot={snapshot}
            busy={busy}
            autoConnect={autoConnect}
            onDispatch={dispatch}
            onSaveAutoConnect={saveAutoConnect}
            onSaveRuntimeSettings={saveRuntimeSettings}
          />
        )}
        {view === "history" && (
          <section className="history-list" aria-label="Recent tasks">
            <p className="footnote">
              Recent results from this panel session. Closing the panel clears this list.
            </p>
            {history.length === 0 ? (
              <div className="history-empty">
                <Icon name="history" size={28} />
                <h3>No tasks yet</h3>
                <p>Your finished tasks will appear here.</p>
              </div>
            ) : (
              history.map((receipt) => (
                <button
                  key={receipt.result.runId ?? receipt.result.finishedAt}
                  className="history-item"
                  onClick={() => {
                    setSelectedReceipt(receipt);
                    setView("thread");
                  }}
                >
                  <Icon
                    name={
                      (receipt.result.verdict?.verified ??
                      receipt.result.outcome === "verified_success")
                        ? "checkCircle"
                        : "info"
                    }
                    size={18}
                  />
                  <span>
                    <strong>{receipt.task}</strong>
                    <small>
                      {new Date(receipt.result.finishedAt).toLocaleString([], {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </small>
                  </span>
                  <Icon name="chevron" size={14} />
                </button>
              ))
            )}
          </section>
        )}
        {panelError && (
          <p className="inline-error panel-error" role="alert">
            {panelError}
          </p>
        )}
      </div>
      <div hidden={view !== "thread"} className="composer-dock">
        <TaskComposer
          key={draft.id}
          initialTask={draft.text}
          protocolReady={
            snapshot.protocolReady &&
            (engine !== "legacy"
              ? true
              : Boolean(snapshot.attachment && snapshot.attachment.state !== "error"))
          }
          engine={engine}
          fastProvider={snapshot.runtimeSettings?.fastProvider ?? "laya"}
          model={snapshot.runtimeSettings?.textModel ?? "gpt-6-luna"}
          onSettings={() => setView("settings")}
          session={session}
          events={snapshot.events}
          busy={busy}
          onDispatch={dispatchTask}
        />
      </div>
    </main>
  );
}

export default App;
