import { PROTOCOL_VERSION, isPlainRecord } from "./protocol";

/**
 * Lets the local General agent drive the user's own tabs (ADR-032).
 *
 * The runtime sends `relay.open` over the authenticated Native Messaging port
 * with a one-use loopback WebSocket URL. This service worker connects to it,
 * attaches `chrome.debugger` to the active tab and forwards per-tab CDP traffic.
 * Only tabs in the lease are reachable: the starting tab, tabs the agent opens
 * and tabs those pages open. Unrelated tabs are never attached or reported.
 */

const RELAY_URL = /^ws:\/\/127\.0\.0\.1:\d{1,5}\/extension\/[A-Za-z0-9_-]{20,128}$/;
const KEEPALIVE_MS = 20_000;
const MAX_LEASED_TABS = 12;
const REFUSED_DOMAINS = [
  "Browser.",
  "Storage.",
  "SystemInfo.",
  "Tracing.",
  "IO.",
  "Fetch.",
];
const REFUSED_METHODS = new Set([
  "Network.getCookies",
  "Network.getAllCookies",
  "Network.setCookie",
  "Network.setCookies",
  "Network.deleteCookies",
  "Network.clearBrowserCookies",
  "Network.clearBrowserCache",
  "Page.setDownloadBehavior",
  "Target.createTarget",
  "Target.closeTarget",
  "Target.createBrowserContext",
  "Target.disposeBrowserContext",
  "Target.exposeDevToolsProtocol",
  "Target.setDiscoverTargets",
  "Target.setRemoteLocations",
]);

export type RelayHostMessage =
  | { type: "relay.open"; payload: { leaseId: string; url: string } }
  | { type: "relay.close"; payload: { leaseId: string } };

export type RelaySocket = {
  readonly readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
};

export type RelayTab = {
  id?: number;
  url?: string;
  title?: string;
  windowId?: number;
  index?: number;
};

export type AgentRelayDependencies = {
  activeTab: () => Promise<RelayTab | undefined>;
  createTab: (properties: chrome.tabs.CreateProperties) => Promise<RelayTab>;
  removeTab: (tabId: number) => Promise<void>;
  activateTab: (tabId: number) => Promise<void>;
  attach: (tabId: number) => Promise<void>;
  detach: (tabId: number) => Promise<void>;
  sendCommand: (
    target: { tabId: number; sessionId?: string },
    method: string,
    params: Record<string, unknown>,
  ) => Promise<unknown>;
  openSocket: (url: string) => RelaySocket;
  legacyAttached: () => boolean;
  onLeaseChanged: () => void;
};

type Lease = {
  leaseId: string;
  socket: RelaySocket;
  windowId?: number;
  tabs: Set<number>;
  keepalive: ReturnType<typeof setInterval>;
};

export function isRelayHostMessage(value: unknown): value is RelayHostMessage {
  if (
    !isPlainRecord(value) ||
    value.protocolVersion !== PROTOCOL_VERSION ||
    !isPlainRecord(value.payload) ||
    typeof value.payload.leaseId !== "string" ||
    !/^[0-9a-f-]{36}$/.test(value.payload.leaseId)
  ) {
    return false;
  }
  if (value.type === "relay.close") return true;
  return (
    value.type === "relay.open" &&
    typeof value.payload.url === "string" &&
    RELAY_URL.test(value.payload.url)
  );
}

export function relayMethodAllowed(method: string): boolean {
  return (
    !REFUSED_DOMAINS.some((domain) => method.startsWith(domain)) &&
    !REFUSED_METHODS.has(method)
  );
}

export function isDebuggableUrl(url: string | undefined): boolean {
  if (!url) return false;
  if (url === "about:blank") return true;
  try {
    const parsed = new URL(url);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      parsed.hostname !== "chromewebstore.google.com" &&
      !(parsed.hostname === "chrome.google.com" && parsed.pathname.startsWith("/webstore"))
    );
  } catch {
    return false;
  }
}

export class AgentRelay {
  private lease: Lease | null = null;

  constructor(private readonly dependencies: AgentRelayDependencies) {}

  get active(): boolean {
    return this.lease !== null;
  }

  isLeasedTab(tabId: number): boolean {
    return this.lease?.tabs.has(tabId) ?? false;
  }

  leasedTabs(): number[] {
    return [...(this.lease?.tabs ?? [])];
  }

  handleHostMessage(message: RelayHostMessage): void {
    if (message.type === "relay.open") {
      void this.open(message.payload.leaseId, message.payload.url);
    } else if (this.lease?.leaseId === message.payload.leaseId) {
      void this.end();
    }
  }

  private async open(leaseId: string, url: string): Promise<void> {
    if (this.lease) await this.end();
    const socket = this.dependencies.openSocket(url);
    const lease: Lease = {
      leaseId,
      socket,
      tabs: new Set(),
      keepalive: setInterval(() => this.send({ type: "ping" }), KEEPALIVE_MS),
    };
    this.lease = lease;
    socket.onmessage = (event) => {
      if (typeof event.data === "string") void this.onSocketMessage(lease, event.data);
    };
    socket.onclose = () => {
      if (this.lease === lease) void this.end();
    };
    socket.onerror = () => socket.close();
    socket.onopen = () => {
      void this.start(lease).catch((error: unknown) =>
        this.fail(lease, safeReason(error, "The current tab could not be controlled.")),
      );
    };
  }

  private async start(lease: Lease): Promise<void> {
    if (this.dependencies.legacyAttached()) {
      throw new Error("Detach the Legacy tab in Settings before running a task.");
    }
    let tab = await this.dependencies.activeTab();
    if (typeof tab?.id !== "number") {
      throw new Error("Chrome did not report an active tab in this window.");
    }
    if (!isDebuggableUrl(tab.url)) {
      // Chrome pages and the new-tab page cannot be debugged: work beside them.
      tab = await this.dependencies.createTab({
        url: "about:blank",
        active: true,
        ...(typeof tab.windowId === "number" ? { windowId: tab.windowId } : {}),
        ...(typeof tab.index === "number" ? { index: tab.index + 1 } : {}),
      });
    }
    if (typeof tab.id !== "number") throw new Error("Chrome did not create a working tab.");
    lease.windowId = tab.windowId;
    await this.attachTab(lease, tab.id);
    this.send({ type: "ready", tabs: [tabInfo(tab)] });
  }

  private async attachTab(lease: Lease, tabId: number): Promise<void> {
    await this.dependencies.attach(tabId);
    if (this.lease !== lease) {
      await this.dependencies.detach(tabId).catch(() => undefined);
      throw new Error("The browser task ended while a tab was attaching.");
    }
    lease.tabs.add(tabId);
    this.dependencies.onLeaseChanged();
  }

  private async onSocketMessage(lease: Lease, raw: string): Promise<void> {
    let message: unknown;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (!isPlainRecord(message) || typeof message.type !== "string") return;
    if (message.type === "close") {
      await this.end();
      return;
    }
    if (typeof message.id !== "number") return;
    try {
      const result = await this.runCommand(lease, message);
      this.sendRaw("R ", { id: message.id }, result);
    } catch (error) {
      this.send({
        type: "result",
        id: message.id,
        error: safeReason(error, "Command failed."),
      });
    }
  }

  private async runCommand(
    lease: Lease,
    message: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    switch (message.type) {
      case "command":
        return this.forward(lease, message);
      case "createTab":
        return { tab: await this.createAgentTab(lease, message) };
      case "closeTab":
        await this.dependencies.removeTab(this.leasedTabId(lease, message.tabId));
        return {};
      case "activateTab":
        await this.dependencies.activateTab(this.leasedTabId(lease, message.tabId));
        return {};
      default:
        throw new Error("Unknown relay command.");
    }
  }

  private async forward(
    lease: Lease,
    message: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const tabId = this.leasedTabId(lease, message.tabId);
    const method = message.method;
    if (typeof method !== "string" || !relayMethodAllowed(method)) {
      throw new Error("This browser operation is not available to the agent.");
    }
    const params = isPlainRecord(message.params) ? message.params : {};
    const target =
      typeof message.sessionId === "string"
        ? { tabId, sessionId: message.sessionId }
        : { tabId };
    const result = await this.dependencies.sendCommand(target, method, params);
    return isPlainRecord(result) ? result : {};
  }

  private async createAgentTab(
    lease: Lease,
    message: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const url = typeof message.url === "string" ? message.url : "about:blank";
    if (!isDebuggableUrl(url)) throw new Error("The agent may only open web pages.");
    if (lease.tabs.size >= MAX_LEASED_TABS)
      throw new Error("The agent tab limit was reached.");
    const tab = await this.dependencies.createTab({
      url,
      active: message.background !== true,
      ...(typeof lease.windowId === "number" ? { windowId: lease.windowId } : {}),
    });
    if (typeof tab.id !== "number") throw new Error("Chrome did not create the tab.");
    await this.attachTab(lease, tab.id);
    return tabInfo(tab);
  }

  private leasedTabId(lease: Lease, value: unknown): number {
    if (typeof value !== "number" || !lease.tabs.has(value)) {
      throw new Error("That tab is not part of this task.");
    }
    return value;
  }

  /** Returns true when the event belonged to the relay. */
  onDebuggerEvent(
    source: chrome.debugger.Debuggee & { sessionId?: string },
    method: string,
    params?: object,
  ): boolean {
    if (typeof source.tabId !== "number" || !this.isLeasedTab(source.tabId)) return false;
    this.sendRaw(
      "E ",
      { tabId: source.tabId, sessionId: source.sessionId ?? null, method },
      params ?? {},
    );
    return true;
  }

  onDebuggerDetach(source: chrome.debugger.Debuggee, reason: string): boolean {
    const lease = this.lease;
    if (!lease || typeof source.tabId !== "number" || !lease.tabs.has(source.tabId)) {
      return false;
    }
    lease.tabs.delete(source.tabId);
    if (reason === "canceled_by_user") {
      this.send({
        type: "cancelled",
        reason: "You stopped the agent from Chrome's debugging bar.",
      });
    }
    this.send({ type: "tabRemoved", tabId: source.tabId });
    this.dependencies.onLeaseChanged();
    return true;
  }

  onTabCreated(tab: RelayTab & { openerTabId?: number }): void {
    const lease = this.lease;
    if (
      !lease ||
      typeof tab.id !== "number" ||
      typeof tab.openerTabId !== "number" ||
      !lease.tabs.has(tab.openerTabId) ||
      lease.tabs.has(tab.id) ||
      lease.tabs.size >= MAX_LEASED_TABS
    ) {
      return;
    }
    const tabId = tab.id;
    void this.attachTab(lease, tabId)
      .then(() => this.send({ type: "tabAdded", tab: tabInfo(tab) }))
      .catch(() => {
        // Pages Chrome refuses to debug (for example chrome:// popups) stay unowned.
      });
  }

  onTabUpdated(tabId: number, tab: RelayTab): void {
    if (this.isLeasedTab(tabId))
      this.send({ type: "tabUpdated", tab: tabInfo({ ...tab, id: tabId }) });
  }

  onTabRemoved(tabId: number): void {
    const lease = this.lease;
    if (!lease?.tabs.delete(tabId)) return;
    this.send({ type: "tabRemoved", tabId });
    this.dependencies.onLeaseChanged();
  }

  private fail(lease: Lease, reason: string): void {
    if (this.lease !== lease) return;
    this.send({ type: "failed", reason });
    void this.end();
  }

  async end(): Promise<void> {
    const lease = this.lease;
    if (!lease) return;
    this.lease = null;
    clearInterval(lease.keepalive);
    await Promise.all(
      [...lease.tabs].map((tabId) =>
        this.dependencies.detach(tabId).catch(() => undefined),
      ),
    );
    try {
      lease.socket.close();
    } catch {
      // The runtime may already have closed the socket.
    }
    this.dependencies.onLeaseChanged();
  }

  private send(message: Record<string, unknown>): void {
    this.sendText(JSON.stringify(message));
  }

  /**
   * Large CDP payloads (DOM, accessibility, snapshots) go as a small JSON header
   * line plus the raw body, so the runtime forwards the body without parsing it.
   */
  private sendRaw(kind: "R " | "E ", header: Record<string, unknown>, body: object): void {
    this.sendText(`${kind}${JSON.stringify(header)}\n${JSON.stringify(body)}`);
  }

  private sendText(text: string): void {
    const socket = this.lease?.socket;
    if (!socket || socket.readyState !== 1) return;
    try {
      socket.send(text);
    } catch {
      // A closing socket ends the lease through onclose.
    }
  }
}

function tabInfo(tab: RelayTab): Record<string, unknown> {
  return { tabId: tab.id, url: tab.url ?? "about:blank", title: tab.title ?? "" };
}

function safeReason(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message.slice(0, 300) : fallback;
}
