import { afterEach, describe, expect, it, vi } from "vitest";

import { NativeHostController } from "./native-host";
import type { ExtensionSnapshot, TimelineEvent } from "./protocol";

const timestamp = "2026-10-16T01:00:00+00:00";

function controllerHarness() {
  const listeners: Array<(message: unknown) => void> = [];
  const disconnectPort = vi.fn();
  const snapshot: ExtensionSnapshot = {
    host: "disconnected",
    hostError: null,
    protocolReady: false,
    session: null,
    events: [],
    pendingApproval: null,
    openAiKeyConfigured: false,
    settingsError: null,
    runtimeSettings: null,
    selectedTab: null,
    attachment: null,
  };
  const controller = new NativeHostController({
    snapshot,
    publishSnapshot: vi.fn(),
    detachOwnedTab: vi.fn(async () => undefined),
    clearSelectedTab: vi.fn(async () => undefined),
    handleDebuggerCommand: vi.fn(),
    handleDetachRequest: vi.fn(),
  });
  vi.stubGlobal("chrome", {
    runtime: {
      connectNative: () => ({
        postMessage: vi.fn(),
        disconnect: disconnectPort,
        onMessage: {
          addListener: (listener: (message: unknown) => void) => listeners.push(listener),
        },
        onDisconnect: { addListener: vi.fn() },
      }),
    },
  });
  controller.connectHost();

  function send(
    type: string,
    payload: Record<string, unknown>,
    connection = listeners.length - 1,
  ) {
    listeners[connection]({
      protocolVersion: 1,
      eventId: crypto.randomUUID(),
      type,
      payload,
    });
  }

  send("host.hello", {
    supportedProtocolVersions: [1],
    debuggerProtocolVersion: 1,
    debuggerMethods: [],
    debuggerEvents: [],
  });
  send("runtime.snapshot", { session: null, events: [], pendingApproval: null });

  function startRun(runId: string) {
    send("runtime.status", {
      session: { sessionId: "session-1", runId, status: "running", updatedAt: timestamp },
    });
  }

  function event(runId: string, sequence: number, type: TimelineEvent["type"]) {
    send("runtime.timeline", {
      event: {
        eventId: crypto.randomUUID(),
        sessionId: "session-1",
        runId,
        sequence,
        createdAt: timestamp,
        type,
        label: type,
        status: "running",
      },
    });
  }

  return { snapshot, controller, send, startRun, event, disconnectPort };
}

afterEach(() => vi.unstubAllGlobals());

describe("run-scoped native timeline", () => {
  it("accepts sequence one for a second task and rejects late previous-run events", () => {
    const harness = controllerHarness();
    harness.startRun("run-1");
    harness.event("run-1", 1, "RunStarted");
    harness.event("run-1", 12, "RunFailed");

    harness.startRun("run-2");
    harness.event("run-2", 1, "RunStarted");
    harness.event("run-2", 2, "ObservationStarted");
    harness.event("run-1", 13, "ActionStarted");

    expect(harness.snapshot.events.map((event) => event.type)).toEqual([
      "RunStarted",
      "ObservationStarted",
    ]);
    expect(harness.snapshot.events.every((event) => event.runId === "run-2")).toBe(true);
    harness.controller.disconnectHost();
  });

  it("enriches the terminal graph event instead of appending a duplicate failure", () => {
    const harness = controllerHarness();
    harness.startRun("run-1");
    harness.event("run-1", 1, "RunStarted");
    harness.event("run-1", 2, "RunFailed");
    const terminalId = harness.snapshot.events[1].eventId;

    harness.send("runtime.task.result", {
      sessionId: "session-1",
      runId: "run-1",
      outcome: "failed",
      summary: "Browser observation failed. Reattach the tab.",
      finishedAt: timestamp,
    });

    expect(harness.snapshot.events).toHaveLength(2);
    expect(harness.snapshot.events[1].eventId).toBe(terminalId);
    expect(harness.snapshot.events[1].detail).toBe(
      "Browser observation failed. Reattach the tab.",
    );
    expect(harness.snapshot.session?.status).toBe("failed");
    harness.controller.disconnectHost();
  });

  it("ignores results for a different run or attachment", () => {
    const harness = controllerHarness();
    harness.startRun("run-2");
    for (const identity of [
      { sessionId: "session-1", runId: "run-1" },
      { sessionId: "other-session", runId: "run-2" },
    ]) {
      harness.send("runtime.task.result", {
        ...identity,
        outcome: "failed",
        summary: "Old failure",
        finishedAt: timestamp,
      });
    }
    expect(harness.snapshot.events).toEqual([]);
    expect(harness.snapshot.session?.status).toBe("running");
    harness.controller.disconnectHost();
  });

  it("ignores a future trace kind while keeping the debugger bridge usable", () => {
    const harness = controllerHarness();
    harness.startRun("run-1");
    harness.event("run-1", 1, "FutureTraceKind");
    expect(harness.snapshot.events).toEqual([]);
    expect(harness.snapshot.protocolReady).toBe(true);
    expect(harness.snapshot.hostError).toBeNull();
    harness.event("run-1", 2, "ObservationStarted");
    expect(harness.snapshot.events).toHaveLength(1);
    harness.controller.disconnectHost();
  });

  it("disconnects on a malformed authoritative timeline message", () => {
    const harness = controllerHarness();
    harness.send("runtime.timeline", {
      event: {
        eventId: "invalid-event",
        sessionId: "",
        runId: "run-1",
        sequence: 1,
        createdAt: timestamp,
        type: "RunStarted",
        label: "Started",
        status: "running",
      },
    });
    expect(harness.snapshot.host).toBe("error");
    expect(harness.snapshot.protocolReady).toBe(false);
    expect(harness.disconnectPort).toHaveBeenCalledOnce();
    expect(harness.controller.sendNative("runtime.snapshot.request", {})).toBe(false);
  });

  it("disconnects on an invalid authoritative runtime session", () => {
    const harness = controllerHarness();
    harness.send("runtime.status", {
      session: {
        sessionId: "session-1",
        runId: "r".repeat(129),
        status: "running",
        updatedAt: timestamp,
      },
    });

    expect(harness.snapshot.host).toBe("error");
    expect(harness.snapshot.protocolReady).toBe(false);
    expect(harness.disconnectPort).toHaveBeenCalledOnce();
    expect(harness.controller.sendNative("runtime.snapshot.request", {})).toBe(false);
  });
});

describe("native connection ownership", () => {
  it("ignores queued data from a disconnected port during the next handshake", () => {
    const harness = controllerHarness();
    harness.startRun("old-run");
    harness.controller.disconnectHost();
    harness.controller.connectHost();

    harness.send(
      "runtime.status",
      {
        session: {
          sessionId: "old-session",
          runId: "old-run",
          status: "running",
          updatedAt: timestamp,
        },
      },
      0,
    );

    expect(harness.snapshot.host).toBe("connecting");
    expect(harness.snapshot.protocolReady).toBe(false);
    expect(harness.snapshot.hostError).toBeNull();
    // Only the intentionally closed old port may have been disconnected.
    expect(harness.disconnectPort).toHaveBeenCalledOnce();
    harness.controller.disconnectHost();
  });

  it("refuses to replace the current run with a snapshot from an old connection", () => {
    const harness = controllerHarness();
    harness.startRun("old-run");
    harness.controller.disconnectHost();
    harness.controller.connectHost();
    harness.send("host.hello", {
      supportedProtocolVersions: [1],
      debuggerProtocolVersion: 1,
      debuggerMethods: [],
      debuggerEvents: [],
    });
    harness.send("runtime.snapshot", {
      session: null,
      events: [],
      pendingApproval: null,
    });
    harness.startRun("current-run");
    harness.event("current-run", 1, "RunStarted");

    harness.send(
      "runtime.snapshot",
      {
        session: {
          sessionId: "old-session",
          runId: "old-run",
          status: "failed",
          updatedAt: timestamp,
        },
        events: [],
        pendingApproval: null,
      },
      0,
    );

    expect(harness.snapshot.protocolReady).toBe(true);
    expect(harness.snapshot.session?.runId).toBe("current-run");
    expect(harness.snapshot.events.map((event) => event.type)).toEqual(["RunStarted"]);
    harness.controller.disconnectHost();
  });
});
