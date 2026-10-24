import { Icon } from "./Icon";

export type OutcomeDraft = { startUrl: string; url: string; heading: string };

export function TaskOutcomeFields({
  draft,
  disabled,
  onChange,
}: {
  draft: OutcomeDraft;
  disabled: boolean;
  onChange: (draft: OutcomeDraft) => void;
}) {
  return (
    <details className="task-outcome-fields">
      <summary>
        <Icon name="chevron" size={11} />
        Verify outcome (optional)
      </summary>
      <label htmlFor="task-start-url">Starting page</label>
      <input
        id="task-start-url"
        type="url"
        value={draft.startUrl}
        maxLength={2048}
        placeholder="Or include a link in your task"
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, startUrl: event.target.value })}
      />
      <p className="footnote">
        Fast starts here, or uses a link in your task. General starts in your current tab.
      </p>
      <label htmlFor="task-expected-url">Expected final page URL</label>
      <input
        id="task-expected-url"
        type="url"
        value={draft.url}
        maxLength={2048}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, url: event.target.value })}
      />
      <label htmlFor="task-expected-heading">Expected page heading</label>
      <input
        id="task-expected-heading"
        value={draft.heading}
        maxLength={200}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, heading: event.target.value })}
      />
      <p className="footnote">
        Both checks must match the final page. Without these checks, General asks an
        independent judge to verify the outcome.
      </p>
    </details>
  );
}
