import type { ExtensionSnapshot } from "../src/protocol";

export function TabAttachment({
  snapshot,
  busy,
  onDispatch,
}: {
  snapshot: ExtensionSnapshot;
  busy: boolean;
  onDispatch: (message: Record<string, unknown>) => Promise<unknown>;
}) {
  return (
    <section className="tab-section" aria-labelledby="tab-heading">
      <div className="section-heading compact-heading">
        <div>
          <p className="eyebrow">BROWSER TAB</p>
          <h2 id="tab-heading">Choose a tab</h2>
        </div>
        <span className={`text-state ${snapshot.attachment ? "text-state-on" : ""}`}>
          {snapshot.attachment?.state ??
            (snapshot.selectedTab ? "Ready to confirm" : "Not attached")}
        </span>
      </div>
      <p className="muted-copy">
        {snapshot.attachment?.message ??
          "Capture the active tab, review its origin, then confirm attachment."}
      </p>
      {snapshot.selectedTab && !snapshot.attachment && (
        <div className="selection-review">
          <span className="selection-label">Selected tab origin</span>
          <code>{snapshot.selectedTab.origin}</code>
          <span className="tab-reference">
            Your selection stays fixed when the active browser tab changes.
          </span>
        </div>
      )}
      {snapshot.attachment && (
        <div className="selection-review">
          <span className="selection-label">Attached tab origin</span>
          <code>{snapshot.attachment.origin}</code>
        </div>
      )}
      <div className="button-row">
        {snapshot.attachment && snapshot.attachment.state !== "error" ? (
          <button
            className="button button-secondary"
            onClick={() => void onDispatch({ type: "tab.detach" })}
            disabled={busy}
          >
            Detach tab
          </button>
        ) : snapshot.attachment?.state === "error" ? (
          <button
            className="button button-secondary"
            onClick={() => void onDispatch({ type: "tab.detach" })}
            disabled={busy}
          >
            Clear attachment error
          </button>
        ) : snapshot.selectedTab ? (
          <>
            <button
              className="button button-primary"
              onClick={() => void onDispatch({ type: "tab.attachSelected" })}
              disabled={!snapshot.protocolReady || busy}
            >
              Confirm and attach
            </button>
            <button
              className="button button-secondary"
              onClick={() => void onDispatch({ type: "tab.captureActive" })}
              disabled={!snapshot.protocolReady || busy}
            >
              Choose current tab
            </button>
            <button
              className="button button-secondary"
              onClick={() => void onDispatch({ type: "tab.clearSelection" })}
              disabled={busy}
            >
              Clear selection
            </button>
          </>
        ) : (
          <button
            className="button button-secondary"
            onClick={() => void onDispatch({ type: "tab.captureActive" })}
            disabled={!snapshot.protocolReady || busy}
          >
            Capture active tab
          </button>
        )}
      </div>
      {!snapshot.session && (
        <p className="footnote">
          BROWSKI can operate the selected tab only after you confirm attachment.
        </p>
      )}
    </section>
  );
}
