import { createNativeEnvelope } from "./native-envelope";
import {
  ALLOWED_DEBUGGER_EVENTS,
  ALLOWED_DEBUGGER_METHODS,
  DEBUGGER_PROTOCOL_VERSION,
  MAX_EXTENSION_TO_HOST_MESSAGE_BYTES,
  MAX_HOST_TO_EXTENSION_MESSAGE_BYTES,
  PROTOCOL_VERSION,
  isNativeHostMessage,
  isPlainRecord,
  isTimelineEvent,
  type DebuggerMethod,
  type ExtensionSnapshot,
  type NativeHostMessage,
  type PendingApproval,
  type RuntimeSession,
  type TimelineEvent,
} from "./protocol";

const NATIVE_HOST_NAME = "com.browski.runtime";
const MAX_TIMELINE_EVENTS = 80;

type NativeHostDependencies = {
  snapshot: ExtensionSnapshot;
  publishSnapshot: () => void;
  detachOwnedTab: (reason: string, retainError?: boolean) => Promise<void>;
  clearSelectedTab: () => Promise<void>;
  handleDebuggerCommand: (payload: unknown) => void;
  handleDetachRequest: (payload: Record<string, unknown>) => void;
};

export class NativeHostController {
  private nativePort: chrome.runtime.Port | null = null;
  private hostNegotiated = false;
  private sequence = 0;
  private readonly negotiatedMethods = new Set<DebuggerMethod>();
  private readonly negotiatedEvents = new Set<string>();

  constructor(private readonly dependencies: NativeHostDependencies) {}

  sendNative = (type: string, payload: Record<string, unknown>): boolean => {
    if (!this.nativePort) return false;
    const envelope = createNativeEnvelope(type, payload);
    const encoded = JSON.stringify(envelope);
    if (
      new TextEncoder().encode(encoded).byteLength > MAX_EXTENSION_TO_HOST_MESSAGE_BYTES
    ) {
      return false;
    }
    this.nativePort.postMessage(envelope);
    return true;
  };

  setHostError = (message: string): void => {
    const { snapshot, publishSnapshot } = this.dependencies;
    snapshot.host = "error";
    snapshot.hostError = message;
    snapshot.protocolReady = false;
    this.hostNegotiated = false;
    publishSnapshot();
  };

  connectHost = (): void => {
    if (this.nativePort) return;
    const { snapshot, publishSnapshot } = this.dependencies;
    snapshot.host = "connecting";
    snapshot.hostError = null;
    snapshot.protocolReady = false;
    this.hostNegotiated = false;
    publishSnapshot();

    try {
      const port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
      this.nativePort = port;
      port.onMessage.addListener(this.onNativeMessage);
      port.onDisconnect.addListener(() => {
        const lastError = chrome.runtime.lastError?.message;
        this.nativePort = null;
        snapshot.protocolReady = false;
        this.hostNegotiated = false;
        this.negotiatedMethods.clear();
        this.negotiatedEvents.clear();
        void this.dependencies.detachOwnedTab(
          "The native runtime connection closed.",
          true,
        );
        void this.dependencies.clearSelectedTab();
        snapshot.host = lastError ? "error" : "disconnected";
        snapshot.hostError = lastError
          ? `Native host disconnected: ${lastError}`
          : "Native host connection closed.";
        publishSnapshot();
      });
      this.sendNative("extension.hello", {
        protocolVersions: [PROTOCOL_VERSION],
        debuggerProtocolVersion: DEBUGGER_PROTOCOL_VERSION,
        debuggerMethods: ALLOWED_DEBUGGER_METHODS,
        debuggerEvents: ALLOWED_DEBUGGER_EVENTS,
      });
    } catch (error) {
      this.setHostError(errorMessage(error));
    }
  };

  disconnectHost = (): void => {
    const { snapshot, publishSnapshot } = this.dependencies;
    void this.dependencies.detachOwnedTab(
      "Disconnected from the runtime by the user.",
      true,
    );
    void this.dependencies.clearSelectedTab();
    this.nativePort?.disconnect();
    this.nativePort = null;
    snapshot.host = "disconnected";
    snapshot.hostError = null;
    snapshot.protocolReady = false;
    this.hostNegotiated = false;
    this.negotiatedMethods.clear();
    this.negotiatedEvents.clear();
    publishSnapshot();
  };

  getNegotiatedMethods(): ReadonlySet<DebuggerMethod> {
    return this.negotiatedMethods;
  }

  getNegotiatedEvents(): ReadonlySet<string> {
    return this.negotiatedEvents;
  }

  private readonly onNativeMessage = (value: unknown): void => {
    const { snapshot } = this.dependencies;
    if (
      new TextEncoder().encode(JSON.stringify(value)).byteLength >
      MAX_HOST_TO_EXTENSION_MESSAGE_BYTES
    ) {
      this.setHostError("Native host message exceeded the 1 MiB application limit.");
      this.nativePort?.disconnect();
      return;
    }
    if (!isNativeHostMessage(value)) {
      this.setHostError("Native host sent an unsupported protocol message.");
      return;
    }
    if (value.type === "host.hello") {
      this.handleHostHello(value);
      return;
    }
    if (
      !snapshot.protocolReady &&
      !(this.hostNegotiated && value.type === "runtime.snapshot")
    ) {
      this.setHostError("Native host sent data before protocol negotiation completed.");
      return;
    }
    switch (value.type) {
      case "runtime.snapshot":
        this.handleRuntimeSnapshot(value);
        break;
      case "runtime.status":
        this.handleRuntimeStatus(value);
        break;
      case "runtime.timeline":
        this.handleTimelineEvent(value.payload.event);
        break;
      case "runtime.approval.required":
        this.handleApprovalRequired(value.payload.approval);
        break;
      case "runtime.approval.cleared":
        if (snapshot.pendingApproval?.approvalId === value.payload.approvalId) {
          snapshot.pendingApproval = null;
        }
        this.dependencies.publishSnapshot();
        break;
      case "runtime.credentials.status":
        snapshot.openAiKeyConfigured = value.payload.openAiKeyConfigured;
        snapshot.settingsError = value.payload.error ?? null;
        this.dependencies.publishSnapshot();
        break;
      case "runtime.settings.status":
        if ("error" in value.payload) {
          snapshot.settingsError = value.payload.error;
        } else {
          snapshot.runtimeSettings = value.payload;
          snapshot.settingsError = null;
        }
        this.dependencies.publishSnapshot();
        break;
      case "runtime.task.result":
        this.handleTaskResult(value.payload);
        break;
      case "debugger.command":
        this.dependencies.handleDebuggerCommand(value.payload);
        break;
      case "debugger.detach":
        this.dependencies.handleDetachRequest(value.payload);
        break;
    }
  };

  private handleHostHello(
    message: Extract<NativeHostMessage, { type: "host.hello" }>,
  ): void {
    const { snapshot, publishSnapshot } = this.dependencies;
    const { supportedProtocolVersions, debuggerMethods, debuggerEvents } = message.payload;
    const acceptedMethods = Array.isArray(debuggerMethods)
      ? debuggerMethods.filter((method): method is DebuggerMethod =>
          ALLOWED_DEBUGGER_METHODS.includes(method as DebuggerMethod),
        )
      : [];
    const validNegotiation =
      Array.isArray(supportedProtocolVersions) &&
      supportedProtocolVersions.includes(PROTOCOL_VERSION) &&
      message.payload.debuggerProtocolVersion === DEBUGGER_PROTOCOL_VERSION &&
      Array.isArray(debuggerMethods) &&
      acceptedMethods.length === debuggerMethods.length &&
      new Set(debuggerMethods).size === debuggerMethods.length &&
      Array.isArray(debuggerEvents) &&
      debuggerEvents.every((event) => ALLOWED_DEBUGGER_EVENTS.includes(event)) &&
      new Set(debuggerEvents).size === debuggerEvents.length;

    if (!validNegotiation) {
      this.setHostError("Native host sent an unsupported protocol or debugger allowlist.");
      this.nativePort?.disconnect();
      return;
    }
    this.negotiatedMethods.clear();
    acceptedMethods.forEach((method) => this.negotiatedMethods.add(method));
    this.negotiatedEvents.clear();
    debuggerEvents.forEach((event) => this.negotiatedEvents.add(event));
    snapshot.host = "connected";
    snapshot.hostError = null;
    this.hostNegotiated = true;
    snapshot.protocolReady = false;
    publishSnapshot();
  }

  private handleRuntimeSnapshot(
    message: Extract<NativeHostMessage, { type: "runtime.snapshot" }>,
  ): void {
    const { snapshot, publishSnapshot } = this.dependencies;
    const { session, events, pendingApproval } = message.payload;
    if (
      (session !== null && !isRuntimeSession(session)) ||
      !Array.isArray(events) ||
      !events.every(isTimelineEvent) ||
      (pendingApproval !== null && !isPendingApproval(pendingApproval))
    ) {
      this.setHostError("Native host sent an invalid runtime snapshot.");
      return;
    }
    snapshot.session = session;
    snapshot.protocolReady = true;
    snapshot.events = events.slice(-MAX_TIMELINE_EVENTS);
    snapshot.pendingApproval = pendingApproval;
    if (snapshot.attachment && snapshot.attachment.sessionId !== session?.sessionId) {
      void this.dependencies.detachOwnedTab(
        "The runtime session changed. Attach again to continue.",
        true,
      );
    }
    this.sequence = snapshot.events.reduce(
      (max, event) => Math.max(max, event.sequence),
      0,
    );
    publishSnapshot();
  }

  private handleRuntimeStatus(
    message: Extract<NativeHostMessage, { type: "runtime.status" }>,
  ): void {
    const { snapshot, publishSnapshot } = this.dependencies;
    if (!isRuntimeSession(message.payload.session)) {
      this.setHostError("Native host sent an invalid runtime session status.");
      return;
    }
    snapshot.session = message.payload.session;
    if (
      snapshot.attachment &&
      snapshot.attachment.sessionId !== message.payload.session.sessionId
    ) {
      void this.dependencies.detachOwnedTab(
        "The runtime session changed. Attach again to continue.",
        true,
      );
    }
    publishSnapshot();
  }

  private handleTimelineEvent(value: unknown): void {
    const { snapshot, publishSnapshot } = this.dependencies;
    if (!isTimelineEvent(value)) {
      this.setHostError("Native host sent an invalid timeline event.");
      return;
    }
    if (snapshot.session && value.sessionId !== snapshot.session.sessionId) return;
    if (value.sequence <= this.sequence) return;
    this.sequence = value.sequence;
    snapshot.events = [...snapshot.events, value].slice(-MAX_TIMELINE_EVENTS);
    publishSnapshot();
  }

  private handleApprovalRequired(value: unknown): void {
    if (!isPendingApproval(value)) {
      this.setHostError("Native host sent an invalid approval request.");
      return;
    }
    this.dependencies.snapshot.pendingApproval = value;
    this.dependencies.publishSnapshot();
  }

  private handleTaskResult(payload: Record<string, unknown>): void {
    const { snapshot, publishSnapshot } = this.dependencies;
    if (
      typeof payload.sessionId !== "string" ||
      !["verified_success", "stopped", "failed"].includes(String(payload.outcome)) ||
      typeof payload.summary !== "string" ||
      typeof payload.finishedAt !== "string"
    ) {
      this.setHostError("Native host sent an invalid task result.");
      return;
    }
    const status: TimelineEvent["status"] =
      payload.outcome === "verified_success" ? "completed" : "failed";
    if (snapshot.session?.sessionId === payload.sessionId) {
      snapshot.session = {
        ...snapshot.session,
        status: payload.outcome === "stopped" ? "stopped" : status,
        updatedAt: payload.finishedAt,
      };
    }
    snapshot.events = [
      ...snapshot.events,
      {
        eventId: crypto.randomUUID(),
        sessionId: payload.sessionId,
        sequence: this.sequence + 1,
        createdAt: payload.finishedAt,
        label:
          payload.outcome === "verified_success"
            ? "Task verified"
            : payload.outcome === "stopped"
              ? "Task stopped by user"
              : "Task failed",
        detail: payload.summary,
        status,
      },
    ].slice(-MAX_TIMELINE_EVENTS);
    this.sequence += 1;
    publishSnapshot();
  }
}

function isRuntimeSession(value: unknown): value is RuntimeSession {
  if (!isPlainRecord(value)) return false;
  return (
    typeof value.sessionId === "string" &&
    typeof value.updatedAt === "string" &&
    [
      "idle",
      "running",
      "paused",
      "awaiting_approval",
      "completed",
      "stopped",
      "failed",
    ].includes(String(value.status)) &&
    (value.taskLabel === undefined || typeof value.taskLabel === "string")
  );
}

function isPendingApproval(value: unknown): value is PendingApproval {
  return (
    isPlainRecord(value) &&
    typeof value.approvalId === "string" &&
    typeof value.sessionId === "string" &&
    typeof value.title === "string" &&
    typeof value.summary === "string" &&
    ["low", "medium", "high"].includes(String(value.risk)) &&
    (value.expiresAt === undefined || typeof value.expiresAt === "string")
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
