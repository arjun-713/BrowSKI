import { describe, expect, it } from "vitest";
import {
  ALLOWED_DEBUGGER_METHODS,
  PROTOCOL_VERSION,
  isAllowedDebuggerCommand,
  isAllowedDebuggerEvent,
  isExtensionToHostMessage,
  isNativeHostMessage,
} from "./protocol";

function command(method: string, params: Record<string, unknown> = {}) {
  return {
    attachmentId: "attachment-1",
    commandId: "command-1",
    sessionId: "session-1",
    method,
    params,
  };
}

describe("versioned native host envelope", () => {
  it("accepts a supported, explicitly typed host event envelope", () => {
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "host.hello",
        eventId: "event-1",
        payload: { supportedProtocolVersions: [1] },
      }),
    ).toBe(true);
  });

  it("rejects unsupported major versions and unknown message types", () => {
    expect(
      isNativeHostMessage({
        protocolVersion: 2,
        type: "host.hello",
        eventId: "event-1",
        payload: { supportedProtocolVersions: [2] },
      }),
    ).toBe(false);
    expect(
      isNativeHostMessage({
        protocolVersion: 1,
        type: "debugger.raw",
        eventId: "event-2",
        payload: {},
      }),
    ).toBe(false);
  });

  it("accepts a content-minimal runtime timeline event", () => {
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-3",
        payload: {
          event: {
            eventId: "timeline-1",
            sessionId: "session-1",
            runId: "run-1",
            sequence: 1,
            step: 2,
            createdAt: "2026-10-07T00:00:00+00:00",
            type: "VerificationCompleted",
            label: "Verified browser result",
            status: "completed",
          },
        },
      }),
    ).toBe(true);
  });

  it("accepts credential presence status without accepting secret values", () => {
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.credentials.status",
        eventId: "credential-status-1",
        payload: { openAiKeyConfigured: true },
      }),
    ).toBe(true);
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.credentials.status",
        eventId: "credential-status-2",
        payload: {
          openAiKeyConfigured: true,
          apiKey: "must-not-cross-back-to-the-extension",
        },
      }),
    ).toBe(false);
  });

  it("rejects unknown or oversized timeline fields", () => {
    const event = {
      eventId: "timeline-1",
      sessionId: "session-1",
      sequence: 1,
      createdAt: "2026-10-07T00:00:00+00:00",
      type: "UnexpectedEvent",
      label: "Something happened",
      status: "completed",
    };
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-4",
        payload: { event },
      }),
    ).toBe(false);
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-5",
        payload: {
          event: { ...event, type: "ActionStarted", label: "x".repeat(161) },
        },
      }),
    ).toBe(false);
  });

  it("accepts only bounded source-free browser-code timeline metadata", () => {
    const trace = {
      purposeCategory: "semantic_data_transform",
      reasonCategory: "explicit_capability_request",
      scriptSha256: "a".repeat(64),
      scriptBytes: 123,
      timeoutMs: 750,
      maxResultBytes: 16_384,
      resultSchema: "BrowserCodePayload",
      durationMs: 12.5,
    };
    const event = {
      eventId: "timeline-code-1",
      sessionId: "session-1",
      runId: "run-1",
      sequence: 1,
      step: 2,
      createdAt: "2026-10-07T00:00:00+00:00",
      type: "BrowserCodeCompleted",
      label: "Checked semantic data transform",
      status: "completed",
      browserCode: trace,
    };
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-code-1",
        payload: { event },
      }),
    ).toBe(true);
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-code-2",
        payload: { event: { ...event, browserCode: { ...trace, script: "raw source" } } },
      }),
    ).toBe(false);
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-code-3",
        payload: { event: { ...event, browserCode: { ...trace, timeoutMs: 1_501 } } },
      }),
    ).toBe(false);
    expect(
      isNativeHostMessage({
        protocolVersion: PROTOCOL_VERSION,
        type: "runtime.timeline",
        eventId: "event-code-4",
        payload: { event: { ...event, type: "ActionStarted" } },
      }),
    ).toBe(false);
  });

  it("validates runtime settings messages with fixed values", () => {
    const envelope = {
      protocolVersion: PROTOCOL_VERSION,
      eventId: "settings-1",
    };
    expect(
      isExtensionToHostMessage({
        ...envelope,
        type: "runtime.settings.get",
        payload: {},
      }),
    ).toBe(true);
    expect(
      isExtensionToHostMessage({
        ...envelope,
        type: "runtime.settings.update",
        payload: {
          effort: "low",
          privacyMode: "privacy_first",
          layaMode: "shadow",
          traceLevel: "standard",
        },
      }),
    ).toBe(true);
    expect(
      isExtensionToHostMessage({
        ...envelope,
        type: "runtime.settings.update",
        payload: {
          effort: "high",
          privacyMode: "standard",
          layaMode: "disabled",
          traceLevel: "detailed",
        },
      }),
    ).toBe(false);
    expect(
      isNativeHostMessage({
        ...envelope,
        type: "runtime.settings.status",
        payload: {
          effort: "none",
          privacyMode: "standard",
          layaMode: "shadow",
          traceLevel: "detailed",
          confirmHighRiskActions: true,
          extensionTransport: "native_host",
        },
      }),
    ).toBe(true);
    expect(
      isNativeHostMessage({
        ...envelope,
        type: "runtime.settings.status",
        payload: { error: "Settings could not be loaded." },
      }),
    ).toBe(true);
    expect(
      isNativeHostMessage({
        ...envelope,
        type: "runtime.settings.status",
        payload: { error: "bad", effort: "high" },
      }),
    ).toBe(false);
  });
});

describe("debugger capability allowlist", () => {
  it("defines only the M2 observation and M3 page/input methods", () => {
    expect(ALLOWED_DEBUGGER_METHODS).toContain("Accessibility.getFullAXTree");
    expect(ALLOWED_DEBUGGER_METHODS).toContain("Input.dispatchMouseEvent");
    expect(ALLOWED_DEBUGGER_METHODS).toContain("Runtime.evaluate");
    expect(ALLOWED_DEBUGGER_METHODS).not.toContain("Network.enable");
  });

  it("accepts a bounded DOM query and rejects unknown domains or methods", () => {
    expect(
      isAllowedDebuggerCommand(
        command("DOM.getDocument", {
          depth: 2,
          pierce: true,
        }),
      ),
    ).toBe(true);
    expect(
      isAllowedDebuggerCommand(
        command("Runtime.evaluate", {
          expression: "document.body",
        }),
      ),
    ).toBe(false);
    expect(isAllowedDebuggerCommand(command("Network.setCookie", {}))).toBe(false);
  });

  it("rejects extra parameters and non-web navigation schemes", () => {
    expect(
      isAllowedDebuggerCommand(
        command("Page.navigate", {
          url: "https://example.test/",
          transitionType: "typed",
        }),
      ),
    ).toBe(false);
    expect(
      isAllowedDebuggerCommand(
        command("Page.navigate", {
          url: "javascript:alert(1)",
        }),
      ),
    ).toBe(false);
    expect(
      isAllowedDebuggerCommand(
        command("Input.insertText", {
          text: "x".repeat(16_385),
        }),
      ),
    ).toBe(false);
    expect(
      isAllowedDebuggerCommand({
        ...command("DOM.getDocument"),
        targetId: "another-target",
      }),
    ).toBe(false);
  });

  it("accepts only known browser events", () => {
    expect(isAllowedDebuggerEvent("Page.frameNavigated")).toBe(true);
    expect(isAllowedDebuggerEvent("Target.targetDestroyed")).toBe(true);
    expect(isAllowedDebuggerEvent("Network.requestWillBeSent")).toBe(false);
    expect(isAllowedDebuggerEvent("Runtime.consoleAPICalled")).toBe(false);
  });

  it("allows only fixed screenshot parameters and explicit owned-tab operations", () => {
    expect(
      isAllowedDebuggerCommand(
        command("Page.captureScreenshot", {
          format: "png",
          fromSurface: true,
          captureBeyondViewport: false,
        }),
      ),
    ).toBe(true);
    expect(
      isAllowedDebuggerCommand(
        command("Page.captureScreenshot", {
          format: "png",
          fromSurface: true,
          captureBeyondViewport: true,
        }),
      ),
    ).toBe(false);
    expect(
      isAllowedDebuggerCommand(
        command("BROWSKI.tabs.create", { url: "https://example.test/login" }),
      ),
    ).toBe(true);
    expect(
      isAllowedDebuggerCommand(
        command("BROWSKI.tabs.create", { url: "https://user:secret@example.test/" }),
      ),
    ).toBe(false);
    expect(
      isAllowedDebuggerCommand(command("BROWSKI.tabs.close", { targetId: "17" })),
    ).toBe(false);
  });
});
