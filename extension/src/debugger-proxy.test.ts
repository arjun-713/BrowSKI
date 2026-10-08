import { describe, expect, it, vi } from "vitest";
import { DebuggerProxy } from "./debugger-proxy";
import { OwnedTabs } from "./owned-tabs";
import type { DebuggerMethod } from "./protocol";

function createHarness() {
  const sent: Array<{ type: string; payload: Record<string, unknown> }> = [];
  const api = {
    createTab: vi.fn(async () => ({ id: 101 })),
    getDebuggerTarget: vi.fn(async () => ({
      title: "Supporting",
      url: "https://example.test/",
    })),
    attachDebugger: vi.fn(async (tabId: number) => void tabId),
    detachDebugger: vi.fn(async (tabId: number) => void tabId),
    activateTab: vi.fn(async (tabId: number) => void tabId),
    removeTab: vi.fn(async (tabId: number) => void tabId),
  };
  const ownedTabs = new OwnedTabs(api);
  const root = ownedTabs.registerInitial({
    attachmentId: "123e4567-e89b-12d3-a456-426614174000",
    ownerSessionId: "runtime-session",
    chromeTabId: 7,
    title: "Start",
    url: "https://example.test/",
    origin: "https://example.test",
  });
  const sendCommand = vi.fn(
    async (tabId: number, method: DebuggerMethod, params: Record<string, unknown>) => {
      void tabId;
      void method;
      void params;
      return { enabled: true };
    },
  );
  const proxy = new DebuggerProxy({
    getAttachment: () => ({
      attachmentId: root.attachmentId,
      tabId: root.chromeTabId,
      origin: root.origin,
      sessionId: root.ownerSessionId,
      state: "attached",
      message: "Attached",
    }),
    getNegotiatedMethods: () =>
      new Set<DebuggerMethod>(["BROWSKI.tabs.create", "BROWSKI.tabs.close", "Page.enable"]),
    getNegotiatedEvents: () => new Set(["Page.loadEventFired"]),
    ownedTabs,
    sendNative: (type, payload) => {
      sent.push({ type, payload });
      return true;
    },
    setHostError: vi.fn(),
    persistOwnedTabs: vi.fn(async () => undefined),
    stopOwnedTabs: vi.fn(async () => undefined),
    detachOwnedTab: vi.fn(async () => undefined),
    sendCommand,
    detachDebugger: api.detachDebugger,
    setInitialLoadingState: vi.fn(),
  });
  return { api, ownedTabs, proxy, root, sendCommand, sent };
}

describe("DebuggerProxy", () => {
  it("routes a CDP command only through the mapped per-tab Chrome identity", async () => {
    const { ownedTabs, proxy, root, sendCommand } = createHarness();
    const child = await ownedTabs.create(
      root.attachmentId,
      root.ownerSessionId,
      "https://example.test/search",
      root.chromeTabId,
    );

    await proxy.handleCommand({
      attachmentId: root.attachmentId,
      commandId: "command-1",
      sessionId: child.tabSessionId,
      method: "Page.enable",
      params: {},
    });

    expect(sendCommand).toHaveBeenCalledWith(101, "Page.enable", {});
  });

  it("refuses agent closure of the initial user tab", async () => {
    const { api, proxy, root, sent } = createHarness();

    await proxy.handleCommand({
      attachmentId: root.attachmentId,
      commandId: "command-1",
      sessionId: root.ownerSessionId,
      method: "BROWSKI.tabs.close",
      params: { targetId: root.targetId },
    });

    expect(api.removeTab).not.toHaveBeenCalled();
    expect(sent.at(-1)?.payload.error).toBe(
      "The requested supporting tab could not be closed.",
    );
  });

  it("routes debugger events to the matching opaque tab session", async () => {
    const { ownedTabs, proxy, root, sent } = createHarness();
    const child = await ownedTabs.create(
      root.attachmentId,
      root.ownerSessionId,
      "https://example.test/search",
      root.chromeTabId,
    );

    proxy.onEvent({ tabId: 101 }, "Page.loadEventFired", { timestamp: 1.25 });

    expect(sent.at(-1)).toMatchObject({
      type: "debugger.event",
      payload: {
        attachmentId: root.attachmentId,
        sessionId: child.tabSessionId,
        method: "Page.loadEventFired",
      },
    });
  });
});
