import { useEffect, useRef, useState } from "react";
import type { PendingApproval } from "../src/protocol";
import { Icon } from "./Icon";
import { pageHost } from "./display";

function safeDetail(approval: PendingApproval, key: string): string {
  const value = approval.details?.[key];
  return typeof value === "string" ? value.slice(0, key === "reason" ? 300 : 500) : "";
}

export function ConfirmationCard({
  approval,
  busy,
  pageUrl,
  onRespond,
}: {
  approval: PendingApproval;
  busy: boolean;
  pageUrl?: string;
  onRespond: (approval: PendingApproval, approved: boolean) => Promise<void>;
}) {
  const card = useRef<HTMLElement>(null);
  const [now, setNow] = useState(Date.now());
  const [responded, setResponded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const opened = useRef(Date.now());
  const fallbackDeadline = useRef(opened.current + 60_000);
  const parsedDeadline = approval.expiresAt
    ? Date.parse(approval.expiresAt)
    : fallbackDeadline.current;
  const deadline = Number.isFinite(parsedDeadline) ? parsedDeadline : 0;
  const remaining = Math.max(0, Math.ceil((deadline - now) / 1000));
  const expired = remaining === 0;
  const approvalWindow = Math.max(1, deadline - opened.current);
  const left = Math.min(1, Math.max(0, (deadline - now) / approvalWindow));
  const target = safeDetail(approval, "target");
  const host = pageHost(target) || pageHost(pageUrl);
  const reason = safeDetail(approval, "reason");
  const action = safeDetail(approval, "action");

  useEffect(() => {
    card.current?.focus();
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [approval.approvalId]);

  async function respond(approved: boolean): Promise<void> {
    if (busy || responded || expired) return;
    setResponded(true);
    setError(null);
    try {
      await onRespond(approval, approved);
    } catch {
      setResponded(false);
      setError("Your response could not be sent. Check the connection and try again.");
    }
  }

  return (
    <section
      ref={card}
      tabIndex={-1}
      className="approval-panel"
      aria-labelledby="approval-heading"
    >
      <div className="approval-head">
        <Icon name="info" size={18} />
        <h2 id="approval-heading">{action ? `${action}?` : approval.title}</h2>
        <span
          className="approval-countdown"
          role="timer"
          aria-label={
            expired ? "Approval expired" : `Approval expires in ${remaining} seconds`
          }
        >
          {expired ? "Expired" : `${remaining}s`}
        </span>
      </div>
      <div className="approval-drain" aria-hidden="true">
        <span style={{ transform: `scaleX(${left})` }} />
      </div>
      {!action && <p>{approval.summary}</p>}
      {(host || target) && (
        <p className="approval-site">
          <Icon name="globe" size={14} />
          {host || target}
        </p>
      )}
      {reason && <p className="approval-reason">{reason}</p>}
      <div className="button-row approval-actions">
        <button
          className="button button-primary"
          onClick={() => void respond(true)}
          disabled={busy || responded || expired}
        >
          Approve action
        </button>
        <button
          className="button button-secondary"
          onClick={() => void respond(false)}
          disabled={busy || responded || expired}
        >
          Decline
        </button>
      </div>
      <p className="footnote">
        {expired
          ? "This request expired. The agent must ask again before acting."
          : "Permission applies to this action only."}
      </p>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
    </section>
  );
}
