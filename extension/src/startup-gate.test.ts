import { describe, expect, it } from "vitest";
import { StartupGate, withStartupTimeout } from "./startup-gate";

describe("StartupGate", () => {
  it("holds explicit attachment work until persisted state restoration finishes", async () => {
    const gate = new StartupGate();
    let attached = false;
    let finishRestore: (() => void) | undefined;
    const restoration = new Promise<void>((resolve) => {
      finishRestore = resolve;
    });
    const restore = restoration.finally(() => gate.release());
    const attach = gate.wait().then(() => {
      attached = true;
    });

    await Promise.resolve();
    expect(attached).toBe(false);

    finishRestore?.();
    await restore;
    await attach;
    expect(attached).toBe(true);
  });

  it("reports restoration failure to attachment callers", async () => {
    const gate = new StartupGate();
    const wait = gate.wait();
    gate.fail("Saved browser state could not be checked.");
    await expect(wait).rejects.toThrow("Saved browser state could not be checked.");
  });

  it("bounds Chrome restoration calls that never resolve", async () => {
    const operation = new Promise<void>(() => undefined);
    await expect(withStartupTimeout(operation, "Chrome target lookup", 1)).rejects.toThrow(
      "Chrome target lookup timed out.",
    );
  });
});
