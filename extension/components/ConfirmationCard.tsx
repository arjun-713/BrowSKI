import type { PendingApproval } from "../src/protocol";

export function ConfirmationCard({
  approval,
  busy,
  onRespond,
}: {
  approval: PendingApproval;
  busy: boolean;
  onRespond: (approval: PendingApproval, approved: boolean) => Promise<void>;
}) {
  return (
    <section className="approval-panel" aria-labelledby="approval-heading">
      <div className="approval-topline">
        <p className="eyebrow">USER APPROVAL REQUIRED</p>
        <span className={`risk-tag risk-${approval.risk}`}>{approval.risk} risk</span>
      </div>
      <h2 id="approval-heading">{approval.title}</h2>
      <p>{approval.summary}</p>
      <div className="button-row approval-actions">
        <button
          className="button button-primary"
          onClick={() => void onRespond(approval, true)}
          disabled={busy}
        >
          Approve action
        </button>
        <button
          className="button button-secondary"
          onClick={() => void onRespond(approval, false)}
          disabled={busy}
        >
          Deny action
        </button>
      </div>
      <p className="footnote">The runtime ties this choice to its pending checkpoint.</p>
    </section>
  );
}
