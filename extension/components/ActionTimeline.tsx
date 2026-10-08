import type { TimelineEvent } from "../src/protocol";

export function ActionTimeline({ events }: { events: TimelineEvent[] }) {
  const orderedEvents = [...events].sort((a, b) => b.sequence - a.sequence);

  return (
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
  );
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

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
