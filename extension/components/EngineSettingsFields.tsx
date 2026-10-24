import type { RuntimeSettingsUpdate } from "../src/protocol";

export function EngineSettingsFields({
  settings,
  disabled,
  onChange,
}: {
  settings: RuntimeSettingsUpdate;
  disabled: boolean;
  onChange: (patch: Partial<RuntimeSettingsUpdate>) => void;
}) {
  return (
    <>
      <label htmlFor="runtime-engine">Engine</label>
      <select
        id="runtime-engine"
        value={settings.engine ?? "legacy"}
        disabled={disabled}
        onChange={(event) => {
          const engine = event.target.value as RuntimeSettingsUpdate["engine"];
          onChange({ engine, ...(engine === "general" ? { textProvider: "openai" } : {}) });
        }}
      >
        <option value="general">General · OpenAI</option>
        <option value="fast">
          Fast · {settings.fastProvider === "jev" ? "Jev" : "Laya"}
        </option>
        {(settings.engine ?? "legacy") === "legacy" && (
          <option value="legacy">Legacy · Advanced</option>
        )}
      </select>
      <p className="footnote">
        {settings.engine === "general"
          ? "Works in your current Chrome tab with your existing logins. Send starts the task; risky actions need your approval."
          : settings.engine === "fast"
            ? "Local Laya handles bounded browser tasks in a separate task browser."
            : "The retained Legacy runtime requires an explicit tab attachment under Advanced."}
      </p>
      <label htmlFor="runtime-text-provider">Generative text</label>
      <select
        id="runtime-text-provider"
        value={settings.textProvider ?? "disabled"}
        disabled={disabled}
        onChange={(event) =>
          onChange({
            textProvider: event.target.value as RuntimeSettingsUpdate["textProvider"],
          })
        }
      >
        <option value="disabled">Disabled</option>
        <option value="openai">OpenAI</option>
      </select>
      {settings.textProvider === "openai" && (
        <>
          <label htmlFor="runtime-text-model">OpenAI model</label>
          <input
            id="runtime-text-model"
            value={settings.textModel ?? "gpt-6-luna"}
            maxLength={200}
            required
            disabled={disabled}
            onChange={(event) => onChange({ textModel: event.target.value })}
          />
        </>
      )}
      <label className="setting-toggle">
        <input
          type="checkbox"
          checked={settings.allowPaidApi ?? false}
          disabled={disabled}
          onChange={(event) => onChange({ allowPaidApi: event.target.checked })}
        />
        <span>Allow paid API usage</span>
      </label>
      <p className="footnote">
        General sends page content and, when needed, screenshots to OpenAI. Each task uses
        your API credits. Turning this off prevents paid calls. Local Laya does not use API
        credits; providers never switch automatically.
      </p>
    </>
  );
}
