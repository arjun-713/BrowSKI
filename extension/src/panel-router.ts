import { isTrustedPanelSender } from "./panel-sender";
import {
  isPlainRecord,
  isRuntimeSettingsUpdate,
  isTaskPageUrl,
  isTaskVerification,
  type ExtensionSnapshot,
} from "./protocol";

type PanelRouterDependencies = {
  extensionId: string;
  getSnapshot: () => ExtensionSnapshot;
  sendNative: (type: string, payload: Record<string, unknown>) => boolean;
  connectHost: () => void;
  disconnectHost: () => void;
  captureActiveTab: () => Promise<void>;
  attachSelectedTab: () => Promise<void>;
  detachOwnedTab: (reason: string) => Promise<void>;
  clearSelectedTab: () => Promise<void>;
};

export function createPanelMessageHandler(dependencies: PanelRouterDependencies) {
  return (
    message: unknown,
    sender: chrome.runtime.MessageSender,
    respond: (response?: unknown) => void,
  ): boolean => {
    if (
      !isTrustedPanelSender(sender, dependencies.extensionId) ||
      !isPanelRequest(message)
    ) {
      return false;
    }

    const snapshot = dependencies.getSnapshot();
    const run = async (): Promise<unknown> => {
      switch (message.type) {
        case "panel.snapshot":
          return { ...snapshot };
        case "host.connect":
          dependencies.connectHost();
          return { ...snapshot };
        case "host.disconnect":
          dependencies.disconnectHost();
          return { ...snapshot };
        case "tab.captureActive":
          await dependencies.captureActiveTab();
          return { ...snapshot };
        case "tab.attachSelected":
          await dependencies.attachSelectedTab();
          return { ...snapshot };
        case "tab.detach":
          await dependencies.detachOwnedTab("Detached by the user from the side panel.");
          return { ...snapshot };
        case "tab.clearSelection":
          await dependencies.clearSelectedTab();
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
          if (message.startUrl !== undefined && !isTaskPageUrl(message.startUrl)) {
            throw new Error(
              "Choose a valid HTTP(S) starting page without embedded credentials.",
            );
          }
          if (
            message.verification !== undefined &&
            !isTaskVerification(message.verification)
          ) {
            throw new Error("Choose an expected HTTP(S) page URL and a non-empty heading.");
          }
          if (
            !dependencies.sendNative("runtime.task.submit", {
              sessionId: snapshot.session.sessionId,
              task: message.task.trim(),
              ...(typeof message.startUrl === "string" && message.startUrl.trim()
                ? { startUrl: message.startUrl.trim() }
                : {}),
              ...(message.verification !== undefined
                ? { verification: message.verification }
                : {}),
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
          const runId = snapshot.session.runId ?? latestRun?.runId;
          if (!runId) {
            throw new Error("There is no active task run to control.");
          }
          if (
            !dependencies.sendNative("runtime.task.control", {
              sessionId: snapshot.session.sessionId,
              runId,
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
          if (
            !dependencies.sendNative("runtime.credentials.set", { apiKey: message.apiKey })
          ) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        }
        case "credentials.clear":
          if (!snapshot.protocolReady) {
            throw new Error("Connect the local runtime before removing credentials.");
          }
          if (!dependencies.sendNative("runtime.credentials.clear", {})) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        case "settings.get":
          if (!snapshot.protocolReady) {
            throw new Error("Connect the local runtime before reading runtime settings.");
          }
          if (!dependencies.sendNative("runtime.settings.get", {})) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        case "settings.update": {
          if (!snapshot.protocolReady) {
            throw new Error("Connect the local runtime before changing runtime settings.");
          }
          const keys = [
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
          ];
          const settings = Object.fromEntries(
            keys
              .filter((key) => message[key] !== undefined)
              .map((key) => [key, message[key]]),
          );
          if (!isRuntimeSettingsUpdate(settings)) {
            throw new Error("Choose valid runtime settings before saving.");
          }
          if (!dependencies.sendNative("runtime.settings.update", settings)) {
            throw new Error("The native host is disconnected.");
          }
          return { ...snapshot };
        }
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
            !dependencies.sendNative("runtime.approval.respond", {
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
  };
}

function isPanelRequest(value: unknown): value is Record<string, unknown> {
  return isPlainRecord(value) && typeof value.type === "string";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
