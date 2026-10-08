/**
 * Attachment-scoped extension tab ownership.
 *
 * Chrome tab IDs stay inside this module. Callers see only fresh opaque target
 * and session IDs that are scoped to the owning attachment.
 */
export const MAX_OWNED_TABS = 8;
export const MAX_OWNED_TAB_URL_BYTES = 2048;

export type OwnedTabIdentity = {
  attachmentId: string;
  ownerSessionId: string;
  targetId: string;
  tabSessionId: string;
  title: string;
  url: string;
  origin: string;
  initial: boolean;
};

export type OwnedTabRecord = OwnedTabIdentity & { chromeTabId: number };

export type OwnedTabApi = {
  createTab: (properties: {
    url: string;
    active: false;
    openerTabId?: number;
  }) => Promise<{ id?: number; title?: string; url?: string }>;
  getDebuggerTarget: (
    tabId: number,
  ) => Promise<{ title?: string; url?: string } | undefined>;
  attachDebugger: (tabId: number) => Promise<void>;
  detachDebugger: (tabId: number) => Promise<void>;
  activateTab: (tabId: number) => Promise<void>;
  removeTab: (tabId: number) => Promise<void>;
};

export type CreatedOwnedTab = Pick<
  OwnedTabRecord,
  "targetId" | "tabSessionId" | "title" | "url" | "origin"
>;

export class OwnedTabs {
  private readonly byTarget = new Map<string, OwnedTabRecord>();
  private readonly bySession = new Map<string, OwnedTabRecord>();

  constructor(private readonly api: OwnedTabApi) {}

  registerInitial(input: {
    attachmentId: string;
    ownerSessionId: string;
    chromeTabId: number;
    title: string;
    url: string;
    origin: string;
  }): OwnedTabRecord {
    if (this.byTarget.size !== 0 || this.bySession.size !== 0) {
      throw new Error("An owned tab set is already active.");
    }
    const record: OwnedTabRecord = {
      ...input,
      targetId: `extension-tab-${input.attachmentId}`,
      tabSessionId: input.ownerSessionId,
      initial: true,
    };
    this.insert(record);
    return record;
  }

  async create(
    attachmentId: string,
    ownerSessionId: string,
    url: string,
    openerTabId: number,
  ): Promise<CreatedOwnedTab> {
    this.assertOwner(attachmentId, ownerSessionId);
    const parsed = parseOwnedTabUrl(url);
    if (this.byTarget.size >= MAX_OWNED_TABS) {
      throw new Error("The owned-tab limit has been reached.");
    }
    const tab = await this.api.createTab({ url: parsed.href, active: false, openerTabId });
    if (typeof tab.id !== "number" || !Number.isSafeInteger(tab.id) || tab.id < 0) {
      throw new Error("Chrome did not return a tab identity.");
    }
    let attachedTab: { title?: string; url?: string } | undefined;
    try {
      await this.api.attachDebugger(tab.id);
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const target = await this.api.getDebuggerTarget(tab.id);
        if (!target?.url || target.url === "about:blank") {
          await new Promise((resolve) => setTimeout(resolve, 50));
          continue;
        }
        const attachedUrl = parseOwnedTabUrl(target.url);
        if (attachedUrl.origin !== parsed.origin) {
          throw new Error("The new tab redirected outside its requested origin.");
        }
        attachedTab = target;
        break;
      }
      if (!attachedTab) throw new Error("Chrome did not report the attached tab URL.");
    } catch (error) {
      await this.api.detachDebugger(tab.id).catch(() => undefined);
      await this.api.removeTab(tab.id).catch(() => undefined);
      throw error;
    }
    const record: OwnedTabRecord = {
      attachmentId,
      ownerSessionId,
      targetId: `browser-tab-${crypto.randomUUID()}`,
      tabSessionId: `browser-session-${crypto.randomUUID()}`,
      chromeTabId: tab.id,
      title: typeof attachedTab.title === "string" ? attachedTab.title.slice(0, 512) : "",
      url:
        typeof attachedTab.url === "string"
          ? attachedTab.url.slice(0, MAX_OWNED_TAB_URL_BYTES)
          : parsed.href,
      origin: parsed.origin,
      initial: false,
    };
    this.insert(record);
    return {
      targetId: record.targetId,
      tabSessionId: record.tabSessionId,
      title: record.title,
      url: record.url,
      origin: record.origin,
    };
  }

  async activate(
    attachmentId: string,
    ownerSessionId: string,
    targetId: string,
  ): Promise<void> {
    const record = this.requireTarget(attachmentId, ownerSessionId, targetId);
    await this.api.activateTab(record.chromeTabId);
  }

  async close(
    attachmentId: string,
    ownerSessionId: string,
    targetId: string,
  ): Promise<OwnedTabRecord> {
    const record = this.requireTarget(attachmentId, ownerSessionId, targetId);
    if (record.initial) {
      throw new Error("The initially attached user tab cannot be closed by the agent.");
    }
    this.removeRecord(record);
    try {
      await this.api.detachDebugger(record.chromeTabId);
    } catch {
      // Chrome may detach when the tab closes or DevTools takes ownership.
    }
    await this.api.removeTab(record.chromeTabId);
    return record;
  }

  getByTarget(targetId: string): OwnedTabRecord | undefined {
    return this.byTarget.get(targetId);
  }

  getBySession(tabSessionId: string): OwnedTabRecord | undefined {
    return this.bySession.get(tabSessionId);
  }

  getByChromeTab(chromeTabId: number): OwnedTabRecord | undefined {
    for (const record of this.byTarget.values()) {
      if (record.chromeTabId === chromeTabId) {
        return record;
      }
    }
    return undefined;
  }

  detachByChromeTab(chromeTabId: number): OwnedTabRecord | undefined {
    const record = this.getByChromeTab(chromeTabId);
    if (record) {
      this.removeRecord(record);
    }
    return record;
  }

  async detachAll(attachmentId: string, ownerSessionId: string): Promise<void> {
    for (const record of [...this.byTarget.values()]) {
      if (
        record.attachmentId !== attachmentId ||
        record.ownerSessionId !== ownerSessionId
      ) {
        continue;
      }
      this.removeRecord(record);
      try {
        await this.api.detachDebugger(record.chromeTabId);
      } catch {
        // Tab may already be closed or detached by DevTools.
      }
    }
  }

  get size(): number {
    return this.byTarget.size;
  }

  snapshot(): OwnedTabRecord[] {
    return [...this.byTarget.values()].map((record) => ({ ...record }));
  }

  restore(value: unknown): boolean {
    if (
      this.byTarget.size !== 0 ||
      this.bySession.size !== 0 ||
      !Array.isArray(value) ||
      value.length < 1 ||
      value.length > MAX_OWNED_TABS
    ) {
      return false;
    }
    const records: OwnedTabRecord[] = [];
    for (const item of value) {
      if (
        typeof item !== "object" ||
        item === null ||
        Array.isArray(item) ||
        !isOwnedTabRecord(item)
      ) {
        return false;
      }
      records.push(item);
    }
    const initialRecords = records.filter((record) => record.initial);
    const owner = initialRecords[0];
    if (
      initialRecords.length !== 1 ||
      !owner ||
      records.some(
        (record) =>
          record.attachmentId !== owner.attachmentId ||
          record.ownerSessionId !== owner.ownerSessionId,
      )
    ) {
      return false;
    }
    try {
      for (const record of records) this.insert({ ...record });
      return true;
    } catch {
      this.byTarget.clear();
      this.bySession.clear();
      return false;
    }
  }

  private assertOwner(attachmentId: string, ownerSessionId: string): void {
    const owns = [...this.byTarget.values()].some(
      (record) =>
        record.initial &&
        record.attachmentId === attachmentId &&
        record.ownerSessionId === ownerSessionId,
    );
    if (!owns) {
      throw new Error("The active attachment does not own this tab set.");
    }
  }

  private requireTarget(
    attachmentId: string,
    ownerSessionId: string,
    targetId: string,
  ): OwnedTabRecord {
    const record = this.byTarget.get(targetId);
    if (
      !record ||
      record.attachmentId !== attachmentId ||
      record.ownerSessionId !== ownerSessionId
    ) {
      throw new Error("The requested tab is not owned by this attachment.");
    }
    return record;
  }

  private insert(record: OwnedTabRecord): void {
    if (this.byTarget.has(record.targetId) || this.bySession.has(record.tabSessionId)) {
      throw new Error("An owned-tab identity collided.");
    }
    this.byTarget.set(record.targetId, record);
    this.bySession.set(record.tabSessionId, record);
  }

  private removeRecord(record: OwnedTabRecord): void {
    this.byTarget.delete(record.targetId);
    this.bySession.delete(record.tabSessionId);
  }
}

export function parseOwnedTabUrl(value: string): URL {
  if (
    value.length === 0 ||
    new TextEncoder().encode(value).byteLength > MAX_OWNED_TAB_URL_BYTES ||
    hasUnsafeUrlCharacter(value)
  ) {
    throw new Error("The new-tab URL is invalid or exceeds its size limit.");
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("The new-tab URL must be an absolute HTTP or HTTPS URL.");
  }
  if (
    (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
    !parsed.hostname ||
    parsed.username.length > 0 ||
    parsed.password.length > 0
  ) {
    throw new Error("The new-tab URL must be a credential-free HTTP or HTTPS URL.");
  }
  return parsed;
}

function hasUnsafeUrlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x20 || code === 0x7f;
  });
}

function isOwnedTabRecord(value: Record<string, unknown>): value is OwnedTabRecord {
  if (
    typeof value.attachmentId !== "string" ||
    value.attachmentId.length < 1 ||
    value.attachmentId.length > 128 ||
    typeof value.ownerSessionId !== "string" ||
    value.ownerSessionId.length < 1 ||
    value.ownerSessionId.length > 128 ||
    typeof value.chromeTabId !== "number" ||
    !Number.isSafeInteger(value.chromeTabId) ||
    value.chromeTabId < 0 ||
    typeof value.targetId !== "string" ||
    typeof value.tabSessionId !== "string" ||
    typeof value.title !== "string" ||
    value.title.length > 512 ||
    typeof value.url !== "string" ||
    value.url.length > MAX_OWNED_TAB_URL_BYTES ||
    typeof value.origin !== "string" ||
    value.origin.length > 512 ||
    typeof value.initial !== "boolean"
  ) {
    return false;
  }
  if (value.initial) {
    return (
      value.targetId === `extension-tab-${value.attachmentId}` &&
      value.tabSessionId === value.ownerSessionId
    );
  }
  try {
    const parsed = parseOwnedTabUrl(value.url);
    return (
      /^browser-tab-[0-9a-f-]{36}$/i.test(value.targetId) &&
      /^browser-session-[0-9a-f-]{36}$/i.test(value.tabSessionId) &&
      value.origin === parsed.origin
    );
  } catch {
    return false;
  }
}
