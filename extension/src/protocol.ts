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
  | "idle"
  | "running"
  | "paused"
  | "awaiting_approval"
  | "completed"
  | "stopped"
  | "failed"
  | "partially_completed"
  | "blocked"
  | "cancelled";

export type RuntimeSession = {
  sessionId: string;
  runId?: string;
  status: RuntimeStatus;
  taskLabel?: string;
  updatedAt: string;
  engine?: "fast" | "general" | "legacy";
  provider?: "laya" | "jev" | "openai" | "disabled";
  browserMode?: "managed" | "attached";
};

export type TimelineEvent = {
  eventId: string;
  sessionId: string;
  runId?: string;
  sequence: number;
  step?: number;
  createdAt: string;
  // Trace kinds are append-only diagnostics; unknown kinds cannot authorize actions.
  type?: string;
  label: string;
  detail?: string;
  pageUrl?: string;
  browserCode?: BrowserCodeTraceMetadata;
  browserSessionId?: string;
  requestId?: string;
  traceId?: string;
  stepId?: string;
  failure?: SafeFailureMetadata;
  status: "info" | "running" | "completed" | "failed";
};

export type SafeFailureMetadata = {
  component: string;
  operation: string;
  failureKind:
    | "GROUNDING"
    | "PLANNING"
    | "MEMORY"
    | "EXECUTION"
    | "VERIFICATION"
    | "RECOVERY"
    | "VISION"
    | "NAVIGATION"
    | "FRAME"
    | "TAB"
    | "UPLOAD"
    | "DOWNLOAD"
    | "AUTH"
    | "TIMEOUT"
    | "STAGNATION"
    | "SITE_BLOCK"
    | "MODEL_FORMAT"
    | "SAFETY"
    | "UNKNOWN";
  recoverable: boolean;
  category: "browser" | "provider" | "persistence" | "transport" | "runtime";
  debugId: string;
  safeMessage: string;
  nativeErrorType?: string;
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
  engine?: "fast" | "general" | "legacy";
  fastProvider?: "laya" | "jev";
  textProvider?: "disabled" | "openai";
  allowPaidApi?: boolean;
  textModel?: string;
  layaCheckpoint?: string;
  jevEndpoint?: string;
};

export function editableRuntimeSettings(
  settings: RuntimeSettingsUpdate,
): RuntimeSettingsUpdate {
  const {
    effort,
    privacyMode,
    layaMode,
    traceLevel,
    engine,
    fastProvider,
    textProvider,
    allowPaidApi,
    textModel,
    layaCheckpoint,
    jevEndpoint,
  } = settings;
  return {
    effort,
    privacyMode,
    layaMode,
    traceLevel,
    engine,
    fastProvider,
    textProvider,
    allowPaidApi,
    textModel,
    layaCheckpoint,
    jevEndpoint,
  };
}

export type RuntimeSettingsSnapshot = RuntimeSettingsUpdate & {
  confirmHighRiskActions: true;
  extensionTransport: "native_host" | "disabled";
};

export type RuntimeSettingsStatus = RuntimeSettingsSnapshot | { error: string };

const RUNTIME_EVENT_TYPES = new Set<NonNullable<TimelineEvent["type"]>>([
  "RunStarted",
  "RunResumed",
  "ObservationStarted",
  "ObservationCompleted",
  "DecisionStarted",
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
  "RunPartiallyCompleted",
  "RunBlocked",
  "RunCancelled",
]);

export function isKnownRuntimeEventType(
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
    isOptionalBoundedId(value.browserSessionId, 128) &&
    isOptionalBoundedId(value.requestId, 128) &&
    isOptionalBoundedId(value.traceId, 128) &&
    isOptionalBoundedId(value.stepId, 160) &&
    (value.type === undefined ||
      (typeof value.type === "string" && /^[A-Za-z][A-Za-z0-9]{0,63}$/.test(value.type))) &&
    typeof value.label === "string" &&
    value.label.length > 0 &&
    value.label.length <= 160 &&
    (value.detail === undefined ||
      (typeof value.detail === "string" && value.detail.length <= 500)) &&
    (value.pageUrl === undefined ||
      (typeof value.pageUrl === "string" &&
        value.pageUrl.length <= 2048 &&
        isOwnedTabUrl(value.pageUrl))) &&
    (value.browserCode === undefined ||
      ((value.type === "BrowserCodeStarted" || value.type === "BrowserCodeCompleted") &&
        isBrowserCodeTraceMetadata(value.browserCode))) &&
    (value.failure === undefined ||
      (value.type === "RunFailed" && isSafeFailureMetadata(value.failure))) &&
    ["info", "running", "completed", "failed"].includes(String(value.status))
  );
}

function isOptionalBoundedId(value: unknown, maximumLength: number): boolean {
  return (
    value === undefined ||
    (typeof value === "string" && value.length > 0 && value.length <= maximumLength)
  );
}

function isSafeFailureMetadata(value: unknown): value is SafeFailureMetadata {
  const failureKinds = [
    "GROUNDING",
    "PLANNING",
    "MEMORY",
    "EXECUTION",
    "VERIFICATION",
    "RECOVERY",
    "VISION",
    "NAVIGATION",
    "FRAME",
    "TAB",
    "UPLOAD",
    "DOWNLOAD",
    "AUTH",
    "TIMEOUT",
    "STAGNATION",
    "SITE_BLOCK",
    "MODEL_FORMAT",
    "SAFETY",
    "UNKNOWN",
  ];
  const categories = ["browser", "provider", "persistence", "transport", "runtime"];
  const nativeErrorTypes = [
    "FRAME_DETACHED",
    "TARGET_CLOSED",
    "COMMAND_TIMEOUT",
    "PROTOCOL_ERROR",
    "NAVIGATION_FAILED",
    "NO_ACTIVE_TAB",
    "INVALID_RESPONSE",
    "CONNECTION_LOST",
    "SESSION_CLOSED",
    "BRIDGE_JSON_DEPTH_LIMIT",
    "BRIDGE_MESSAGE_TOO_LARGE",
    "EXTENSION_COMMAND_REJECTED",
    "EXTENSION_SESSION_MISMATCH",
    "EXTENSION_COMMAND_TIMEOUT",
    "EXTENSION_BRIDGE_FAILURE",
    "OBSERVATION_TIMEOUT",
    "BROWSER_RUNTIME_FAILURE",
    "APIConnectionError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "RateLimitError",
    "InternalServerError",
  ];
  if (
    !isPlainRecord(value) ||
    !hasOnlyKeys(value, [
      "component",
      "operation",
      "failureKind",
      "recoverable",
      "category",
      "debugId",
      "safeMessage",
      "nativeErrorType",
    ])
  ) {
    return false;
  }
  return (
    typeof value.component === "string" &&
    /^[A-Za-z0-9_]{1,64}$/.test(value.component) &&
    typeof value.operation === "string" &&
    /^[A-Za-z0-9_]{1,64}$/.test(value.operation) &&
    failureKinds.includes(String(value.failureKind)) &&
    typeof value.recoverable === "boolean" &&
    categories.includes(String(value.category)) &&
    typeof value.debugId === "string" &&
    /^[0-9a-f]{32}$/.test(value.debugId) &&
    typeof value.safeMessage === "string" &&
    value.safeMessage.length > 0 &&
    value.safeMessage.length <= 200 &&
    (value.nativeErrorType === undefined ||
      (typeof value.nativeErrorType === "string" &&
        nativeErrorTypes.includes(value.nativeErrorType)))
  );
}

export type PendingApproval = {
  approvalId: string;
  sessionId: string;
  title: string;
  summary: string;
  risk: "low" | "medium" | "high";
  expiresAt?: string;
  details?: Record<string, unknown>;
};

export type DebuggerMethod =
  | "BROWSKI.tabs.activate"
  | "BROWSKI.tabs.close"
  | "BROWSKI.tabs.create"
  | "BROWSKI.tabs.preparePopup"
  | "BROWSKI.tabs.finishPopup"
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
  | EventEnvelope<"runtime.task.result", TaskResult>
  | EventEnvelope<"debugger.command", DebuggerCommandRequest>
  | EventEnvelope<"debugger.detach", { attachmentId: string; reason: string }>;

export type ExtensionToHostMessage =
  | EventEnvelope<"runtime.settings.get", Record<string, never>>
  | EventEnvelope<"runtime.settings.update", RuntimeSettingsUpdate>;

export function isRuntimeSettingsUpdate(value: Record<string, unknown>): boolean {
  return (
    hasOnlyKeys(value, [
      "effort",
      "privacyMode",
      "layaMode",
      "traceLevel",
      "engine",
      "fastProvider",
      "textProvider",
      "allowPaidApi",
      "textModel",
      "layaCheckpoint",
      "jevEndpoint",
    ]) &&
    ["none", "low"].includes(String(value.effort)) &&
    ["standard", "privacy_first", "offline"].includes(String(value.privacyMode)) &&
    ["disabled", "shadow"].includes(String(value.layaMode)) &&
    ["standard", "detailed"].includes(String(value.traceLevel)) &&
    (value.engine === undefined ||
      (typeof value.engine === "string" &&
        ["fast", "general", "legacy"].includes(value.engine))) &&
    (value.fastProvider === undefined ||
      (typeof value.fastProvider === "string" &&
        ["laya", "jev"].includes(value.fastProvider))) &&
    (value.textProvider === undefined ||
      (typeof value.textProvider === "string" &&
        ["disabled", "openai"].includes(value.textProvider))) &&
    (value.allowPaidApi === undefined || typeof value.allowPaidApi === "boolean") &&
    ["textModel", "layaCheckpoint", "jevEndpoint"].every(
      (key) =>
        value[key] === undefined ||
        (typeof value[key] === "string" &&
          value[key].length > 0 &&
          value[key].length <= 1000),
    )
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
  const settings: Record<string, unknown> = { ...value };
  delete settings.confirmHighRiskActions;
  delete settings.extensionTransport;
  return (
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

export type TaskResult = {
  sessionId: string;
  runId?: string;
  outcome:
    | "verified_success"
    | "stopped"
    | "failed"
    | "partially_completed"
    | "blocked"
    | "cancelled";
  summary: string;
  finishedAt: string;
  failure?: SafeFailureMetadata;
  answer?: string;
  verdict?: { verified: boolean; reason: string };
  stats?: { steps: number; actions: number; modelCalls: number; durationMs: number };
};

export type ExtensionSnapshot = {
  host: "disconnected" | "connecting" | "connected" | "error";
  hostError: string | null;
  protocolReady: boolean;
  session: RuntimeSession | null;
  events: TimelineEvent[];
  pendingApproval: PendingApproval | null;
  lastResult?: TaskResult;
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
  "BROWSKI.tabs.preparePopup": (params) =>
    hasOnlyKeys(params, ["url", "openerSessionId"]) &&
    typeof params.url === "string" &&
    isOwnedTabUrl(params.url) &&
    typeof params.openerSessionId === "string" &&
    params.openerSessionId.length > 0 &&
    params.openerSessionId.length <= 128,
  "BROWSKI.tabs.finishPopup": (params) =>
    hasOnlyKeys(params, ["popupId", "cancel"]) &&
    typeof params.popupId === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(params.popupId) &&
    typeof params.cancel === "boolean",
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

export function isTaskPageUrl(value: unknown): value is string {
  return typeof value === "string" && isOwnedTabUrl(value);
}

export function isTaskVerification(value: unknown): boolean {
  return (
    isPlainRecord(value) &&
    hasOnlyKeys(value, ["url", "heading"]) &&
    isTaskPageUrl(value.url) &&
    typeof value.heading === "string" &&
    value.heading.trim().length > 0 &&
    value.heading.length <= 200
  );
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
  if (value.type === "runtime.snapshot") {
    const payload = value.payload;
    return (
      isPlainRecord(payload) &&
      (payload.session === null || isRuntimeSession(payload.session)) &&
      Array.isArray(payload.events) &&
      payload.events.every(isTimelineEvent)
    );
  }
  if (value.type === "runtime.task.result") {
    const payload = value.payload;
    return (
      isPlainRecord(payload) &&
      typeof payload.sessionId === "string" &&
      payload.sessionId.length > 0 &&
      payload.sessionId.length <= 128 &&
      (payload.runId === undefined || isOptionalBoundedId(payload.runId, 128)) &&
      [
        "verified_success",
        "stopped",
        "failed",
        "partially_completed",
        "blocked",
        "cancelled",
      ].includes(String(payload.outcome)) &&
      typeof payload.summary === "string" &&
      payload.summary.length <= 2_000 &&
      typeof payload.finishedAt === "string" &&
      Number.isFinite(Date.parse(payload.finishedAt)) &&
      (payload.answer === undefined ||
        (typeof payload.answer === "string" && payload.answer.length <= 4000)) &&
      (payload.verdict === undefined ||
        (isPlainRecord(payload.verdict) &&
          typeof payload.verdict.verified === "boolean" &&
          typeof payload.verdict.reason === "string" &&
          payload.verdict.reason.length <= 500)) &&
      (payload.stats === undefined ||
        (isPlainRecord(payload.stats) &&
          ["steps", "actions", "modelCalls", "durationMs"].every(
            (key) =>
              Number.isSafeInteger((payload.stats as Record<string, unknown>)[key]) &&
              Number((payload.stats as Record<string, unknown>)[key]) >= 0,
          ))) &&
      (payload.failure === undefined ||
        (payload.outcome === "failed" && isSafeFailureMetadata(payload.failure)))
    );
  }
  if (value.type === "runtime.approval.cleared") {
    const payload = value.payload;
    return (
      isPlainRecord(payload) &&
      typeof payload.approvalId === "string" &&
      payload.approvalId.length > 0 &&
      payload.approvalId.length <= 128
    );
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

export function isRuntimeSession(value: unknown): value is RuntimeSession {
  return (
    isPlainRecord(value) &&
    typeof value.sessionId === "string" &&
    value.sessionId.length > 0 &&
    value.sessionId.length <= 128 &&
    (value.runId === undefined || isOptionalBoundedId(value.runId, 128)) &&
    [
      "idle",
      "running",
      "paused",
      "awaiting_approval",
      "completed",
      "stopped",
      "failed",
      "partially_completed",
      "blocked",
      "cancelled",
    ].includes(String(value.status)) &&
    (value.taskLabel === undefined ||
      (typeof value.taskLabel === "string" && value.taskLabel.length <= 200)) &&
    (value.engine === undefined ||
      (typeof value.engine === "string" &&
        ["fast", "general", "legacy"].includes(value.engine))) &&
    (value.provider === undefined ||
      (typeof value.provider === "string" &&
        ["laya", "jev", "openai", "disabled"].includes(value.provider))) &&
    (value.browserMode === undefined ||
      value.browserMode === "managed" ||
      value.browserMode === "attached") &&
    typeof value.updatedAt === "string" &&
    value.updatedAt.length <= 64 &&
    Number.isFinite(Date.parse(value.updatedAt))
  );
}
