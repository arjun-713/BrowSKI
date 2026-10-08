import { useState, type FormEvent } from "react";
import type { RuntimeStatus, TimelineEvent } from "../src/protocol";
import { canStartTask, type RunControl } from "../src/run-controls";
import { RunControls } from "./RunControls";

export function TaskComposer({
  protocolReady,
  session,
  events,
  busy,
  onDispatch,
}: {
  protocolReady: boolean;
  session: { status: RuntimeStatus } | null;
  events: TimelineEvent[];
  busy: boolean;
  onDispatch: (message: Record<string, unknown>) => Promise<{ error?: string }>;
}) {
  const [task, setTask] = useState("");
  const canSubmitTask = Boolean(protocolReady && session && canStartTask(session.status));

  async function submitTask(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canSubmitTask || busy || task.trim().length === 0) {
      return;
    }

    const result = await onDispatch({ type: "task.submit", task });
    if (!result.error) {
      setTask("");
    }
  }

  function controlTask(control: RunControl): Promise<void> {
    return onDispatch({ type: "task.control", control }).then(() => undefined);
  }

  return (
    <section className="task-section" aria-labelledby="task-heading">
      <div className="section-heading compact-heading">
        <div>
          <p className="eyebrow">TASK</p>
          <h2 id="task-heading">New task</h2>
        </div>
        {session && <StatusTag status={session.status} />}
      </div>
      <form onSubmit={(event) => void submitTask(event)}>
        <label htmlFor="task-input">Task instruction</label>
        <textarea
          id="task-input"
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder="Find five AI internships in Bengaluru and open each in a tab."
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
        Follow the action timeline below. Consequential actions wait for your approval.
      </p>
      {session && events.some((event) => event.runId) && (
        <RunControls status={session.status} busy={busy} onControl={controlTask} />
      )}
    </section>
  );
}

function StatusTag({ status }: { status: RuntimeStatus }) {
  return <span className={`status-tag status-${status}`}>{formatStatus(status)}</span>;
}

function formatStatus(status: RuntimeStatus): string {
  return status.replaceAll("_", " ");
}
