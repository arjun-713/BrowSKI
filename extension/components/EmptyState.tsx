import type { ExtensionSnapshot } from "../src/protocol";
import { Icon } from "./Icon";

const EXAMPLES = [
  {
    icon: "read",
    label: "Summarize this page",
    task: "Summarize the key points on this page.",
  },
  {
    icon: "search",
    label: "Research a topic",
    task: "Research the following topic and link your sources: ",
  },
  { icon: "tab", label: "Compare two options", task: "Compare these two options: " },
  {
    icon: "type",
    label: "Help fill a form",
    task: "Help me fill in this form with the following details: ",
  },
] as const;

export function EmptyState({
  snapshot,
  busy,
  onExample,
  onSettings,
  onConnect,
}: {
  snapshot: ExtensionSnapshot;
  busy: boolean;
  onExample: (task: string) => void;
  onSettings: () => void;
  onConnect: () => void;
}) {
  const disconnected = !snapshot.protocolReady;
  const needsKey =
    !disconnected &&
    !snapshot.openAiKeyConfigured &&
    (snapshot.runtimeSettings?.engine ?? "general") === "general";

  return (
    <section className="welcome" aria-labelledby="welcome-heading">
      <h2 id="welcome-heading">What should I do in your browser?</h2>
      <p className="welcome-lede">
        I work in your current tab, print every step as I go, and stop for your approval
        before anything risky.
      </p>
      <ol className="example-tasks" aria-label="Example tasks">
        {EXAMPLES.map((example) => (
          <li key={example.label}>
            <button onClick={() => onExample(example.task)}>
              <Icon name={example.icon} size={16} />
              <span>{example.label}</span>
              <Icon name="diagonal" size={13} />
            </button>
          </li>
        ))}
      </ol>
      {disconnected ? (
        <div className="setup-notice" role="status">
          <Icon name="connection" size={18} />
          <div>
            <h3>
              {snapshot.host === "connecting"
                ? "Connecting to your runtime…"
                : "Connect your local runtime"}
            </h3>
            <p>
              Start BROWSKI on this computer with <code>browski serve</code>, then retry.
              You can draft a task below.
            </p>
            {snapshot.hostError && (
              <details className="technical-detail">
                <summary>
                  <Icon name="chevron" size={11} />
                  Technical detail
                </summary>
                <p>{snapshot.hostError}</p>
              </details>
            )}
            <button
              className="text-button"
              disabled={busy || snapshot.host === "connecting"}
              onClick={onConnect}
            >
              Retry connection <Icon name="refresh" size={14} />
            </button>
          </div>
        </div>
      ) : needsKey ? (
        <div className="setup-notice" role="status">
          <Icon name="key" size={18} />
          <div>
            <h3>Add your OpenAI key</h3>
            <p>General uses OpenAI to work in your tabs. Add a key in Settings to begin.</p>
            <button className="text-button" onClick={onSettings}>
              Open Settings <Icon name="chevron" size={14} />
            </button>
          </div>
        </div>
      ) : (
        <p className="welcome-consent">
          <Icon name="tab" size={14} /> Send starts a task from your current tab.
        </p>
      )}
    </section>
  );
}
