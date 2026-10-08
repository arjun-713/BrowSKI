import type { RuntimeStatus } from "../src/protocol";
import { permittedRunControls, type RunControl } from "../src/run-controls";

const LABELS: Record<RunControl, string> = {
  pause: "Pause",
  resume: "Resume",
  stop: "Stop",
};

export function RunControls({
  status,
  busy,
  onControl,
}: {
  status: RuntimeStatus;
  busy: boolean;
  onControl: (control: RunControl) => Promise<void>;
}) {
  const controls = permittedRunControls(status);
  if (controls.length === 0) return null;

  return (
    <div className="button-row task-controls" aria-label="Task controls">
      {controls.map((control) => (
        <button
          key={control}
          className={`button ${control === "stop" ? "button-danger" : "button-secondary"}`}
          onClick={() => void onControl(control)}
          disabled={busy}
        >
          {LABELS[control]}
        </button>
      ))}
    </div>
  );
}
