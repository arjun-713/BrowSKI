import {
  ALLOWED_DEBUGGER_EVENTS,
  ALLOWED_DEBUGGER_METHODS,
  DEBUGGER_PROTOCOL_VERSION,
  MAX_EXTENSION_TO_HOST_MESSAGE_BYTES,
  MAX_HOST_TO_EXTENSION_MESSAGE_BYTES,
  PROTOCOL_VERSION,
  isAllowedDebuggerCommand,
  isAllowedDebuggerEvent,
  isNativeHostMessage,
  isPlainRecord,
  isTimelineEvent,
  type DebuggerCommandRequest,
  type DebuggerMethod,
  type ExtensionSnapshot,
  type NativeHostMessage,
  type PendingApproval,
  type RuntimeSession,
  type TimelineEvent,
} from "../src/protocol";

const NATIVE_HOST_NAME = "com.browski.runtime";
const ATTACHMENT_STORAGE_KEY = "browserAttachment";
const SELECTED_TAB_STORAGE_KEY = "selectedBrowserTab";
const MAX_TIMELINE_EVENTS = 80;
const PANEL_CHANNEL = "extension.snapshot";

type Attachment = NonNullable<ExtensionSnapshot["attachment"]>;
type NativeEnvelope = {
  protocolVersion: typeof PROTOCOL_VERSION;
  type: string;
  requestId: string;
  payload: Record<string, unknown>;
};

const snapshot: ExtensionSnapshot = {
  host: "disconnected",
  hostError: null,
  protocolReady: false,
  session: null,
  events: [],
  pendingApproval: null,
  openAiKeyConfigured: false,
  settingsError: null,
  selectedTab: null,
  attachment: null,
};

let nativePort: chrome.runtime.Port | null = null;
let sequence = 0;
let debuggerEventSequence = 0;
const panelPorts = new Set<chrome.runtime.Port>();
const pendingDebuggerCommands = new Set<string>();
const seenDebuggerCommands = new Set<string>();
const debuggerCommandHistory: string[] = [];
const MAX_PENDING_DEBUGGER_COMMANDS = 8;
const MAX_SEEN_DEBUGGER_COMMANDS = 256;
const negotiatedDebuggerMethods = new Set<DebuggerMethod>();
const negotiatedDebuggerEvents = new Set<string>();

function requestId(): string {
  return crypto.randomUUID();
}

function sendToPanel(): void {
  for (const port of panelPorts) {
    try {
      port.postMessage({ type: PANEL_CHANNEL, snapshot: { ...snapshot } });
    } catch {
      panelPorts.delete(port);
    }
  }
}

function publishSnapshot(): void {
  sendToPanel();
}

function nativeEnvelope(type: string, payload: Record<string, unknown>): NativeEnvelope {
  return {
    protocolVersion: PROTOCOL_VERSION,
    type,
    requestId: requestId(),
    payload,
  };
}

function sendNative(type: string, payload: Record<string, unknown>): boolean {
  if (!nativePort) {
    return false;
  }

  const envelope = nativeEnvelope(type, payload);
  const encoded = JSON.stringify(envelope);
  if (new TextEncoder().encode(encoded).byteLength > MAX_EXTENSION_TO_HOST_MESSAGE_BYTES) {
    return false;
  }

  nativePort.postMessage(envelope);
  return true;
}

function setHostError(message: string): void {
  snapshot.host = "error";
  snapshot.hostError = message;
  snapshot.protocolReady = false;
  publishSnapshot();
}

function connectHost(): void {
  if (nativePort) {
    return;
  }

  snapshot.host = "connecting";
  snapshot.hostError = null;
  snapshot.protocolReady = false;
  publishSnapshot();

  try {
    const port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    nativePort = port;
    port.onMessage.addListener(onNativeMessage);
    port.onDisconnect.addListener(() => {
      const lastError = chrome.runtime.lastError?.message;
      nativePort = null;
      snapshot.protocolReady = false;
      negotiatedDebuggerMethods.clear();
      negotiatedDebuggerEvents.clear();
      void detachOwnedTab("The native runtime connection closed.", true);
      void clearSelectedTab();
      snapshot.host = lastError ? "error" : "disconnected";
      snapshot.hostError = lastError
        ? `Native host disconnected: ${lastError}`
        : "Native host connection closed.";
      publishSnapshot();
    });
    sendNative("extension.hello", {
      protocolVersions: [PROTOCOL_VERSION],
      debuggerProtocolVersion: DEBUGGER_PROTOCOL_VERSION,
      debuggerMethods: ALLOWED_DEBUGGER_METHODS,
      debuggerEvents: ALLOWED_DEBUGGER_EVENTS,
    });
  } catch (error) {
    setHostError(errorMessage(error));
  }
}

function disconnectHost(): void {
  void detachOwnedTab("Disconnected from the runtime by the user.", true);
  void clearSelectedTab();
  nativePort?.disconnect();
  nativePort = null;
  snapshot.host = "disconnected";
  snapshot.hostError = null;
  snapshot.protocolReady = false;
  negotiatedDebuggerMethods.clear();
  negotiatedDebuggerEvents.clear();
  publishSnapshot();
}

function isRuntimeSession(value: unknown): value is RuntimeSession {
  if (!isPlainRecord(value)) {
    return false;
  }

  return (
    typeof value.sessionId === "string" &&
    typeof value.updatedAt === "string" &&
    ["idle", "running", "awaiting_approval", "completed", "failed"].includes(
      String(value.status),
    ) &&
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

function onNativeMessage(value: unknown): void {
  if (
    new TextEncoder().encode(JSON.stringify(value)).byteLength >
    MAX_HOST_TO_EXTENSION_MESSAGE_BYTES
  ) {
    setHostError("Native host message exceeded the 1 MiB application limit.");
    nativePort?.disconnect();
    return;
  }

  if (!isNativeHostMessage(value)) {
    setHostError("Native host sent an unsupported protocol message.");
    return;
  }

  if (value.type === "host.hello") {
    handleHostHello(value);
    return;
  }

  if (!snapshot.protocolReady) {
    setHostError("Native host sent data before protocol negotiation completed.");
    return;
  }

  switch (value.type) {
    case "runtime.snapshot":
      handleRuntimeSnapshot(value);
      break;
    case "runtime.status":
      handleRuntimeStatus(value);
      break;
    case "runtime.timeline":
      handleTimelineEvent(value.payload.event);
      break;
    case "runtime.approval.required":
      handleApprovalRequired(value.payload.approval);
      break;
    case "runtime.approval.cleared":
      if (snapshot.pendingApproval?.approvalId === value.payload.approvalId) {
        snapshot.pendingApproval = null;
      }
      publishSnapshot();
      break;
    case "runtime.credentials.status":
      snapshot.openAiKeyConfigured = value.payload.openAiKeyConfigured;
      snapshot.settingsError = value.payload.error ?? null;
      publishSnapshot();
      break;
    case "runtime.task.result":
      handleTaskResult(value.payload);
      break;
    case "debugger.command":
      void handleDebuggerCommand(value.payload);
      break;
    case "debugger.detach":
      handleHostDetachRequest(value.payload);
      break;
  }
}

function handleHostHello(
  message: Extract<NativeHostMessage, { type: "host.hello" }>,
): void {
  const versions = message.payload.supportedProtocolVersions;
  const debuggerMethods = message.payload.debuggerMethods;
  const debuggerEvents = message.payload.debuggerEvents;
  const acceptedMethods = Array.isArray(debuggerMethods)
    ? debuggerMethods.filter((method): method is DebuggerMethod =>
        ALLOWED_DEBUGGER_METHODS.includes(method as DebuggerMethod),
      )
    : [];
  const validNegotiation =
    Array.isArray(versions) &&
    versions.includes(PROTOCOL_VERSION) &&
    message.payload.debuggerProtocolVersion === DEBUGGER_PROTOCOL_VERSION &&
    Array.isArray(debuggerMethods) &&
    acceptedMethods.length === debuggerMethods.length &&
    new Set(debuggerMethods).size === debuggerMethods.length &&
    Array.isArray(debuggerEvents) &&
    debuggerEvents.every((event) => ALLOWED_DEBUGGER_EVENTS.includes(event)) &&
    new Set(debuggerEvents).size === debuggerEvents.length;

  if (!validNegotiation) {
    setHostError("Native host sent an unsupported protocol or debugger allowlist.");
    nativePort?.disconnect();
    return;
  }

  negotiatedDebuggerMethods.clear();
  acceptedMethods.forEach((method) => negotiatedDebuggerMethods.add(method));
  negotiatedDebuggerEvents.clear();
  debuggerEvents.forEach((event) => negotiatedDebuggerEvents.add(event));
  snapshot.host = "connected";
  snapshot.hostError = null;
  snapshot.protocolReady = true;
  sendNative("runtime.snapshot.request", { afterSequence: sequence });
  publishSnapshot();
}

function handleRuntimeSnapshot(
  message: Extract<NativeHostMessage, { type: "runtime.snapshot" }>,
): void {
  const { session, events, pendingApproval } = message.payload;
  if (
    (session !== null && !isRuntimeSession(session)) ||
    !Array.isArray(events) ||
    !events.every(isTimelineEvent) ||
    (pendingApproval !== null && !isPendingApproval(pendingApproval))
  ) {
    setHostError("Native host sent an invalid runtime snapshot.");
    return;
  }

  snapshot.session = session;
  snapshot.events = events.slice(-MAX_TIMELINE_EVENTS);
  snapshot.pendingApproval = pendingApproval;
  if (snapshot.attachment && snapshot.attachment.sessionId !== session?.sessionId) {
    void detachOwnedTab("The runtime session changed. Attach again to continue.", true);
  }
  sequence = snapshot.events.reduce((max, event) => Math.max(max, event.sequence), 0);
  publishSnapshot();
}

function handleRuntimeStatus(
  message: Extract<NativeHostMessage, { type: "runtime.status" }>,
): void {
  if (!isRuntimeSession(message.payload.session)) {
    setHostError("Native host sent an invalid runtime session status.");
    return;
  }

  snapshot.session = message.payload.session;
  if (
    snapshot.attachment &&
    snapshot.attachment.sessionId !== message.payload.session.sessionId
  ) {
    void detachOwnedTab("The runtime session changed. Attach again to continue.", true);
  }
  publishSnapshot();
}

function handleTimelineEvent(value: unknown): void {
  if (!isTimelineEvent(value)) {
    setHostError("Native host sent an invalid timeline event.");
    return;
  }

  if (snapshot.session && value.sessionId !== snapshot.session.sessionId) {
    return;
  }
  if (value.sequence <= sequence) {
    return;
  }

  sequence = value.sequence;
  snapshot.events = [...snapshot.events, value].slice(-MAX_TIMELINE_EVENTS);
  publishSnapshot();
}

function handleApprovalRequired(value: unknown): void {
  if (!isPendingApproval(value)) {
    setHostError("Native host sent an invalid approval request.");
    return;
  }

  snapshot.pendingApproval = value;
  publishSnapshot();
}

function handleTaskResult(payload: Record<string, unknown>): void {
  if (
    typeof payload.sessionId !== "string" ||
    (payload.outcome !== "verified_success" && payload.outcome !== "failed") ||
    typeof payload.summary !== "string" ||
    typeof payload.finishedAt !== "string"
  ) {
    setHostError("Native host sent an invalid task result.");
    return;
  }

  const status: TimelineEvent["status"] =
    payload.outcome === "verified_success" ? "completed" : "failed";
  if (snapshot.session?.sessionId === payload.sessionId) {
    snapshot.session = { ...snapshot.session, status, updatedAt: payload.finishedAt };
  }
  snapshot.events = [
    ...snapshot.events,
    {
      eventId: requestId(),
      sessionId: payload.sessionId,
      sequence: sequence + 1,
      createdAt: payload.finishedAt,
      label: payload.outcome === "verified_success" ? "Task verified" : "Task failed",
      detail: payload.summary,
      status,
    },
  ].slice(-MAX_TIMELINE_EVENTS);
  sequence += 1;
  publishSnapshot();
}

async function handleDebuggerCommand(payload: unknown): Promise<void> {
  if (!isAllowedDebuggerCommand(payload)) {
    sendNative("debugger.command.result", {
      commandId: isPlainRecord(payload) ? payload.commandId : "unknown",
      error: "Debugger command or parameters are not allowlisted.",
    });
    return;
  }

  const attachment = snapshot.attachment;
  const commandKey = `${payload.attachmentId}:${payload.commandId}`;
  if (seenDebuggerCommands.has(commandKey)) {
    sendDebuggerError(payload, "Duplicate debugger command ID.");
    return;
  }
  if (pendingDebuggerCommands.size >= MAX_PENDING_DEBUGGER_COMMANDS) {
    sendDebuggerError(payload, "Too many debugger commands are already in flight.");
    return;
  }
  if (
    !attachment ||
    attachment.state === "error" ||
    attachment.attachmentId !== payload.attachmentId ||
    attachment.sessionId !== payload.sessionId ||
    snapshot.session?.sessionId !== payload.sessionId ||
    !negotiatedDebuggerMethods.has(payload.method)
  ) {
    sendDebuggerError(payload, "Command does not belong to the owned tab attachment.");
    return;
  }

  rememberDebuggerCommand(commandKey);
  pendingDebuggerCommands.add(commandKey);
  try {
    const result = await chrome.debugger.sendCommand(
      { tabId: attachment.tabId },
      payload.method,
      payload.params,
    );
    const sent = sendNative("debugger.command.result", {
      attachmentId: attachment.attachmentId,
      commandId: payload.commandId,
      sessionId: payload.sessionId,
      result: result ?? {},
    });
    if (!sent) {
      sendDebuggerError(payload, "Debugger result exceeded the message size limit.");
    }
  } catch (error) {
    sendDebuggerError(payload, errorMessage(error));
  } finally {
    pendingDebuggerCommands.delete(commandKey);
  }
}

function rememberDebuggerCommand(commandKey: string): void {
  seenDebuggerCommands.add(commandKey);
  debuggerCommandHistory.push(commandKey);
  if (debuggerCommandHistory.length > MAX_SEEN_DEBUGGER_COMMANDS) {
    const expired = debuggerCommandHistory.shift();
    if (expired) {
      seenDebuggerCommands.delete(expired);
    }
  }
}

function sendDebuggerError(payload: DebuggerCommandRequest, error: string): void {
  const sent = sendNative("debugger.command.result", {
    attachmentId: payload.attachmentId,
    commandId: payload.commandId,
    sessionId: payload.sessionId,
    error,
  });
  if (!sent) {
    setHostError("Could not send the debugger response to the native host.");
  }
}

async function captureActiveTab(): Promise<void> {
  if (!nativePort || !snapshot.protocolReady) {
    throw new Error("Connect to the local BROWSKI runtime before choosing a tab.");
  }
  if (snapshot.attachment) {
    throw new Error("Clear the current attachment before choosing another tab.");
  }
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (typeof tab?.id !== "number") {
    throw new Error("Chrome did not report an active tab in the focused window.");
  }
  snapshot.selectedTab = { tabId: tab.id, origin: allowedOrigin(tab.url) };
  await chrome.storage.session.set({ [SELECTED_TAB_STORAGE_KEY]: snapshot.selectedTab });
  publishSnapshot();
}

async function attachSelectedTab(): Promise<void> {
  if (!nativePort || !snapshot.protocolReady) {
    throw new Error("Connect to the local BROWSKI runtime before attaching a tab.");
  }
  if (snapshot.attachment) {
    throw new Error("A tab is already attached. Clear it before choosing another.");
  }
  const selectedTab = snapshot.selectedTab;
  if (!selectedTab) {
    throw new Error("Choose a tab and review its origin first.");
  }
  const currentTab = await chrome.tabs.get(selectedTab.tabId);
  if (allowedOrigin(currentTab.url) !== selectedTab.origin) {
    await clearSelectedTab();
    throw new Error("The selected tab navigated. Capture it again before attaching.");
  }
  await chrome.debugger.attach({ tabId: selectedTab.tabId }, "1.3");
  const session = snapshot.session ?? {
    sessionId: requestId(),
    updatedAt: new Date().toISOString(),
    status: "idle" as const,
  };
  snapshot.session = session;
  const attachment: Attachment = {
    attachmentId: requestId(),
    tabId: selectedTab.tabId,
    origin: selectedTab.origin,
    sessionId: session.sessionId,
    state: "attached",
    message: "Attached to the origin reviewed in this panel.",
  };
  snapshot.attachment = attachment;
  await chrome.storage.session.set({ [ATTACHMENT_STORAGE_KEY]: attachment });
  sendNative("browser.tab.attached", {
    attachmentId: attachment.attachmentId,
    tabId: attachment.tabId,
    origin: attachment.origin,
    sessionId: attachment.sessionId,
  });
  publishSnapshot();
}

function allowedOrigin(value: string | undefined): string {
  if (!value) {
    throw new Error("Chrome did not share this tab's origin.");
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Chrome did not share a valid HTTP or HTTPS tab origin.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only HTTP and HTTPS tabs can be attached.");
  }
  return parsed.origin;
}

async function clearSelectedTab(): Promise<void> {
  snapshot.selectedTab = null;
  await chrome.storage.session.remove(SELECTED_TAB_STORAGE_KEY);
  publishSnapshot();
}

async function detachOwnedTab(reason: string, retainError = false): Promise<void> {
  const attachment = snapshot.attachment;
  if (!attachment) {
    return;
  }

  snapshot.attachment = retainError
    ? { ...attachment, state: "error", message: reason }
    : null;
  if (retainError) {
    await clearSelectedTab();
  }
  await chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
  try {
    await chrome.debugger.detach({ tabId: attachment.tabId });
  } catch {
    // Chrome may already have detached because the tab closed or DevTools took over.
  }
  sendNative("browser.tab.detached", {
    attachmentId: attachment.attachmentId,
    reason,
  });
  publishSnapshot();
}

function handleHostDetachRequest(payload: Record<string, unknown>): void {
  if (
    typeof payload.attachmentId !== "string" ||
    payload.attachmentId !== snapshot.attachment?.attachmentId
  ) {
    return;
  }

  void detachOwnedTab(
    typeof payload.reason === "string" ? payload.reason : "Runtime requested detach.",
  );
}

function onDebuggerEvent(
  source: chrome.debugger.Debuggee,
  method: string,
  params?: object,
): void {
  const attachment = snapshot.attachment;
  if (
    !attachment ||
    source.tabId !== attachment.tabId ||
    ("sessionId" in source && source.sessionId !== undefined) ||
    !isAllowedDebuggerEvent(method) ||
    !negotiatedDebuggerEvents.has(method)
  ) {
    return;
  }

  const eventParams = (params ?? {}) as Record<string, unknown>;
  if (method === "Page.frameNavigated" && isTopFrame(eventParams.frame)) {
    let navigatedOrigin: string;
    try {
      navigatedOrigin = allowedOrigin(eventParams.frame.url);
    } catch {
      void detachOwnedTab("The attached tab navigated to an unsupported page.", true);
      return;
    }
    if (navigatedOrigin !== attachment.origin) {
      sendDebuggerEvent(attachment, method, eventParams);
      void detachOwnedTab(
        "The attached tab changed origin. Confirm it again to continue.",
        true,
      );
      return;
    }
  }
  const payload = {
    attachmentId: attachment.attachmentId,
    sessionId: attachment.sessionId,
    sequence: ++debuggerEventSequence,
    method,
    params: eventParams,
  };
  if (
    new TextEncoder().encode(JSON.stringify(payload)).byteLength >
    MAX_EXTENSION_TO_HOST_MESSAGE_BYTES
  ) {
    sendNative("browser.event.dropped", {
      attachmentId: attachment.attachmentId,
      method,
      reason: "event-size-limit",
    });
    return;
  }

  sendNative("debugger.event", payload);
  if (method === "Page.frameStartedLoading") {
    snapshot.attachment = {
      ...attachment,
      state: "navigating",
      message: "The attached tab is navigating; its tab identity remains fixed.",
    };
    publishSnapshot();
  } else if (method === "Page.frameStoppedLoading") {
    snapshot.attachment = {
      ...attachment,
      state: "attached",
      message: "The attached tab finished loading.",
    };
    publishSnapshot();
  }
}

function sendDebuggerEvent(
  attachment: Attachment,
  method: string,
  params: Record<string, unknown>,
): void {
  sendNative("debugger.event", {
    attachmentId: attachment.attachmentId,
    sessionId: attachment.sessionId,
    sequence: ++debuggerEventSequence,
    method,
    params,
  });
}

function isTopFrame(value: unknown): value is { url: string; parentId?: string } {
  return (
    isPlainRecord(value) && typeof value.url === "string" && value.parentId === undefined
  );
}

function onDebuggerDetach(source: chrome.debugger.Debuggee, reason: string): void {
  const attachment = snapshot.attachment;
  if (!attachment || source.tabId !== attachment.tabId) {
    return;
  }

  snapshot.attachment = {
    ...attachment,
    state: "error",
    message: `Chrome debugger detached: ${reason}. Reattach explicitly to continue.`,
  };
  void chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
  void clearSelectedTab();
  sendNative("browser.tab.detached", {
    attachmentId: attachment.attachmentId,
    reason,
  });
  publishSnapshot();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isPanelRequest(value: unknown): value is Record<string, unknown> {
  return isPlainRecord(value) && typeof value.type === "string";
}

export default defineBackground(() => {
  chrome.action.onClicked.addListener(async (tab) => {
    if (typeof tab.windowId === "number") {
      await chrome.sidePanel.open({ windowId: tab.windowId });
    }
  });

  chrome.debugger.onEvent.addListener(onDebuggerEvent);
  chrome.debugger.onDetach.addListener(onDebuggerDetach);

  chrome.tabs.onRemoved.addListener((tabId) => {
    if (snapshot.attachment?.tabId === tabId) {
      void detachOwnedTab("The attached tab was closed.");
    }
    if (snapshot.selectedTab?.tabId === tabId) {
      void clearSelectedTab();
    }
  });

  chrome.tabs.onActivated.addListener(({ tabId }) => {
    if (snapshot.attachment && snapshot.attachment.tabId !== tabId) {
      snapshot.attachment.message =
        "Another tab is active. BROWSKI remains attached to the original tab.";
      publishSnapshot();
    }
  });

  chrome.runtime.onConnect.addListener((port) => {
    if (port.name !== "browski-panel") {
      return;
    }
    panelPorts.add(port);
    port.onDisconnect.addListener(() => panelPorts.delete(port));
    port.postMessage({ type: PANEL_CHANNEL, snapshot: { ...snapshot } });
  });

  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (!isPanelRequest(message)) {
      return false;
    }

    const run = async (): Promise<unknown> => {
      switch (message.type) {
        case "panel.snapshot":
          return { ...snapshot };
        case "host.connect":
          connectHost();
          return { ...snapshot };
        case "host.disconnect":
          disconnectHost();
          return { ...snapshot };
        case "tab.captureActive":
          await captureActiveTab();
          return { ...snapshot };
        case "tab.attachSelected":
          await attachSelectedTab();
          return { ...snapshot };
        case "tab.detach":
          await detachOwnedTab("Detached by the user from the side panel.");
          return { ...snapshot };
        case "tab.clearSelection":
          await clearSelectedTab();
          return { ...snapshot };
        case "task.submit":
          if (!snapshot.protocolReady || !snapshot.session) {
            throw new Error("A runtime session is not available yet.");
          }
          if (typeof message.task !== "string" || message.task.trim().length === 0) {
            throw new Error("Enter a task before sending it to the runtime.");
          }
          if (message.task.length > 4000) {
            throw new Error("Tasks must be 4,000 characters or fewer.");
          }
          if (
            !sendNative("runtime.task.submit", {
              sessionId: snapshot.session.sessionId,
              task: message.task.trim(),
            })
          ) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        case "task.control": {
          if (!snapshot.protocolReady || !snapshot.session) {
            throw new Error("A runtime session is not available.");
          }
          const control = message.control;
          if (control !== "pause" && control !== "resume" && control !== "stop") {
            throw new Error("Choose a valid task control action.");
          }
          const latestRun = [...snapshot.events]
            .reverse()
            .find(
              (event) => event.runId && event.sessionId === snapshot.session?.sessionId,
            );
          if (!latestRun?.runId) {
            throw new Error("There is no active task run to control.");
          }
          if (
            !sendNative("runtime.task.control", {
              sessionId: snapshot.session.sessionId,
              runId: latestRun.runId,
              control,
            })
          ) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        }
        case "credentials.set": {
          if (!snapshot.protocolReady) {
            throw new Error("Connect the local runtime before saving credentials.");
          }
          if (typeof message.apiKey !== "string" || message.apiKey.trim().length === 0) {
            throw new Error("Enter an API key before saving.");
          }
          if (message.apiKey.length > 4096 || /[\r\n]/.test(message.apiKey)) {
            throw new Error("The API key is outside supported limits.");
          }
          if (!sendNative("runtime.credentials.set", { apiKey: message.apiKey })) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        }
        case "credentials.clear":
          if (!snapshot.protocolReady) {
            throw new Error("Connect the local runtime before removing credentials.");
          }
          if (!sendNative("runtime.credentials.clear", {})) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        case "approval.respond":
          if (!snapshot.pendingApproval || !snapshot.protocolReady) {
            throw new Error("There is no pending runtime approval.");
          }
          if (message.approvalId !== snapshot.pendingApproval.approvalId) {
            throw new Error("This approval request is no longer current.");
          }
          if (message.approved !== true && message.approved !== false) {
            throw new Error("Choose approve or deny for this request.");
          }
          if (
            !sendNative("runtime.approval.respond", {
              sessionId: snapshot.pendingApproval.sessionId,
              approvalId: snapshot.pendingApproval.approvalId,
              decision: message.approved ? "approve" : "deny",
            })
          ) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        default:
          throw new Error("This panel request is not supported.");
      }
    };

    void run()
      .then(respond)
      .catch((error: unknown) => {
        respond({ error: errorMessage(error), snapshot: { ...snapshot } });
      });
    return true;
  });

  void chrome.storage.session
    .get([ATTACHMENT_STORAGE_KEY, SELECTED_TAB_STORAGE_KEY])
    .then(async (value) => {
      const selected = value[SELECTED_TAB_STORAGE_KEY] as
        { tabId?: unknown; origin?: unknown } | undefined;
      if (typeof selected?.tabId === "number" && typeof selected.origin === "string") {
        try {
          const tab = await chrome.tabs.get(selected.tabId);
          if (allowedOrigin(tab.url) === selected.origin) {
            snapshot.selectedTab = { tabId: selected.tabId, origin: selected.origin };
          } else {
            await clearSelectedTab();
          }
        } catch {
          await clearSelectedTab();
        }
      }

      const restored = value[ATTACHMENT_STORAGE_KEY] as Attachment | undefined;
      if (!restored || typeof restored.tabId !== "number") {
        return;
      }

      const targets = await chrome.debugger.getTargets();
      const stillAttached = targets.some(
        (target) => target.tabId === restored.tabId && target.attached,
      );
      if (stillAttached) {
        if (
          snapshot.session?.sessionId === restored.sessionId &&
          snapshot.selectedTab?.tabId === restored.tabId &&
          snapshot.selectedTab.origin === restored.origin
        ) {
          snapshot.attachment = restored;
        } else {
          await chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
          snapshot.attachment = {
            ...restored,
            state: "error",
            message: "The runtime session changed. Attach again to continue.",
          };
          await chrome.debugger.detach({ tabId: restored.tabId }).catch(() => undefined);
        }
      } else {
        await chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
        snapshot.attachment = null;
      }
      publishSnapshot();
    });
});
