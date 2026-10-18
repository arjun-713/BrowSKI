import type { TimelineEvent, RuntimeStatus } from "../src/protocol";
import { Icon, type IconName } from "./Icon";

export function ActionTimeline({
  events,
  status,
}: {
  events: TimelineEvent[];
  status?: RuntimeStatus;
}) {
  const ordered = [...events].sort((a, b) => b.sequence - a.sequence);
  const running = status === "running";

  if (ordered.length === 0) {
    return (
      <section className="welcome" aria-labelledby="welcome-heading">
        <span className="welcome-mark" aria-hidden="true">
          <Icon name="tab" size={30} />
        </span>
        <h2 id="welcome-heading">
          What can I do
          <br />
          on this page?
        </h2>
        <p>Give BROWSKI a task. Follow each action as it works in your browser.</p>
        <ul className="welcome-hints">
          <li>
            <Icon name="at" />
            <span>Mention a tab or paste a link</span>
          </li>
          <li>
            <Icon name="slash" />
            <span>Find a shortcut with slash commands</span>
          </li>
          <li>
            <Icon name="attach" />
            <span>Attach a text file for context</span>
          </li>
        </ul>
      </section>
    );
  }

  return (
    <section className="timeline-section" aria-labelledby="timeline-heading">
      <div className="section-heading">
        <h2 id="timeline-heading">Activity</h2>
        <span className={`activity-state ${running ? "is-working" : ""}`} role="status">
          {running && <span className="working-dot" aria-hidden="true" />}
          {status?.replaceAll("_", " ") ?? `${ordered.length} events`}
        </span>
      </div>
      <p className="timeline-note">Decisions, actions & verified results</p>
      <ol className="timeline-list" aria-label="Runtime activity">
        {ordered.map((event) => (
          <TimelineRow key={event.eventId} event={event} />
        ))}
      </ol>
    </section>
  );
}

function eventPresentation(event: TimelineEvent): { icon: IconName; label: string } {
  if (event.type === "DecisionMade") return { icon: "thought", label: "Decision summary" };
  if (event.type === "VerificationCompleted")
    return { icon: "check", label: "Verification" };
  if (event.type === "ObservationCompleted") return { icon: "globe", label: "Observation" };
  if (event.type === "ActionStarted" || event.type === "ActionCompleted")
    return { icon: "play", label: "Action" };
  if (event.type === "BrowserCodeStarted" || event.type === "BrowserCodeCompleted")
    return { icon: "code", label: "Page data" };
  if (event.type === "RunPaused") return { icon: "pause", label: "Paused" };
  if (event.type === "RunCompleted") return { icon: "check", label: "Result" };
  return { icon: "tab", label: "Runtime" };
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const presentation = eventPresentation(event);
  const date = new Date(event.createdAt);
  const time = Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <li className={`timeline-item event-${event.status}`}>
      <span className="timeline-icon">
        <Icon name={presentation.icon} size={16} />
      </span>
      <div className="timeline-copy">
        <div className="timeline-meta">
          <span>
            {presentation.label}
            {event.step !== undefined ? ` · Step ${event.step}` : ""}
          </span>
          <time dateTime={event.createdAt}>{time}</time>
        </div>
        {event.type === "DecisionMade" && event.detail ? (
          <details className="decision-summary">
            <summary>
              {event.label}
              <Icon name="chevron" size={14} />
            </summary>
            <p>{event.detail}</p>
          </details>
        ) : (
          <>
            <h3>{event.label}</h3>
            {event.detail && <p>{event.detail}</p>}
          </>
        )}
        <span className="event-outcome">
          {event.status === "completed"
            ? "Completed"
            : event.status === "failed"
              ? "Failed"
              : event.status === "running"
                ? "In progress"
                : "Update"}
        </span>
      </div>
    </li>
  );
}
