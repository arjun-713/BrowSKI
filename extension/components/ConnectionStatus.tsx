import type { ExtensionSnapshot } from "../src/protocol";

export function ConnectionStatus({
  snapshot,
  busy,
  onDispatch,
}: {
  snapshot: ExtensionSnapshot;
  busy: boolean;
  onDispatch: (message: Record<string, unknown>) => Promise<unknown>;
}) {
  const label = hostStatusLabel(snapshot.host, snapshot.protocolReady);

  return (
    <>
      <div className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            B
          </span>
          <h1 aria-label="Browser companion">BROWSKI</h1>
        </div>
        <span className={`connection-state state-${snapshot.host}`}>
          <span className="state-dot" aria-hidden="true" />
          {label}
        </span>
      </div>
      <div className="runtime-strip">
        {snapshot.hostError && <p className="inline-error">{snapshot.hostError}</p>}
        <div className="runtime-action">
          {snapshot.host === "connected" ? (
            <button
              className="button button-secondary"
              onClick={() => void onDispatch({ type: "host.disconnect" })}
              disabled={busy}
            >
              Disconnect host
            </button>
          ) : (
            <button
              className="button button-primary"
              onClick={() => void onDispatch({ type: "host.connect" })}
              disabled={busy || snapshot.host === "connecting"}
            >
              {snapshot.host === "connecting" ? "Connecting…" : "Connect runtime host"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function hostStatusLabel(
  status: ExtensionSnapshot["host"],
  protocolReady: boolean,
): string {
  if (status === "connected" && protocolReady) return "Connected";
  if (status === "connected") return "Negotiating";
  if (status === "connecting") return "Connecting";
  if (status === "error") return "Connection error";
  return "Disconnected";
}
