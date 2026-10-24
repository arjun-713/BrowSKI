import { describe, expect, it, vi } from "vitest";
import {
  AgentRelay,
  isDebuggableUrl,
  isRelayHostMessage,
  relayMethodAllowed,
  type AgentRelayDependencies,
  type RelaySocket,
  type RelayTab,
} from "./agent-relay";

const LEASE_ID = "0b0f6a8e-4c7e-4d55-9f43-1f7a3a2b9c10";
const RELAY_URL = "ws://127.0.0.1:43123/extension/abcdefghijklmnopqrstuvwxyz012345";

class FakeSocket implements RelaySocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readonly sent: Record<string, unknown>[] = [];

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  send(data: string): void {
    // Raw frames: "R {id}\n<result>" and "E {tabId, sessionId, method}\n<params>".
    if (data.startsWith("R ") || data.startsWith("E ")) {
      const newline = data.indexOf("\n");
      const header = JSON.parse(data.slice(2, newline)) as Record<string, unknown>;
      const body = JSON.parse(data.slice(newline + 1)) as unknown;
      this.sent.push(
        data.startsWith("R ")
          ? { type: "result", ...header, result: body }
          : { type: "event", ...header, params: body },
      );
      return;
    }
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(): void {
    this.readyState = 3;
  }

  receive(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function setup(
  active: RelayTab = { id: 7, url: "https://example.test/", windowId: 1, index: 2 },
) {
  const socket = new FakeSocket();
  let nextTab = 100;
  const dependencies = {
    activeTab: vi.fn(async () => active),
    createTab: vi.fn(async (properties: chrome.tabs.CreateProperties) => ({
      id: ++nextTab,
      url: properties.url,
      windowId: properties.windowId,
    })),
    removeTab: vi.fn(async () => undefined),
    activateTab: vi.fn(async () => undefined),
    attach: vi.fn(async () => undefined),
    detach: vi.fn(async () => undefined),
    sendCommand: vi.fn(async () => ({ result: { value: 2 } })),
    openSocket: vi.fn(() => socket),
    legacyAttached: vi.fn(() => false),
    onLeaseChanged: vi.fn(),
  } satisfies AgentRelayDependencies;
  const relay = new AgentRelay(dependencies);
  return { relay, socket, dependencies };
}

async function openLease(relay: AgentRelay, socket: FakeSocket): Promise<void> {
  relay.handleHostMessage({
    type: "relay.open",
    payload: { leaseId: LEASE_ID, url: RELAY_URL },
  });
  await vi.waitFor(() => expect(socket.onopen).not.toBeNull());
  socket.open();
  await vi.waitFor(() => expect(socket.sent.some((m) => m.type === "ready")).toBe(true));
}

describe("relay host messages", () => {
  it("accepts only loopback relay URLs with a token", () => {
    const valid = {
      protocolVersion: 1,
      type: "relay.open",
      eventId: "e",
      payload: { leaseId: LEASE_ID, url: RELAY_URL },
    };
    expect(isRelayHostMessage(valid)).toBe(true);
    expect(
      isRelayHostMessage({
        ...valid,
        payload: {
          leaseId: LEASE_ID,
          url: "ws://evil.test:1/extension/abcdefghijklmnopqrstuvwxyz",
        },
      }),
    ).toBe(false);
    expect(
      isRelayHostMessage({
        ...valid,
        payload: { leaseId: LEASE_ID, url: "ws://127.0.0.1:1/x" },
      }),
    ).toBe(false);
  });

  it("refuses cookie, storage and browser-level domains", () => {
    expect(relayMethodAllowed("Runtime.evaluate")).toBe(true);
    expect(relayMethodAllowed("Target.setAutoAttach")).toBe(true);
    expect(relayMethodAllowed("Network.getAllCookies")).toBe(false);
    expect(relayMethodAllowed("Storage.clearDataForOrigin")).toBe(false);
    expect(relayMethodAllowed("Browser.close")).toBe(false);
  });

  it("recognises pages Chrome will not debug", () => {
    expect(isDebuggableUrl("https://example.test/")).toBe(true);
    expect(isDebuggableUrl("about:blank")).toBe(true);
    expect(isDebuggableUrl("chrome://newtab/")).toBe(false);
    expect(isDebuggableUrl("https://chromewebstore.google.com/detail/x")).toBe(false);
  });
});

describe("AgentRelay", () => {
  it("attaches the active tab and forwards commands to it and its child sessions", async () => {
    const { relay, socket, dependencies } = setup();
    await openLease(relay, socket);
    expect(dependencies.attach).toHaveBeenCalledWith(7);
    expect(socket.sent.at(-1)).toMatchObject({ type: "ready", tabs: [{ tabId: 7 }] });

    socket.receive({
      type: "command",
      id: 1,
      tabId: 7,
      sessionId: null,
      method: "Runtime.evaluate",
      params: { expression: "1+1" },
    });
    socket.receive({
      type: "command",
      id: 2,
      tabId: 7,
      sessionId: "CHILD",
      method: "DOM.enable",
      params: {},
    });
    await vi.waitFor(() =>
      expect(socket.sent.filter((m) => m.type === "result")).toHaveLength(2),
    );
    expect(dependencies.sendCommand).toHaveBeenNthCalledWith(
      1,
      { tabId: 7 },
      "Runtime.evaluate",
      { expression: "1+1" },
    );
    expect(dependencies.sendCommand).toHaveBeenNthCalledWith(
      2,
      { tabId: 7, sessionId: "CHILD" },
      "DOM.enable",
      {},
    );
  });

  it("works beside a chrome:// tab instead of failing", async () => {
    const { relay, socket, dependencies } = setup({
      id: 3,
      url: "chrome://newtab/",
      windowId: 4,
      index: 0,
    });
    await openLease(relay, socket);
    expect(dependencies.createTab).toHaveBeenCalledWith({
      url: "about:blank",
      active: true,
      windowId: 4,
      index: 1,
    });
    expect(dependencies.attach).toHaveBeenCalledWith(101);
  });

  it("refuses tabs outside the lease and refused methods", async () => {
    const { relay, socket, dependencies } = setup();
    await openLease(relay, socket);
    socket.receive({
      type: "command",
      id: 1,
      tabId: 99,
      method: "Runtime.evaluate",
      params: {},
    });
    socket.receive({
      type: "command",
      id: 2,
      tabId: 7,
      method: "Network.getAllCookies",
      params: {},
    });
    await vi.waitFor(() =>
      expect(socket.sent.filter((m) => m.type === "result")).toHaveLength(2),
    );
    expect(dependencies.sendCommand).not.toHaveBeenCalled();
    expect(
      socket.sent
        .filter((m) => m.type === "result")
        .every((m) => typeof m.error === "string"),
    ).toBe(true);
  });

  it("adds tabs opened by a leased page and reports removal", async () => {
    const { relay, socket, dependencies } = setup();
    await openLease(relay, socket);
    relay.onTabCreated({ id: 8, openerTabId: 7, url: "", title: "" });
    relay.onTabCreated({ id: 9, openerTabId: 55, url: "", title: "" });
    await vi.waitFor(() =>
      expect(socket.sent.some((m) => m.type === "tabAdded")).toBe(true),
    );
    expect(dependencies.attach).toHaveBeenCalledWith(8);
    expect(dependencies.attach).not.toHaveBeenCalledWith(9);
    relay.onTabRemoved(8);
    expect(socket.sent.at(-1)).toEqual({ type: "tabRemoved", tabId: 8 });
  });

  it("reports a user cancel from Chrome's debugging bar", async () => {
    const { relay, socket } = setup();
    await openLease(relay, socket);
    expect(relay.onDebuggerDetach({ tabId: 7 }, "canceled_by_user")).toBe(true);
    expect(socket.sent.some((m) => m.type === "cancelled")).toBe(true);
    expect(relay.onDebuggerDetach({ tabId: 12 }, "target_closed")).toBe(false);
  });

  it("refuses to start while a Legacy tab is attached", async () => {
    const { relay, socket, dependencies } = setup();
    dependencies.legacyAttached.mockReturnValue(true);
    relay.handleHostMessage({
      type: "relay.open",
      payload: { leaseId: LEASE_ID, url: RELAY_URL },
    });
    await vi.waitFor(() => expect(socket.onopen).not.toBeNull());
    socket.open();
    await vi.waitFor(() => expect(socket.sent.some((m) => m.type === "failed")).toBe(true));
    expect(dependencies.attach).not.toHaveBeenCalled();
    expect(relay.active).toBe(false);
  });

  it("detaches every leased tab and keeps them open when the lease closes", async () => {
    const { relay, socket, dependencies } = setup();
    await openLease(relay, socket);
    relay.handleHostMessage({ type: "relay.close", payload: { leaseId: LEASE_ID } });
    await vi.waitFor(() => expect(relay.active).toBe(false));
    expect(dependencies.detach).toHaveBeenCalledWith(7);
    expect(dependencies.removeTab).not.toHaveBeenCalled();
  });
});
