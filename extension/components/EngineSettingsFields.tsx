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
  if (settings.engine === undefined) return null;
  return (
    <>
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
        <option value="openai">OpenAI · hosted</option>
      </select>
      {settings.textProvider === "openai" && (
        <>
          <label htmlFor="runtime-text-model">OpenAI model</label>
          <input
            id="runtime-text-model"
            value={settings.textModel ?? "gpt-6-luna"}
            maxLength={200}
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
        <span>Permit paid API calls for tasks</span>
      </label>
      <p className="footnote">
        Laya stays local. General/OpenAI and Jev need this permission and their credentials.
        A provider failure never enables paid fallback.
      </p>
      <label htmlFor="runtime-laya-checkpoint">Local Laya checkpoint</label>
      <input
        id="runtime-laya-checkpoint"
        value={settings.layaCheckpoint ?? ""}
        maxLength={1000}
        disabled={disabled}
        onChange={(event) => onChange({ layaCheckpoint: event.target.value })}
      />
      {settings.fastProvider === "jev" && (
        <>
          <label htmlFor="runtime-jev-endpoint">Jev endpoint</label>
          <input
            id="runtime-jev-endpoint"
            type="url"
            value={settings.jevEndpoint ?? ""}
            maxLength={1000}
            disabled={disabled}
            onChange={(event) => onChange({ jevEndpoint: event.target.value })}
          />
          <p className="footnote">
            Jev is optional. Configure TYPESAFE_API_KEY in the runtime environment before
            selecting it.
          </p>
        </>
      )}
    </>
  );
}
