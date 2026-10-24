import { afterEach, describe, expect, it, vi } from "vitest";
import { OwnedPopups } from "./owned-popups";
import { MAX_OWNED_TABS, OwnedTabs } from "./owned-tabs";

const url = "https://example.test/guide";

function harness() {
  let nextTab = 100;
  const api = {
    createTab: vi.fn(async () => ({ id: nextTab++ })),
    getDebuggerTarget: vi.fn(async () => ({ title: "Guide", url })),
    attachDebugger: vi.fn(async (tabId: number) => {
      void tabId;
    }),
    detachDebugger: vi.fn(async (tabId: number) => {
      void tabId;
    }),
    activateTab: vi.fn(async (tabId: number) => {
      void tabId;
    }),
    removeTab: vi.fn(async (tabId: number) => {
      void tabId;
    }),
  };
  const tabs = new OwnedTabs(api);
  tabs.registerInitial({
    attachmentId: "attachment",
    ownerSessionId: "root-session",
    chromeTabId: 7,
    title: "Start",
    url: "https://example.test/",
    origin: "https://example.test",
  });
  const getOwner = vi.fn(() => ({
    attachmentId: "attachment",
    sessionId: "root-session",
    state: "attached",
  }));
  const popups = new OwnedPopups(tabs, getOwner);
  const prepare = () => popups.prepare("attachment", "root-session", "root-session", url);
  const finish = (id: string, cancel = false) =>
    popups.finish("attachment", "root-session", id, cancel);
  const windowOpened = () =>
    popups.windowOpened(7, { url, windowName: "_blank", userGesture: true });
  const created = () => popups.tabCreated({ id: 42, openerTabId: 7 });
  return { api, tabs, popups, getOwner, prepare, finish, windowOpened, created };
}

afterEach(() => vi.useRealTimers());

describe("correlated native popup ownership", () => {
  it.each([true, false])(
    "consumes both events in either order (window first: %s)",
    async (windowFirst) => {
      const h = harness();
      const id = h.prepare();
      if (windowFirst) {
        h.windowOpened();
        h.created();
      } else {
        h.created();
        h.windowOpened();
      }
      expect(h.api.attachDebugger).not.toHaveBeenCalled();
      const tab = await h.finish(id);
      expect(tab?.targetId).toMatch(/^browser-tab-/);
      expect(tab?.tabSessionId).toMatch(/^browser-session-/);
      expect(tab).not.toHaveProperty("chromeTabId");
      expect(h.tabs.getByChromeTab(42)?.initial).toBe(false);
      expect(h.tabs.size).toBe(2);
      expect(h.api.createTab).not.toHaveBeenCalled();
      expect(h.api.removeTab).not.toHaveBeenCalled();
      await expect(h.finish(id)).rejects.toThrow("no longer current");
    },
  );

  it.each([
    { url: "https://other.test/", windowName: "_blank", userGesture: true },
    { url, windowName: "_blank", userGesture: false },
    { url, windowName: "unrelated-window", userGesture: true },
  ])("refuses mismatched browser metadata %j", async (params) => {
    const h = harness();
    const id = h.prepare();
    h.popups.windowOpened(7, params);
    h.created();
    await expect(h.finish(id)).rejects.toThrow();
    expect(h.api.attachDebugger).not.toHaveBeenCalled();
    expect(h.tabs.size).toBe(1);
  });

  it("ignores unrelated openers and expires without adopting existing tabs", async () => {
    vi.useFakeTimers();
    const h = harness();
    const id = h.prepare();
    h.popups.windowOpened(99, { url, windowName: "_blank", userGesture: true });
    h.popups.tabCreated({ id: 42, openerTabId: 99 });
    await vi.advanceTimersByTimeAsync(6_000);
    await expect(h.finish(id)).rejects.toThrow("no longer current");
    expect(h.api.attachDebugger).not.toHaveBeenCalled();
    expect(h.prepare()).not.toBe(id);
    h.popups.cancel();
  });

  it("refuses multiple candidates instead of guessing", async () => {
    const h = harness();
    const id = h.prepare();
    h.windowOpened();
    h.created();
    h.popups.tabCreated({ id: 43, openerTabId: 7 });
    await expect(h.finish(id)).rejects.toThrow();
    expect(h.api.attachDebugger).not.toHaveBeenCalled();
    expect(h.tabs.size).toBe(1);
  });

  it("keeps the native tab open after an origin-validation refusal", async () => {
    const h = harness();
    const id = h.prepare();
    h.windowOpened();
    h.created();
    h.api.getDebuggerTarget.mockResolvedValueOnce({
      title: "Redirect",
      url: "https://other.test/",
    });
    await expect(h.finish(id)).rejects.toThrow("outside its requested origin");
    expect(h.api.detachDebugger).toHaveBeenCalledWith(42);
    expect(h.api.removeTab).not.toHaveBeenCalled();
    expect(h.tabs.size).toBe(1);
  });

  it("invalidates failed input before a later user popup", async () => {
    const h = harness();
    const id = h.prepare();
    expect(await h.finish(id, true)).toBeNull();
    h.windowOpened();
    h.created();
    await expect(h.finish(id)).rejects.toThrow();
    expect(h.api.attachDebugger).not.toHaveBeenCalled();
  });

  it("refuses overlapping expectations and unowned sessions", () => {
    const h = harness();
    expect(() =>
      h.popups.prepare("attachment", "root-session", "other-session", url),
    ).toThrow("not owned");
    h.prepare();
    expect(() => h.prepare()).toThrow("already active");
    h.popups.cancel();
  });

  it("preserves the eight-tab cap", async () => {
    const h = harness();
    for (let index = 1; index < MAX_OWNED_TABS; index += 1) {
      await h.tabs.create("attachment", "root-session", url, 7);
    }
    expect(() => h.prepare()).toThrow("limit");
    expect(h.tabs.size).toBe(MAX_OWNED_TABS);
  });

  it("unblocks a pending completion on detach", async () => {
    const h = harness();
    const id = h.prepare();
    const finished = expect(h.finish(id)).rejects.toThrow();
    h.popups.cancel();
    await finished;
    h.windowOpened();
    h.created();
    expect(h.api.attachDebugger).not.toHaveBeenCalled();
  });

  it("detaches late attachment after owner loss without closing the page", async () => {
    const h = harness();
    let release!: () => void;
    let started!: () => void;
    const attaching = new Promise<void>((resolve) => {
      started = resolve;
    });
    h.api.attachDebugger.mockImplementationOnce(async () => {
      started();
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    });
    const id = h.prepare();
    h.windowOpened();
    h.created();
    const finished = expect(h.finish(id)).rejects.toThrow();
    await attaching;
    h.popups.cancel();
    await h.tabs.detachAll("attachment", "root-session");
    release();
    await finished;
    expect(h.tabs.size).toBe(0);
    expect(h.api.detachDebugger).toHaveBeenCalledWith(42);
    expect(h.api.removeTab).not.toHaveBeenCalled();
  });
});
