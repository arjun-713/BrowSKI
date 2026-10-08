import { isMechanicalEvaluation, isMechanicalFunctionCall } from "./mechanical-scripts";

export const PROTOCOL_VERSION = 1 as const;
export const DEBUGGER_PROTOCOL_VERSION = 1 as const;
export const MAX_EXTENSION_TO_HOST_MESSAGE_BYTES = 8 * 1024 * 1024;
export const MAX_HOST_TO_EXTENSION_MESSAGE_BYTES = 1024 * 1024;

export type EventEnvelope<TType extends string, TPayload> = {
  protocolVersion: typeof PROTOCOL_VERSION;
  type: TType;
  eventId: string;
  payload: TPayload;
};

export type RuntimeStatus =
  "idle" | "running" | "paused" | "awaiting_approval" | "completed" | "stopped" | "failed";

export type RuntimeSession = {
  sessionId: string;
  status: RuntimeStatus;
  taskLabel?: string;
  updatedAt: string;
};

export type TimelineEvent = {
  eventId: string;
  sessionId: string;
  runId?: string;
  sequence: number;
  step?: number;
  createdAt: string;
  type?:
    | "RunStarted"
    | "RunResumed"
    | "ObservationCompleted"
    | "DecisionMade"
    | "ActionStarted"
    | "ActionCompleted"
    | "VerificationCompleted"
    | "RecoveryStarted"
    | "BrowserCodeStarted"
    | "BrowserCodeCompleted"
    | "ConfirmationRequired"
    | "RunPaused"
    | "RunStopped"
    | "RunCompleted"
    | "RunFailed";
  label: string;
  detail?: string;
  browserCode?: BrowserCodeTraceMetadata;
  status: "info" | "running" | "completed" | "failed";
};

export type BrowserCodeTraceMetadata = {
  purposeCategory: "semantic_data_transform";
  reasonCategory: "explicit_capability_request";
  scriptSha256: string;
  scriptBytes: number;
  timeoutMs: number;
  maxResultBytes: number;
  resultSchema: "BrowserCodePayload";
  durationMs?: number;
};

export type RuntimeSettingsUpdate = {
  effort: "none" | "low";
  privacyMode: "standard" | "privacy_first" | "offline";
  layaMode: "disabled" | "shadow";
  traceLevel: "standard" | "detailed";
};

export type RuntimeSettingsSnapshot = RuntimeSettingsUpdate & {
  confirmHighRiskActions: true;
  extensionTransport: "native_host" | "disabled";
};

export type RuntimeSettingsStatus = RuntimeSettingsSnapshot | { error: string };

const RUNTIME_EVENT_TYPES = new Set<NonNullable<TimelineEvent["type"]>>([
  "RunStarted",
  "RunResumed",
  "ObservationCompleted",
  "DecisionMade",
  "ActionStarted",
  "ActionCompleted",
  "VerificationCompleted",
  "RecoveryStarted",
  "BrowserCodeStarted",
  "BrowserCodeCompleted",
  "ConfirmationRequired",
  "RunPaused",
  "RunStopped",
  "RunCompleted",
  "RunFailed",
]);

export function isRuntimeEventType(
  value: unknown,
): value is NonNullable<TimelineEvent["type"]> {
  return (
    typeof value === "string" &&
    RUNTIME_EVENT_TYPES.has(value as NonNullable<TimelineEvent["type"]>)
  );
}

export function isTimelineEvent(value: unknown): value is TimelineEvent {
  return (
    isPlainRecord(value) &&
    typeof value.eventId === "string" &&
    value.eventId.length > 0 &&
    value.eventId.length <= 128 &&
    typeof value.sessionId === "string" &&
    value.sessionId.length > 0 &&
    value.sessionId.length <= 128 &&
    (value.runId === undefined ||
      (typeof value.runId === "string" && value.runId.length <= 128)) &&
    Number.isSafeInteger(value.sequence) &&
    Number(value.sequence) > 0 &&
    (value.step === undefined ||
      (Number.isSafeInteger(value.step) && Number(value.step) >= 0)) &&
    typeof value.createdAt === "string" &&
    value.createdAt.length <= 64 &&
    Number.isFinite(Date.parse(value.createdAt)) &&
    (value.type === undefined || isRuntimeEventType(value.type)) &&
    typeof value.label === "string" &&
    value.label.length > 0 &&
    value.label.length <= 160 &&
    (value.detail === undefined ||
      (typeof value.detail === "string" && value.detail.length <= 500)) &&
    (value.browserCode === undefined ||
      ((value.type === "BrowserCodeStarted" || value.type === "BrowserCodeCompleted") &&
        isBrowserCodeTraceMetadata(value.browserCode))) &&
    ["info", "running", "completed", "failed"].includes(String(value.status))
  );
}

export type PendingApproval = {
  approvalId: string;
  sessionId: string;
  title: string;
  summary: string;
  risk: "low" | "medium" | "high";
  expiresAt?: string;
};

export type DebuggerMethod =
  | "BROWSKI.tabs.activate"
  | "BROWSKI.tabs.close"
  | "BROWSKI.tabs.create"
  | "BROWSKI.tabs.stop"
  | "Accessibility.getFullAXTree"
  | "CSS.enable"
  | "CSS.getComputedStyleForNode"
  | "DOM.enable"
  | "DOM.focus"
  | "DOM.getBoxModel"
  | "DOM.getDocument"
  | "DOM.getNodeForLocation"
  | "DOM.resolveNode"
  | "DOM.scrollIntoViewIfNeeded"
  | "Input.dispatchKeyEvent"
  | "Input.dispatchMouseEvent"
  | "Input.insertText"
  | "Page.enable"
  | "Page.captureScreenshot"
  | "Page.getLayoutMetrics"
  | "Page.getNavigationHistory"
  | "Page.handleJavaScriptDialog"
  | "Page.navigate"
  | "Page.navigateToHistoryEntry"
  | "Page.reload"
  | "Runtime.enable"
  | "Runtime.evaluate"
  | "Runtime.callFunctionOn";

export type DebuggerEventMethod =
  | "Accessibility.loadComplete"
  | "Accessibility.nodesUpdated"
  | "DOM.attributeModified"
  | "DOM.attributeRemoved"
  | "DOM.characterDataModified"
  | "DOM.childNodeCountUpdated"
  | "DOM.childNodeInserted"
  | "DOM.childNodeRemoved"
  | "DOM.documentUpdated"
  | "DOM.setChildNodes"
  | "Target.targetDestroyed"
  | "Page.domContentEventFired"
  | "Page.frameAttached"
  | "Page.frameDetached"
  | "Page.frameNavigated"
  | "Page.frameStartedLoading"
  | "Page.frameStoppedLoading"
  | "Page.javascriptDialogClosed"
  | "Page.javascriptDialogOpening"
  | "Page.lifecycleEvent"
  | "Page.loadEventFired"
  | "Runtime.executionContextCreated"
  | "Runtime.executionContextDestroyed"
  | "Runtime.executionContextsCleared";

export type DebuggerCommandRequest = {
  attachmentId: string;
  commandId: string;
  sessionId: string;
  method: DebuggerMethod;
  params: Record<string, unknown>;
};

export type NativeHostMessage =
  | EventEnvelope<
      "host.hello",
      {
        supportedProtocolVersions: number[];
        debuggerProtocolVersion: number;
        debuggerMethods: string[];
        debuggerEvents: string[];
      }
    >
  | EventEnvelope<
      "runtime.snapshot",
      {
        session: RuntimeSession | null;
        events: TimelineEvent[];
        pendingApproval: PendingApproval | null;
      }
    >
  | EventEnvelope<"runtime.status", { session: RuntimeSession }>
  | EventEnvelope<"runtime.timeline", { event: TimelineEvent }>
  | EventEnvelope<"runtime.approval.required", { approval: PendingApproval }>
  | EventEnvelope<"runtime.approval.cleared", { approvalId: string }>
  | EventEnvelope<
      "runtime.credentials.status",
      { openAiKeyConfigured: boolean; error?: string }
    >
  | EventEnvelope<"runtime.settings.status", RuntimeSettingsStatus>
  | EventEnvelope<
      "runtime.task.result",
      {
        sessionId: string;
        outcome: "verified_success" | "stopped" | "failed";
        summary: string;
        finishedAt: string;
      }
    >
  | EventEnvelope<"debugger.command", DebuggerCommandRequest>
  | EventEnvelope<"debugger.detach", { attachmentId: string; reason: string }>;

export type ExtensionToHostMessage =
  | EventEnvelope<"runtime.settings.get", Record<string, never>>
  | EventEnvelope<"runtime.settings.update", RuntimeSettingsUpdate>;

function isRuntimeSettingsUpdate(value: Record<string, unknown>): boolean {
  return (
    hasOnlyKeys(value, ["effort", "privacyMode", "layaMode", "traceLevel"]) &&
    ["none", "low"].includes(String(value.effort)) &&
    ["standard", "privacy_first", "offline"].includes(String(value.privacyMode)) &&
    ["disabled", "shadow"].includes(String(value.layaMode)) &&
    ["standard", "detailed"].includes(String(value.traceLevel))
  );
}

function isRuntimeSettingsStatus(value: Record<string, unknown>): boolean {
  if (
    hasOnlyKeys(value, ["error"]) &&
    typeof value.error === "string" &&
    value.error.length > 0 &&
    value.error.length <= 200
  ) {
    return true;
  }
  const settings: Record<string, unknown> = {
    effort: value.effort,
    privacyMode: value.privacyMode,
    layaMode: value.layaMode,
    traceLevel: value.traceLevel,
  };
  return (
    hasOnlyKeys(value, [
      "effort",
      "privacyMode",
      "layaMode",
      "traceLevel",
      "confirmHighRiskActions",
      "extensionTransport",
    ]) &&
    isRuntimeSettingsUpdate(settings) &&
    value.confirmHighRiskActions === true &&
    ["native_host", "disabled"].includes(String(value.extensionTransport))
  );
}

export function isExtensionToHostMessage(value: unknown): value is ExtensionToHostMessage {
  if (
    !isPlainRecord(value) ||
    value.protocolVersion !== PROTOCOL_VERSION ||
    typeof value.eventId !== "string" ||
    value.eventId.length === 0 ||
    value.eventId.length > 128 ||
    typeof value.type !== "string" ||
    !isPlainRecord(value.payload)
  ) {
    return false;
  }
  if (value.type === "runtime.settings.get") {
    return (
      hasOnlyKeys(value, ["protocolVersion", "type", "eventId", "payload"]) &&
      Object.keys(value.payload).length === 0
    );
  }
  return (
    value.type === "runtime.settings.update" &&
    hasOnlyKeys(value, ["protocolVersion", "type", "eventId", "payload"]) &&
    isRuntimeSettingsUpdate(value.payload)
  );
}

export type ExtensionSnapshot = {
  host: "disconnected" | "connecting" | "connected" | "error";
  hostError: string | null;
  protocolReady: boolean;
  session: RuntimeSession | null;
  events: TimelineEvent[];
  pendingApproval: PendingApproval | null;
  openAiKeyConfigured: boolean;
  settingsError: string | null;
  runtimeSettings: RuntimeSettingsSnapshot | null;
  selectedTab: { tabId: number; origin: string } | null;
  attachment: {
    attachmentId: string;
    tabId: number;
    origin: string;
    sessionId: string;
    state: "attached" | "navigating" | "error";
    message: string;
  } | null;
};

export function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isOptionalNumber(value: unknown): boolean {
  return value === undefined || isFiniteNumber(value);
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || (typeof value === "string" && value.length <= 512);
}

function isOptionalBoolean(value: unknown): boolean {
  return value === undefined || typeof value === "boolean";
}

function isBrowserCodeTraceMetadata(value: unknown): value is BrowserCodeTraceMetadata {
  if (
    !isPlainRecord(value) ||
    !hasOnlyKeys(value, [
      "purposeCategory",
      "reasonCategory",
      "scriptSha256",
      "scriptBytes",
      "timeoutMs",
      "maxResultBytes",
      "resultSchema",
      "durationMs",
    ])
  ) {
    return false;
  }
  return (
    value.purposeCategory === "semantic_data_transform" &&
    value.reasonCategory === "explicit_capability_request" &&
    typeof value.scriptSha256 === "string" &&
    /^[0-9a-f]{64}$/.test(value.scriptSha256) &&
    Number.isInteger(value.scriptBytes) &&
    Number(value.scriptBytes) >= 1 &&
    Number(value.scriptBytes) <= 8_192 &&
    Number.isInteger(value.timeoutMs) &&
    Number(value.timeoutMs) >= 1 &&
    Number(value.timeoutMs) <= 1_500 &&
    Number.isInteger(value.maxResultBytes) &&
    Number(value.maxResultBytes) >= 1 &&
    Number(value.maxResultBytes) <= 16_384 &&
    value.resultSchema === "BrowserCodePayload" &&
    (value.durationMs === undefined ||
      (isFiniteNumber(value.durationMs) &&
        value.durationMs >= 0 &&
        value.durationMs <= 30_000))
  );
}

function onlyOptionalFields(
  params: Record<string, unknown>,
  validators: Record<string, (value: unknown) => boolean>,
): boolean {
  return (
    hasOnlyKeys(params, Object.keys(validators)) &&
    Object.entries(params).every(([key, value]) => validators[key]?.(value) === true)
  );
}

function isMouseParams(params: Record<string, unknown>): boolean {
  const allowed = [
    "type",
    "x",
    "y",
    "button",
    "clickCount",
    "deltaX",
    "deltaY",
    "modifiers",
  ];
  const types = ["mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"];
  const buttons = ["none", "left", "middle", "right", "back", "forward"];

  return (
    hasOnlyKeys(params, allowed) &&
    types.includes(String(params.type)) &&
    isFiniteNumber(params.x) &&
    isFiniteNumber(params.y) &&
    (params.button === undefined || buttons.includes(String(params.button))) &&
    isOptionalNumber(params.clickCount) &&
    isOptionalNumber(params.deltaX) &&
    isOptionalNumber(params.deltaY) &&
    isOptionalNumber(params.modifiers)
  );
}

function isKeyParams(params: Record<string, unknown>): boolean {
  const allowed = [
    "type",
    "key",
    "code",
    "text",
    "unmodifiedText",
    "windowsVirtualKeyCode",
    "nativeVirtualKeyCode",
    "modifiers",
  ];
  const types = ["keyDown", "keyUp", "rawKeyDown", "char"];

  return (
    hasOnlyKeys(params, allowed) &&
    types.includes(String(params.type)) &&
    typeof params.key === "string" &&
    params.key.length <= 128 &&
    isOptionalString(params.code) &&
    isOptionalString(params.text) &&
    isOptionalString(params.unmodifiedText) &&
    isOptionalNumber(params.windowsVirtualKeyCode) &&
    isOptionalNumber(params.nativeVirtualKeyCode) &&
    isOptionalNumber(params.modifiers)
  );
}

const parameterValidators: Record<
  DebuggerMethod,
  (params: Record<string, unknown>) => boolean
> = {
  "BROWSKI.tabs.activate": (params) =>
    hasOnlyKeys(params, ["targetId"]) && isOpaqueOwnedTargetId(params.targetId),
  "BROWSKI.tabs.close": (params) =>
    hasOnlyKeys(params, ["targetId"]) && isOpaqueOwnedTargetId(params.targetId),
  "BROWSKI.tabs.create": (params) =>
    hasOnlyKeys(params, ["url"]) &&
    typeof params.url === "string" &&
    isOwnedTabUrl(params.url),
  "BROWSKI.tabs.stop": (params) => Object.keys(params).length === 0,
  "Accessibility.getFullAXTree": (params) => Object.keys(params).length === 0,
  "CSS.enable": (params) => Object.keys(params).length === 0,
  "CSS.getComputedStyleForNode": (params) =>
    hasOnlyKeys(params, ["nodeId"]) && isFiniteNumber(params.nodeId),
  "DOM.enable": (params) => Object.keys(params).length === 0,
  "DOM.focus": (params) =>
    hasOnlyKeys(params, ["backendNodeId"]) && isFiniteNumber(params.backendNodeId),
  "DOM.getBoxModel": (params) =>
    hasOnlyKeys(params, ["backendNodeId"]) && isFiniteNumber(params.backendNodeId),
  "DOM.getDocument": (params) =>
    onlyOptionalFields(params, {
      depth: (value) => value === undefined || Number.isInteger(value),
      pierce: isOptionalBoolean,
    }),
  "DOM.getNodeForLocation": (params) =>
    hasOnlyKeys(params, ["x", "y"]) &&
    Number.isInteger(params.x) &&
    Number.isInteger(params.y),
  "DOM.resolveNode": (params) =>
    hasOnlyKeys(params, ["backendNodeId"]) && isFiniteNumber(params.backendNodeId),
  "DOM.scrollIntoViewIfNeeded": (params) =>
    hasOnlyKeys(params, ["backendNodeId"]) && isFiniteNumber(params.backendNodeId),
  "Input.dispatchKeyEvent": isKeyParams,
  "Input.dispatchMouseEvent": isMouseParams,
  "Input.insertText": (params) =>
    hasOnlyKeys(params, ["text"]) &&
    typeof params.text === "string" &&
    params.text.length <= 16_384,
  "Page.enable": (params) => Object.keys(params).length === 0,
  "Page.captureScreenshot": (params) =>
    hasOnlyKeys(params, ["format", "fromSurface", "captureBeyondViewport"]) &&
    params.format === "png" &&
    params.fromSurface === true &&
    params.captureBeyondViewport === false,
  "Page.getLayoutMetrics": (params) => Object.keys(params).length === 0,
  "Page.getNavigationHistory": (params) => Object.keys(params).length === 0,
  "Page.handleJavaScriptDialog": (params) =>
    hasOnlyKeys(params, ["accept", "promptText"]) &&
    typeof params.accept === "boolean" &&
    isOptionalString(params.promptText),
  "Page.navigate": (params) =>
    hasOnlyKeys(params, ["url"]) && typeof params.url === "string" && isWebUrl(params.url),
  "Page.navigateToHistoryEntry": (params) =>
    hasOnlyKeys(params, ["entryId"]) && Number.isInteger(params.entryId),
  "Page.reload": (params) =>
    onlyOptionalFields(params, {
      ignoreCache: isOptionalBoolean,
    }),
  "Runtime.enable": (params) => Object.keys(params).length === 0,
  "Runtime.evaluate": isMechanicalEvaluation,
  "Runtime.callFunctionOn": isMechanicalFunctionCall,
};

export const ALLOWED_DEBUGGER_METHODS = Object.freeze(
  Object.keys(parameterValidators) as DebuggerMethod[],
);

const allowedDebuggerEvents = new Set([
  "DOM.documentUpdated",
  "DOM.attributeModified",
  "DOM.attributeRemoved",
  "DOM.characterDataModified",
  "DOM.childNodeInserted",
  "DOM.childNodeRemoved",
  "DOM.childNodeCountUpdated",
  "DOM.setChildNodes",
  // This event is generated by our tab-ownership adapter when one supporting
  // tab is closed or detached; arbitrary Target commands remain unavailable.
  "Target.targetDestroyed",
  "Accessibility.loadComplete",
  "Accessibility.nodesUpdated",
  "Page.domContentEventFired",
  "Page.frameAttached",
  "Page.frameDetached",
  "Page.frameNavigated",
  "Page.frameStartedLoading",
  "Page.frameStoppedLoading",
  "Page.lifecycleEvent",
  "Page.loadEventFired",
  "Page.javascriptDialogClosed",
  "Page.javascriptDialogOpening",
  "Runtime.executionContextCreated",
  "Runtime.executionContextDestroyed",
  "Runtime.executionContextsCleared",
]);

export const ALLOWED_DEBUGGER_EVENTS = Object.freeze(Array.from(allowedDebuggerEvents));

export function isAllowedDebuggerCommand(value: unknown): value is DebuggerCommandRequest {
  if (!isPlainRecord(value) || !isPlainRecord(value.params)) {
    return false;
  }

  const method = value.method;
  if (
    typeof method !== "string" ||
    !Object.hasOwn(parameterValidators, method) ||
    !hasOnlyKeys(value, ["attachmentId", "commandId", "sessionId", "method", "params"])
  ) {
    return false;
  }

  return (
    typeof value.attachmentId === "string" &&
    value.attachmentId.length > 0 &&
    value.attachmentId.length <= 128 &&
    typeof value.commandId === "string" &&
    value.commandId.length > 0 &&
    value.commandId.length <= 128 &&
    typeof value.sessionId === "string" &&
    value.sessionId.length > 0 &&
    value.sessionId.length <= 128 &&
    parameterValidators[method as DebuggerMethod](value.params)
  );
}

function isWebUrl(value: string): boolean {
  if (value.length === 0 || value.length > 8192) {
    return false;
  }

  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function isOwnedTabUrl(value: string): boolean {
  if (value.length === 0 || new TextEncoder().encode(value).byteLength > 2048) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      parsed.hostname.length > 0 &&
      parsed.username.length === 0 &&
      parsed.password.length === 0 &&
      !Array.from(value).some((character) => {
        const code = character.charCodeAt(0);
        return code <= 0x20 || code === 0x7f;
      })
    );
  } catch {
    return false;
  }
}

function isOpaqueOwnedTargetId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 128 &&
    (/^extension-tab-[0-9a-f-]{36}$/i.test(value) ||
      /^browser-tab-[0-9a-f-]{36}$/i.test(value))
  );
}

export function isAllowedDebuggerEvent(method: string): boolean {
  return allowedDebuggerEvents.has(method);
}

const acceptedMessageTypes = new Set([
  "host.hello",
  "runtime.snapshot",
  "runtime.status",
  "runtime.timeline",
  "runtime.approval.required",
  "runtime.approval.cleared",
  "runtime.credentials.status",
  "runtime.settings.status",
  "runtime.task.result",
  "debugger.command",
  "debugger.detach",
]);

export function isNativeHostMessage(value: unknown): value is NativeHostMessage {
  if (!isPlainRecord(value) || value.protocolVersion !== PROTOCOL_VERSION) {
    return false;
  }

  const envelopeIsValid =
    typeof value.eventId === "string" &&
    value.eventId.length > 0 &&
    value.eventId.length <= 128 &&
    typeof value.type === "string" &&
    acceptedMessageTypes.has(value.type) &&
    isPlainRecord(value.payload);
  if (!envelopeIsValid) {
    return false;
  }
  if (value.type === "runtime.timeline") {
    return isPlainRecord(value.payload) && isTimelineEvent(value.payload.event);
  }
  if (value.type === "runtime.credentials.status") {
    const payload = value.payload;
    if (!isPlainRecord(payload)) {
      return false;
    }
    return (
      Object.keys(payload).every((key) => ["openAiKeyConfigured", "error"].includes(key)) &&
      typeof payload.openAiKeyConfigured === "boolean" &&
      (payload.error === undefined ||
        (typeof payload.error === "string" && payload.error.length <= 200))
    );
  }
  if (value.type === "runtime.settings.status") {
    return isPlainRecord(value.payload) && isRuntimeSettingsStatus(value.payload);
  }
  return true;
}
