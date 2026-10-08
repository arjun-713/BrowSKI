import { describe, expect, it } from "vitest";
import { canStartTask, permittedRunControls } from "./run-controls";

describe("task lifecycle controls", () => {
  it("keeps an idle session distinct from a paused run", () => {
    expect(permittedRunControls("idle")).toEqual([]);
    expect(permittedRunControls("paused")).toEqual(["resume", "stop"]);
    expect(canStartTask("idle")).toBe(true);
    expect(canStartTask("paused")).toBe(false);
  });

  it("requires explicit approval instead of normal resume", () => {
    expect(permittedRunControls("awaiting_approval")).toEqual(["stop"]);
    expect(canStartTask("awaiting_approval")).toBe(false);
  });

  it("permits a fresh task after terminal outcomes", () => {
    for (const status of ["completed", "stopped", "failed"] as const) {
      expect(permittedRunControls(status)).toEqual([]);
      expect(canStartTask(status)).toBe(true);
    }
    expect(permittedRunControls("running")).toEqual(["pause", "stop"]);
    expect(canStartTask("running")).toBe(false);
  });
});
