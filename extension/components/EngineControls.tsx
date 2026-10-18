import type { RuntimeSettingsSnapshot, RuntimeSettingsUpdate } from "../src/protocol";
import { editableRuntimeSettings } from "../src/protocol";

export function EngineControls({
  settings,
  disabled,
  onSave,
}: {
  settings: RuntimeSettingsSnapshot | null;
  disabled: boolean;
  onSave: (settings: RuntimeSettingsUpdate) => Promise<void>;
}) {
  if (!settings?.engine) return null;
  const engine = settings.engine;
  function update(patch: Partial<RuntimeSettingsUpdate>): void {
    if (settings) void onSave({ ...editableRuntimeSettings(settings), ...patch });
  }
  return (
    <section className="engine-controls" aria-label="Task engine">
      <div className="engine-selectors">
        <label>
          <span>Engine</span>
          <select
            aria-label="Engine"
            value={engine}
            disabled={disabled}
            onChange={(event) =>
              update({
                engine: event.target.value as RuntimeSettingsUpdate["engine"],
              })
            }
          >
            <option value="fast">Fast · links</option>
            <option value="general">General · approve</option>
            {engine === "legacy" && <option value="legacy">Legacy</option>}
          </select>
        </label>
        {engine === "fast" && (
          <label>
            <span>Decisions</span>
            <select
              aria-label="Decision provider"
              value={settings.fastProvider ?? "laya"}
              disabled={disabled}
              onChange={(event) =>
                update({
                  fastProvider: event.target.value as RuntimeSettingsUpdate["fastProvider"],
                })
              }
            >
              <option value="laya">Laya · local</option>
              <option value="jev">Jev · hosted</option>
            </select>
          </label>
        )}
      </div>
      <p className="footnote">
        {engine === "legacy"
          ? "Controls the explicitly attached tab."
          : "Opens a separate task browser. Your selected tabs remain reference context."}
        {engine === "general" &&
          (!settings.allowPaidApi || settings.textProvider !== "openai") &&
          " Enable OpenAI and paid access in settings to use General."}
        {engine === "fast" && settings.fastProvider === "laya" && " No paid inference."}
      </p>
    </section>
  );
}
