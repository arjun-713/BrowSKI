import type { RuntimeStatus } from "./protocol";

export type RunControl = "pause" | "resume" | "stop";

export function permittedRunControls(status: RuntimeStatus): RunControl[] {
  if (status === "running") return ["pause", "stop"];
  if (status === "paused") return ["resume", "stop"];
  if (status === "awaiting_approval") return ["stop"];
  return [];
}

export function canStartTask(status: RuntimeStatus): boolean {
  return ["idle", "completed", "stopped", "failed"].includes(status);
}
