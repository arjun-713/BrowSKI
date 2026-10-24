import { MAX_OWNED_TABS, OwnedTabs, parseOwnedTabUrl } from "./owned-tabs";
import type { CreatedOwnedTab } from "./owned-tabs";

const POPUP_EXPECTATION_MS = 6_000;

type PopupOwner = {
  attachmentId: string;
  sessionId: string;
  state: string;
};

type PendingPopup = {
  id: string;
  attachmentId: string;
  ownerSessionId: string;
  openerSessionId: string;
  openerTabId: number;
  url: string;
  windowSeen: boolean;
  tabId?: number;
  finishing: boolean;
  error?: string;
  receipt: Promise<number | null>;
  resolve: (value: number | null) => void;
  timer: ReturnType<typeof setTimeout>;
};

/** Correlate one runtime click; never enumerate or discover existing tabs. */
export class OwnedPopups {
  private pending: PendingPopup | null = null;

  constructor(
    private readonly tabs: OwnedTabs,
    private readonly getOwner: () => PopupOwner | null,
  ) {}

  prepare(
    attachmentId: string,
    ownerSessionId: string,
    openerSessionId: string,
    url: string,
  ): string {
    const opener = this.tabs.getBySession(openerSessionId);
    const owner = this.getOwner();
    if (
      !owner ||
      owner.state === "error" ||
      owner.attachmentId !== attachmentId ||
      owner.sessionId !== ownerSessionId ||
      !opener ||
      opener.attachmentId !== attachmentId ||
      opener.ownerSessionId !== ownerSessionId
    ) {
      throw new Error("Popup opener is not owned by this attachment.");
    }
    if (this.pending) throw new Error("A popup expectation is already active.");
    if (this.tabs.size >= MAX_OWNED_TABS)
      throw new Error("The owned-tab limit has been reached.");
    const parsed = parseOwnedTabUrl(url);
    let resolve!: (value: number | null) => void;
    const receipt = new Promise<number | null>((accept) => {
      resolve = accept;
    });
    const pending: PendingPopup = {
      id: crypto.randomUUID(),
      attachmentId,
      ownerSessionId,
      openerSessionId,
      openerTabId: opener.chromeTabId,
      url: parsed.href,
      windowSeen: false,
      finishing: false,
      receipt,
      resolve,
      timer: setTimeout(
        () => this.invalidate(pending, "The expected popup did not arrive."),
        POPUP_EXPECTATION_MS,
      ),
    };
    this.pending = pending;
    return pending.id;
  }

  windowOpened(openerTabId: number, params: Record<string, unknown>): void {
    const pending = this.pending;
    if (!pending || pending.openerTabId !== openerTabId) return;
    if (
      !this.isCurrent(pending) ||
      pending.windowSeen ||
      params.userGesture !== true ||
      params.url !== pending.url ||
      typeof params.windowName !== "string" ||
      params.windowName.toLowerCase() !== "_blank"
    ) {
      this.invalidate(pending, "The popup did not match the requested native link.");
      return;
    }
    pending.windowSeen = true;
    this.resolveReceipt(pending);
  }

  tabCreated(tab: Pick<chrome.tabs.Tab, "id" | "openerTabId">): void {
    const pending = this.pending;
    if (!pending || tab.openerTabId !== pending.openerTabId) return;
    if (
      !this.isCurrent(pending) ||
      typeof tab.id !== "number" ||
      this.tabs.getByChromeTab(tab.id) ||
      pending.tabId !== undefined
    ) {
      this.invalidate(pending, "The popup identity is ambiguous or already owned.");
      return;
    }
    pending.tabId = tab.id;
    this.resolveReceipt(pending);
  }

  async finish(
    attachmentId: string,
    ownerSessionId: string,
    id: string,
    cancel: boolean,
  ): Promise<CreatedOwnedTab | null> {
    const pending = this.pending;
    if (
      !pending ||
      pending.id !== id ||
      pending.finishing ||
      pending.attachmentId !== attachmentId ||
      pending.ownerSessionId !== ownerSessionId
    ) {
      throw new Error("The popup expectation is no longer current.");
    }
    if (cancel) {
      this.invalidate(pending, "The browser input was cancelled.");
      return null;
    }
    pending.finishing = true;
    try {
      const tabId = await pending.receipt;
      clearTimeout(pending.timer);
      if (tabId === null || !this.isCurrent(pending)) {
        throw new Error(pending.error ?? "The popup attachment changed.");
      }
      return await this.tabs.adoptPopup(
        attachmentId,
        ownerSessionId,
        pending.url,
        tabId,
        () => this.isCurrent(pending),
      );
    } finally {
      this.invalidate(pending, "The popup expectation was consumed.");
    }
  }

  cancel(): void {
    if (this.pending) this.invalidate(this.pending, "The popup attachment ended.");
  }

  private isCurrent(pending: PendingPopup): boolean {
    const owner = this.getOwner();
    const opener = this.tabs.getBySession(pending.openerSessionId);
    return (
      this.pending === pending &&
      !pending.error &&
      Boolean(
        owner &&
        owner.state !== "error" &&
        owner.attachmentId === pending.attachmentId &&
        owner.sessionId === pending.ownerSessionId &&
        opener?.chromeTabId === pending.openerTabId &&
        opener?.attachmentId === pending.attachmentId &&
        opener?.ownerSessionId === pending.ownerSessionId,
      )
    );
  }

  private resolveReceipt(pending: PendingPopup): void {
    if (pending.windowSeen && pending.tabId !== undefined) pending.resolve(pending.tabId);
  }

  private invalidate(pending: PendingPopup, reason: string): void {
    clearTimeout(pending.timer);
    pending.error = reason;
    pending.resolve(null);
    if (this.pending === pending) this.pending = null;
  }
}
