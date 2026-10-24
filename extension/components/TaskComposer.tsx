import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { RuntimeStatus, TimelineEvent } from "../src/protocol";
import { MAX_TASK_LENGTH } from "../src/composer-context";
import { canStartTask, type RunControl } from "../src/run-controls";
import { CommandMenu } from "./CommandMenu";
import { Icon } from "./Icon";
import { useComposer } from "./useComposer";
import { TaskOutcomeFields, type OutcomeDraft } from "./TaskOutcomeFields";

export function TaskComposer({
  protocolReady,
  session,
  busy,
  onDispatch,
  engine = "legacy",
  model = "gpt-6-luna",
  fastProvider = "laya",
  initialTask = "",
  onSettings,
}: {
  protocolReady: boolean;
  session: { status: RuntimeStatus; runId?: string } | null;
  engine?: "fast" | "general" | "legacy";
  events: TimelineEvent[];
  model?: string;
  fastProvider?: "laya" | "jev";
  initialTask?: string;
  onSettings?: () => void;
  busy: boolean;
  onDispatch: (message: Record<string, unknown>) => Promise<{ error?: string }>;
}) {
  function controlTask(control: RunControl): Promise<void> {
    return onDispatch({ type: "task.control", control }).then(() => undefined);
  }
  const composer = useComposer({
    status: session?.status,
    onControl: controlTask,
    initialTask,
  });
  const container = useRef<HTMLElement>(null);
  const [outcome, setOutcome] = useState<OutcomeDraft>({
    startUrl: "",
    url: "",
    heading: "",
  });
  const [outcomeError, setOutcomeError] = useState<string | null>(null);
  const { setTrigger } = composer;
  const canSubmit = Boolean(protocolReady && session && canStartTask(session.status));
  const overLimit = composer.serializedTask.length > MAX_TASK_LENGTH;
  const locked = busy || composer.reading;
  const menuOpen = Boolean(composer.trigger);
  const active = Boolean(session && !canStartTask(session.status));

  useEffect(() => {
    const textarea = composer.input.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(180, Math.max(56, textarea.scrollHeight))}px`;
  }, [composer.task, composer.input]);

  useEffect(() => {
    function closeOutside(event: PointerEvent): void {
      if (event.target instanceof Node && !container.current?.contains(event.target)) {
        setTrigger(null);
      }
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [setTrigger]);

  async function submitTask(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault();
    if (!canSubmit || locked || overLimit || !composer.task.trim()) return;
    composer.setTrigger(null);
    if (
      engine !== "legacy" &&
      Boolean(outcome.url.trim()) !== Boolean(outcome.heading.trim())
    ) {
      setOutcomeError("Enter both the expected URL and heading, or leave both empty.");
      return;
    }
    setOutcomeError(null);
    const detectedUrl = composer.serializedTask
      .match(/https?:\/\/[^\s"'<>]+/)?.[0]
      ?.replace(/[),.;]+$/, "");
    const startUrl = outcome.startUrl.trim() || detectedUrl;
    const result = await onDispatch({
      type: "task.submit",
      task: composer.serializedTask,
      ...(engine !== "legacy" && startUrl ? { startUrl } : {}),
      ...(engine !== "legacy" && outcome.url.trim() && outcome.heading.trim()
        ? {
            verification: { url: outcome.url.trim(), heading: outcome.heading.trim() },
          }
        : {}),
    });
    if (!result.error) composer.clear();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape") {
      composer.setTrigger(null);
      return;
    }
    if (menuOpen && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      const length = composer.options.length;
      if (length) {
        const direction = event.key === "ArrowDown" ? 1 : -1;
        composer.setSelected((composer.selected + direction + length) % length);
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (menuOpen) {
        const option = composer.options[composer.selected];
        if (option) composer.choose(option);
      } else {
        void submitTask();
      }
    }
  }

  return (
    <section
      ref={container}
      className="task-section"
      aria-label="Task composer"
      onDragOver={(event) => {
        if (!locked) event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        if (!locked) void composer.attachFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <form onSubmit={(event) => void submitTask(event)} className="composer-form">
        {engine !== "legacy" && (
          <TaskOutcomeFields
            draft={outcome}
            disabled={locked || !canSubmit}
            onChange={setOutcome}
          />
        )}
        {composer.trigger && (
          <CommandMenu
            kind={composer.trigger.kind}
            options={composer.options}
            selected={composer.selected}
            onSelect={composer.choose}
            onHover={composer.setSelected}
          />
        )}
        <div className={`composer-box ${overLimit ? "composer-invalid" : ""}`}>
          {composer.context.length > 0 && (
            <ul className="context-list" aria-label="Attached references">
              {composer.context.map((item) => (
                <li key={item.id} title={item.kind === "file" ? item.label : item.content}>
                  <Icon
                    name={
                      item.kind === "file" ? "file" : item.kind === "tab" ? "tab" : "link"
                    }
                    size={14}
                  />
                  <span>{item.label}</span>
                  <button
                    type="button"
                    disabled={locked}
                    aria-label={`Remove ${item.label}`}
                    onClick={() =>
                      composer.setContext(
                        composer.context.filter((entry) => entry.id !== item.id),
                      )
                    }
                  >
                    <Icon name="close" size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <label htmlFor="task-input" className="composer-label">
            Ask BROWSKI
          </label>
          <textarea
            ref={composer.input}
            id="task-input"
            aria-label="Task instruction"
            aria-describedby="composer-hint composer-feedback"
            aria-expanded={menuOpen}
            aria-controls={menuOpen ? "composer-options" : undefined}
            aria-activedescendant={
              menuOpen && composer.options[composer.selected]
                ? `composer-option-${composer.selected}`
                : undefined
            }
            aria-autocomplete="list"
            value={composer.task}
            onChange={(event) =>
              composer.updateTask(event.target.value, event.target.selectionStart)
            }
            onKeyDown={onKeyDown}
            onClick={(event) =>
              composer.updateTask(composer.task, event.currentTarget.selectionStart)
            }
            placeholder="Give your browser a task…"
            maxLength={MAX_TASK_LENGTH}
            disabled={locked}
            rows={2}
          />
          <div className="composer-toolbar">
            <div className="composer-tools">
              <button
                type="button"
                className="icon-button"
                title="Attach a text file"
                aria-label="Attach a text file"
                disabled={locked}
                onClick={() => composer.fileInput.current?.click()}
              >
                <Icon name="attach" />
              </button>
              <button
                type="button"
                className="icon-button"
                title="Mention a tab or link (@)"
                aria-label="Mention a tab or link"
                disabled={locked}
                onClick={() => composer.insertTrigger("@")}
              >
                <Icon name="at" />
              </button>
              <button
                type="button"
                className="icon-button"
                title="Shortcuts (/)"
                aria-label="Open shortcuts"
                disabled={locked}
                onClick={() => composer.insertTrigger("/")}
              >
                <Icon name="slash" />
              </button>
            </div>
            <div className="composer-send-group">
              <span className={`character-count ${overLimit ? "text-danger" : ""}`}>
                {composer.serializedTask.length.toLocaleString()}/4,000
              </span>
              {active ? (
                <button
                  type="button"
                  className="send-button stop-button"
                  aria-label="Stop task"
                  title="Stop task"
                  disabled={busy}
                  onClick={() => void controlTask("stop")}
                >
                  <Icon name="stop" size={18} />
                </button>
              ) : (
                <button
                  type="submit"
                  className="send-button"
                  aria-label="Send task"
                  title="Send task (Enter)"
                  disabled={!canSubmit || locked || overLimit || !composer.task.trim()}
                >
                  <Icon name="arrow" size={20} />
                </button>
              )}
            </div>
          </div>
        </div>
        <input
          ref={composer.fileInput}
          type="file"
          multiple
          accept=".txt,.md,.csv,.json"
          className="visually-hidden"
          aria-label="Attach reference files"
          tabIndex={-1}
          onChange={(event) =>
            void composer.attachFiles(Array.from(event.target.files ?? []))
          }
        />
      </form>
      <div id="composer-feedback" aria-live="polite">
        {outcomeError && (
          <p className="inline-error" role="alert">
            {outcomeError}
          </p>
        )}
        {composer.error && (
          <p className="inline-error" role="alert">
            {composer.error}
          </p>
        )}
        {overLimit && !composer.error && (
          <p className="inline-error" role="alert">
            Task and references must fit within 4,000 characters.
          </p>
        )}
        {composer.reading && <p className="footnote">Reading text files…</p>}
      </div>
      <div className="composer-bottom">
        <button
          className="engine-chip"
          type="button"
          onClick={onSettings}
          disabled={!onSettings}
          aria-label="Engine settings"
        >
          <span className="engine-dot" />
          {engine === "general"
            ? `General · ${model}`
            : engine === "fast"
              ? `Fast · ${fastProvider === "jev" ? "Jev" : "Laya"}`
              : "Legacy"}
          <Icon name="chevron" size={12} />
        </button>
        <p id="composer-hint" className="composer-hint">
          {!protocolReady || !session
            ? engine === "legacy"
              ? "Connect the runtime and attach a tab to send."
              : "Connect the runtime to send."
            : !canSubmit
              ? "Draft the next task while this runs"
              : "Shift+Enter for a new line"}
        </p>
      </div>
    </section>
  );
}
