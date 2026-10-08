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
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            B
          </span>
          <div>
            <p className="eyebrow">BROWSKI</p>
            <h1>Browser companion</h1>
          </div>
        </div>
        <span className={`connection-state state-${snapshot.host}`}>
          <span className="state-dot" aria-hidden="true" />
          {label}
        </span>
      </header>

      <section className="runtime-strip" aria-labelledby="runtime-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">ON THIS DEVICE</p>
            <h2 id="runtime-heading">Local service</h2>
          </div>
        </div>

        <p className="muted-copy">
          {snapshot.protocolReady
            ? snapshot.session
              ? "BROWSKI is connected to your local service."
              : "Connected. Choose a browser tab to begin."
            : "Start BROWSKI on this device, then connect here."}
        </p>
        {snapshot.hostError && <p className="inline-error">{snapshot.hostError}</p>}
        <div className="button-row">
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
      </section>
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
