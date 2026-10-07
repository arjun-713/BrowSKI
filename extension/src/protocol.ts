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
  "idle" | "running" | "awaiting_approval" | "completed" | "failed";

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
    | "ConfirmationRequired"
    | "RunPaused"
    | "RunStopped"
    | "RunCompleted"
    | "RunFailed";
  label: string;
  detail?: string;
  status: "info" | "running" | "completed" | "failed";
};

const RUNTIME_EVENT_TYPES = new Set<NonNullable<TimelineEvent["type"]>>([
  "RunStarted",
  "RunResumed",
  "ObservationCompleted",
  "DecisionMade",
  "ActionStarted",
  "ActionCompleted",
  "VerificationCompleted",
  "RecoveryStarted",
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
  | "Page.getLayoutMetrics"
  | "Page.getNavigationHistory"
  | "Page.handleJavaScriptDialog"
  | "Page.navigate"
  | "Page.navigateToHistoryEntry"
  | "Page.reload"
  | "Runtime.enable";

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
  | EventEnvelope<
      "runtime.task.result",
      {
        sessionId: string;
        outcome: "verified_success" | "failed";
        summary: string;
        finishedAt: string;
      }
    >
  | EventEnvelope<"debugger.command", DebuggerCommandRequest>
  | EventEnvelope<"debugger.detach", { attachmentId: string; reason: string }>;

export type ExtensionSnapshot = {
  host: "disconnected" | "connecting" | "connected" | "error";
  hostError: string | null;
  protocolReady: boolean;
  session: RuntimeSession | null;
  events: TimelineEvent[];
  pendingApproval: PendingApproval | null;
  openAiKeyConfigured: boolean;
  settingsError: string | null;
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
  return true;
}
