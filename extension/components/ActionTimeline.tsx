import { useState } from "react";
import type { TimelineEvent, RuntimeStatus } from "../src/protocol";
import { Icon, type IconName } from "./Icon";
import { formatDuration, pageHost } from "./display";

const VISIBLE_STEPS = 6;

function statusTitle(status: RuntimeStatus | undefined, host: string): string {
  switch (status) {
    case "running":
      return host ? `Working on ${host}…` : "Working in your browser…";
    case "paused":
      return "Paused. Ready when you are.";
    case "awaiting_approval":
      return "Waiting for your approval";
    case "completed":
      return "Finished browsing";
    case "partially_completed":
      return "Finished with an incomplete outcome";
    case "failed":
      return "The task ran into a problem";
    case "blocked":
      return "The task needs your attention";
    case "stopped":
    case "cancelled":
      return "Task stopped";
    default:
      return "Activity";
  }
}

export function ActionTimeline({
  events,
  status,
  busy = false,
  onControl,
}: {
  events: TimelineEvent[];
  status?: RuntimeStatus;
  busy?: boolean;
  onControl?: (control: "pause" | "resume") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const ordered = [...events].sort((a, b) => a.sequence - b.sequence);
  const visible = expanded ? ordered : ordered.slice(-VISIBLE_STEPS);
  const host = pageHost([...ordered].reverse().find((event) => event.pageUrl)?.pageUrl);
  const live = status === "running";
  const started = ordered.at(0)?.createdAt;
  const elapsed = started ? Date.now() - Date.parse(started) : 0;

  return (
    <section className={`run-block ${live ? "is-live" : ""}`} aria-label="Agent activity">
      <div className="run-heading">
        <span className={`agent-avatar ${live ? "is-working" : ""}`}>
          <Icon name="brand" size={16} />
        </span>
        <p role="status">{statusTitle(status, host)}</p>
        {onControl && (status === "running" || status === "paused") && (
          <button
            className="icon-button"
            disabled={busy}
            aria-label={status === "paused" ? "Resume task" : "Pause task"}
            title={status === "paused" ? "Resume task" : "Pause task"}
            onClick={() => onControl(status === "paused" ? "resume" : "pause")}
          >
            <Icon name={status === "paused" ? "play" : "pause"} size={15} />
          </button>
        )}
      </div>
      {ordered.length > VISIBLE_STEPS && (
        <button
          className="steps-toggle text-button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show recent steps" : `Show all ${ordered.length} steps`}
        </button>
      )}
      {visible.length > 0 ? (
        <ol className="timeline-list" aria-label="Runtime activity">
          {visible.map((event, index) => (
            <TimelineRow
              key={event.eventId}
              event={event}
              number={ordered.indexOf(event) + 1}
              live={live && index === visible.length - 1}
            />
          ))}
        </ol>
      ) : (
        <p className="run-starting">Feeding the first line…</p>
      )}
      {live && ordered.length > 0 && Number.isFinite(elapsed) && (
        <p className="run-meter" aria-label="Progress so far">
          {ordered.length} {ordered.length === 1 ? "line" : "lines"} ·{" "}
          {formatDuration(Math.max(0, elapsed))}
        </p>
      )}
    </section>
  );
}

function actionIcon(event: TimelineEvent): IconName {
  const label = event.label.toLowerCase();
  if (event.type === "DecisionMade" || event.type === "DecisionStarted") return "thought";
  if (/\bsearch/.test(label)) return "search";
  if (/\b(typ|input|fill|enter)/.test(label)) return "type";
  if (/\b(click|press|select)/.test(label)) return "click";
  if (/\bscroll/.test(label)) return "scroll";
  if (/\btab/.test(label)) return "tab";
  if (/\b(wait|load)/.test(label)) return "wait";
  if (/\b(read|observ|extract)/.test(label)) return "read";
  if (/\b(open|navigat)/.test(label)) return "globe";
  if (/\b(page changed|looking again)/.test(label)) return "refresh";
  if (event.type?.includes("Verification") || event.type === "RunCompleted") return "check";
  if (event.status === "failed") return "info";
  return "globe";
}

function TimelineRow({
  event,
  number,
  live,
}: {
  event: TimelineEvent;
  number: number;
  live: boolean;
}) {
  const date = new Date(event.createdAt);
  const time = Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const host = pageHost(event.pageUrl);
  return (
    <li
      className={`timeline-item event-${event.status} ${live ? "is-live" : ""}`}
      aria-current={live ? "step" : undefined}
    >
      <span className="step-number" aria-hidden="true">
        {String(number).padStart(2, "0")}
      </span>
      <span className="timeline-icon">
        <Icon name={actionIcon(event)} size={15} />
      </span>
      <div className="timeline-copy">
        {event.detail ? (
          <details className="step-detail">
            <summary>
              <span>{event.label}</span>
              <Icon name="chevron" size={12} />
            </summary>
            <p>{event.detail}</p>
          </details>
        ) : (
          <p className="step-label">{event.label}</p>
        )}
        <div className="timeline-meta">
          {host && <span className="step-host">{host}</span>}
          <time dateTime={event.createdAt}>{time}</time>
          {event.status === "failed" && <span className="text-danger">Failed</span>}
          {event.status === "running" && <span>In progress</span>}
        </div>
        {event.failure && <p className="inline-error">{event.failure.safeMessage}</p>}
      </div>
    </li>
  );
}
