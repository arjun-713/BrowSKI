import { OwnedPopups } from "./owned-popups";
import { allowedOrigin } from "./browser-origin";
import { OwnedTabs, type OwnedTabRecord } from "./owned-tabs";
import {
  MAX_EXTENSION_TO_HOST_MESSAGE_BYTES,
  isAllowedDebuggerCommand,
  isAllowedDebuggerEvent,
  isPlainRecord,
  type DebuggerCommandRequest,
  type DebuggerMethod,
  type ExtensionSnapshot,
} from "./protocol";

type Attachment = NonNullable<ExtensionSnapshot["attachment"]>;

export type DebuggerProxyDependencies = {
  getAttachment: () => Attachment | null;
  getNegotiatedMethods: () => ReadonlySet<DebuggerMethod>;
  getNegotiatedEvents: () => ReadonlySet<string>;
  ownedTabs: OwnedTabs;
  sendNative: (type: string, payload: Record<string, unknown>) => boolean;
  setHostError: (message: string) => void;
  persistOwnedTabs: () => Promise<void>;
  stopOwnedTabs: (attachment: Attachment) => Promise<void>;
  detachOwnedTab: (reason: string, retainError?: boolean) => Promise<void>;
  sendCommand: (
    tabId: number,
    method: DebuggerMethod,
    params: Record<string, unknown>,
  ) => Promise<unknown>;
  detachDebugger: (tabId: number) => Promise<void>;
  setInitialLoadingState: (state: "navigating" | "attached", message: string) => void;
};

const MAX_PENDING_COMMANDS = 8;
const MAX_SEEN_COMMANDS = 256;

export class DebuggerProxy {
  private readonly pendingCommands = new Set<string>();
  private readonly seenCommands = new Set<string>();
  private readonly commandHistory: string[] = [];
  private eventSequence = 0;

  private readonly popups: OwnedPopups;

  constructor(private readonly dependencies: DebuggerProxyDependencies) {
    this.popups = new OwnedPopups(dependencies.ownedTabs, dependencies.getAttachment);
  }

  onTabCreated(tab: Pick<chrome.tabs.Tab, "id" | "openerTabId">): void {
    this.popups.tabCreated(tab);
  }

  cancelPendingPopup(): void {
    this.popups.cancel();
  }

  async handleCommand(value: unknown): Promise<void> {
    if (!isAllowedDebuggerCommand(value)) {
      this.dependencies.sendNative("debugger.command.result", {
        commandId: isPlainRecord(value) ? value.commandId : "unknown",
        error: "Debugger command or parameters are not allowlisted.",
      });
      return;
    }

    const attachment = this.dependencies.getAttachment();
    const commandKey = `${value.attachmentId}:${value.commandId}`;
    if (this.seenCommands.has(commandKey)) {
      this.sendError(value, "Duplicate debugger command ID.");
      return;
    }
    if (this.pendingCommands.size >= MAX_PENDING_COMMANDS) {
      this.sendError(value, "Too many debugger commands are already in flight.");
      return;
    }
    if (
      !attachment ||
      attachment.state === "error" ||
      attachment.attachmentId !== value.attachmentId ||
      !this.dependencies.getNegotiatedMethods().has(value.method)
    ) {
      this.sendError(value, "Command does not belong to the owned tab attachment.");
      return;
    }
    const tab = this.dependencies.ownedTabs.getBySession(value.sessionId);
    if (
      !tab ||
      tab.attachmentId !== attachment.attachmentId ||
      tab.ownerSessionId !== attachment.sessionId
    ) {
      this.sendError(value, "Command targets a tab outside this owned session.");
      return;
    }

    this.rememberCommand(commandKey);
    this.pendingCommands.add(commandKey);
    try {
      if (value.method.startsWith("BROWSKI.tabs.")) {
        if (value.sessionId !== attachment.sessionId) {
          this.sendError(value, "Tab lifecycle commands must use the owning session.");
          return;
        }
        const result = await this.runOwnedTabCommand(value, attachment);
        this.sendResult(value, result);
        return;
      }
      const result = await this.dependencies.sendCommand(
        tab.chromeTabId,
        value.method,
        value.params,
      );
      this.sendResult(value, isPlainRecord(result) ? result : {});
    } catch (error) {
      this.sendError(
        value,
        value.method.startsWith("BROWSKI.tabs.")
          ? this.ownedTabFailureCategory(value.method)
          : errorMessage(error),
      );
    } finally {
      this.pendingCommands.delete(commandKey);
    }
  }

  onEvent(source: chrome.debugger.Debuggee, method: string, params?: object): void {
    const attachment = this.dependencies.getAttachment();
    if (!attachment || typeof source.tabId !== "number") return;
    const ownedTab = this.dependencies.ownedTabs.getByChromeTab(source.tabId);
    if (
      !ownedTab ||
      ownedTab.attachmentId !== attachment.attachmentId ||
      ("sessionId" in source && source.sessionId !== undefined)
    ) {
      return;
    }

    const eventParams = (params ?? {}) as Record<string, unknown>;
    // Browser-reported popup metadata is consumed only by the armed capability;
    // it is never exposed as an additional generic debugger event.
    if (method === "Page.windowOpen") {
      this.popups.windowOpened(source.tabId, eventParams);
      return;
    }
    if (
      !isAllowedDebuggerEvent(method) ||
      !this.dependencies.getNegotiatedEvents().has(method)
    ) {
      return;
    }
    if (method === "Page.frameNavigated" && isTopFrame(eventParams.frame)) {
      let navigatedOrigin: string;
      try {
        navigatedOrigin = allowedOrigin(eventParams.frame.url);
      } catch {
        if (ownedTab.initial) {
          void this.dependencies.detachOwnedTab(
            "The attached tab navigated to an unsupported page.",
            true,
          );
        } else {
          void this.invalidateOwnedTab(ownedTab);
        }
        return;
      }
      if (navigatedOrigin !== ownedTab.origin) {
        if (ownedTab.initial) {
          this.sendEvent(ownedTab, method, eventParams);
          void this.dependencies.detachOwnedTab(
            "The attached tab changed origin. Confirm it again to continue.",
            true,
          );
        } else {
          void this.invalidateOwnedTab(ownedTab);
        }
        return;
      }
    }

    const payload = {
      attachmentId: attachment.attachmentId,
      sessionId: ownedTab.tabSessionId,
      sequence: ++this.eventSequence,
      method,
      params: eventParams,
    };
    if (
      new TextEncoder().encode(JSON.stringify(payload)).byteLength >
      MAX_EXTENSION_TO_HOST_MESSAGE_BYTES
    ) {
      this.dependencies.sendNative("browser.event.dropped", {
        attachmentId: attachment.attachmentId,
        method,
        reason: "event-size-limit",
      });
      return;
    }

    this.dependencies.sendNative("debugger.event", payload);
    if (ownedTab.initial && method === "Page.frameStartedLoading") {
      this.dependencies.setInitialLoadingState(
        "navigating",
        "The attached tab is navigating; its tab identity remains fixed.",
      );
    } else if (ownedTab.initial && method === "Page.frameStoppedLoading") {
      this.dependencies.setInitialLoadingState(
        "attached",
        "The attached tab finished loading.",
      );
    }
  }

  onDetach(source: chrome.debugger.Debuggee, reason: string): void {
    const attachment = this.dependencies.getAttachment();
    if (!attachment || typeof source.tabId !== "number") return;
    const ownedTab = this.dependencies.ownedTabs.getByChromeTab(source.tabId);
    if (!ownedTab || ownedTab.attachmentId !== attachment.attachmentId) return;
    if (!ownedTab.initial) {
      const removed = this.dependencies.ownedTabs.detachByChromeTab(source.tabId);
      if (removed) {
        void this.dependencies.persistOwnedTabs();
        this.sendTargetDestroyed(removed);
      }
      return;
    }
    void this.dependencies.detachOwnedTab(
      `Chrome debugger detached: ${reason}. Reattach explicitly to continue.`,
      true,
    );
  }

  notifyTabDestroyed(ownedTab: OwnedTabRecord): void {
    this.sendTargetDestroyed(ownedTab);
  }

  private async runOwnedTabCommand(
    request: DebuggerCommandRequest,
    attachment: Attachment,
  ): Promise<Record<string, unknown>> {
    switch (request.method) {
      case "BROWSKI.tabs.preparePopup":
        return {
          popupId: this.popups.prepare(
            attachment.attachmentId,
            attachment.sessionId,
            request.params.openerSessionId as string,
            request.params.url as string,
          ),
        };
      case "BROWSKI.tabs.finishPopup": {
        const created = await this.popups.finish(
          attachment.attachmentId,
          attachment.sessionId,
          request.params.popupId as string,
          request.params.cancel as boolean,
        );
        if (created) await this.dependencies.persistOwnedTabs();
        return created ?? {};
      }
      case "BROWSKI.tabs.create": {
        const created = await this.dependencies.ownedTabs.create(
          attachment.attachmentId,
          attachment.sessionId,
          request.params.url as string,
          attachment.tabId,
        );
        await this.dependencies.persistOwnedTabs();
        return created;
      }
      case "BROWSKI.tabs.activate":
        await this.dependencies.ownedTabs.activate(
          attachment.attachmentId,
          attachment.sessionId,
          request.params.targetId as string,
        );
        return {};
      case "BROWSKI.tabs.close": {
        const removed = await this.dependencies.ownedTabs.close(
          attachment.attachmentId,
          attachment.sessionId,
          request.params.targetId as string,
        );
        this.sendTargetDestroyed(removed);
        await this.dependencies.persistOwnedTabs();
        return {};
      }
      case "BROWSKI.tabs.stop":
        await this.dependencies.stopOwnedTabs(attachment);
        return {};
      default:
        throw new Error("Unsupported owned-tab operation.");
    }
  }

  private async invalidateOwnedTab(ownedTab: OwnedTabRecord): Promise<void> {
    const removed = this.dependencies.ownedTabs.detachByChromeTab(ownedTab.chromeTabId);
    if (!removed) return;
    try {
      await this.dependencies.detachDebugger(removed.chromeTabId);
    } catch {
      // Chrome may already have detached because the tab closed or DevTools took over.
    }
    await this.dependencies.persistOwnedTabs();
    this.sendTargetDestroyed(removed);
  }

  private sendEvent(
    ownedTab: OwnedTabRecord,
    method: string,
    params: Record<string, unknown>,
  ): void {
    this.dependencies.sendNative("debugger.event", {
      attachmentId: ownedTab.attachmentId,
      sessionId: ownedTab.tabSessionId,
      sequence: ++this.eventSequence,
      method,
      params,
    });
  }

  private sendTargetDestroyed(ownedTab: OwnedTabRecord): void {
    this.dependencies.sendNative("debugger.event", {
      attachmentId: ownedTab.attachmentId,
      sessionId: ownedTab.tabSessionId,
      sequence: ++this.eventSequence,
      method: "Target.targetDestroyed",
      params: { targetId: ownedTab.targetId },
    });
  }

  private sendResult(
    request: DebuggerCommandRequest,
    result: Record<string, unknown>,
  ): void {
    const sent = this.dependencies.sendNative("debugger.command.result", {
      attachmentId: request.attachmentId,
      commandId: request.commandId,
      sessionId: request.sessionId,
      result,
    });
    if (!sent) this.sendError(request, "Debugger result exceeded the message size limit.");
  }

  private sendError(request: DebuggerCommandRequest, error: string): void {
    const sent = this.dependencies.sendNative("debugger.command.result", {
      attachmentId: request.attachmentId,
      commandId: request.commandId,
      sessionId: request.sessionId,
      error,
    });
    if (!sent)
      this.dependencies.setHostError(
        "Could not send the debugger response to the native host.",
      );
  }

  private rememberCommand(commandKey: string): void {
    this.seenCommands.add(commandKey);
    this.commandHistory.push(commandKey);
    if (this.commandHistory.length > MAX_SEEN_COMMANDS) {
      const expired = this.commandHistory.shift();
      if (expired) this.seenCommands.delete(expired);
    }
  }

  private ownedTabFailureCategory(method: DebuggerMethod): string {
    switch (method) {
      case "BROWSKI.tabs.create":
        return "Owned-tab creation failed or the URL was rejected.";
      case "BROWSKI.tabs.activate":
        return "The requested tab could not be activated.";
      case "BROWSKI.tabs.close":
        return "The requested supporting tab could not be closed.";
      case "BROWSKI.tabs.stop":
        return "Owned tab debuggers could not be detached.";
      default:
        return "Owned-tab operation failed.";
    }
  }
}

function isTopFrame(value: unknown): value is { url: string; parentId?: string } {
  return (
    isPlainRecord(value) && typeof value.url === "string" && value.parentId === undefined
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
