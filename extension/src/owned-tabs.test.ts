import { describe, expect, it, vi } from "vitest";
import { MAX_OWNED_TABS, OwnedTabs, parseOwnedTabUrl } from "./owned-tabs";

function createHarness() {
  let nextTab = 101;
  const api = {
    createTab: vi.fn(
      async (properties: { url: string; active: false; openerTabId?: number }) => ({
        id: nextTab++,
        title: "New page",
        url: properties.url,
      }),
    ),
    getDebuggerTarget: vi.fn(async () => ({
      title: "New page",
      url: "https://example.test/",
    })),
    attachDebugger: vi.fn(async (tabId: number) => void tabId),
    detachDebugger: vi.fn(async (tabId: number) => void tabId),
    activateTab: vi.fn(async (tabId: number) => void tabId),
    removeTab: vi.fn(async (tabId: number) => void tabId),
  };
  const tabs = new OwnedTabs(api);
  const initial = tabs.registerInitial({
    attachmentId: "attachment-opaque",
    ownerSessionId: "session-root",
    chromeTabId: 7,
    title: "Start",
    url: "https://example.test/",
    origin: "https://example.test",
  });
  return { api, initial, tabs };
}

describe("OwnedTabs", () => {
  it("returns opaque target/session IDs and creates inactive HTTP(S) tabs", async () => {
    const { api, initial, tabs } = createHarness();
    const created = await tabs.create(
      initial.attachmentId,
      initial.ownerSessionId,
      "https://example.test/results?q=one",
      initial.chromeTabId,
    );

    expect(api.createTab).toHaveBeenCalledWith({
      url: "https://example.test/results?q=one",
      active: false,
      openerTabId: 7,
    });
    expect(created.targetId).not.toContain("101");
    expect(created.tabSessionId).not.toBe(initial.ownerSessionId);
    expect(tabs.getByTarget(created.targetId)?.chromeTabId).toBe(101);
    expect(tabs.getBySession(created.tabSessionId)?.chromeTabId).toBe(101);
  });

  it("does not create tabs with non-HTTP(S), credentials, whitespace, or oversized URLs", async () => {
    const { api, initial, tabs } = createHarness();
    for (const url of [
      "javascript:alert(1)",
      "file:///etc/passwd",
      "https://user:secret@example.test/",
      "https://example.test/a b",
      `https://example.test/${"x".repeat(2050)}`,
    ]) {
      await expect(
        tabs.create(initial.attachmentId, initial.ownerSessionId, url, initial.chromeTabId),
      ).rejects.toThrow();
    }
    expect(api.createTab).not.toHaveBeenCalled();
  });

  it("removes a supporting tab that redirects before its ownership record is registered", async () => {
    const { api, initial, tabs } = createHarness();
    api.getDebuggerTarget.mockResolvedValueOnce({
      title: "Redirected",
      url: "https://other.test/account",
    });
    await expect(
      tabs.create(
        initial.attachmentId,
        initial.ownerSessionId,
        "https://example.test/start",
        initial.chromeTabId,
      ),
    ).rejects.toThrow("redirected outside its requested origin");
    expect(api.detachDebugger).toHaveBeenCalled();
    expect(api.removeTab).toHaveBeenCalled();
    expect(tabs.size).toBe(1);
  });

  it("limits a session to eight total tabs and detaches a tab if debugger attach fails", async () => {
    const { api, initial, tabs } = createHarness();
    for (let index = 1; index < MAX_OWNED_TABS; index += 1) {
      await tabs.create(
        initial.attachmentId,
        initial.ownerSessionId,
        `https://example.test/${index}`,
        initial.chromeTabId,
      );
    }
    await expect(
      tabs.create(
        initial.attachmentId,
        initial.ownerSessionId,
        "https://example.test/overflow",
        7,
      ),
    ).rejects.toThrow("limit");
    expect(api.createTab).toHaveBeenCalledTimes(MAX_OWNED_TABS - 1);

    const separate = createHarness();
    separate.api.attachDebugger.mockRejectedValueOnce(new Error("attach refused"));
    await expect(
      separate.tabs.create(
        separate.initial.attachmentId,
        separate.initial.ownerSessionId,
        "https://example.test/failed",
        separate.initial.chromeTabId,
      ),
    ).rejects.toThrow("attach refused");
    expect(separate.api.removeTab).toHaveBeenCalledWith(101);
    expect(separate.tabs.size).toBe(1);
  });

  it("activates only mapped targets and refuses to close the initial user tab", async () => {
    const { api, initial, tabs } = createHarness();
    await expect(
      tabs.activate(initial.attachmentId, initial.ownerSessionId, "chrome-tab-7"),
    ).rejects.toThrow("not owned");
    await expect(
      tabs.close(initial.attachmentId, initial.ownerSessionId, initial.targetId),
    ).rejects.toThrow("initially attached");
    expect(api.activateTab).not.toHaveBeenCalled();
    expect(api.removeTab).not.toHaveBeenCalled();
  });

  it("closes only the selected supporting tab and keeps its siblings mapped", async () => {
    const { api, initial, tabs } = createHarness();
    const one = await tabs.create(
      initial.attachmentId,
      initial.ownerSessionId,
      "https://example.test/one",
      initial.chromeTabId,
    );
    const two = await tabs.create(
      initial.attachmentId,
      initial.ownerSessionId,
      "https://example.test/two",
      initial.chromeTabId,
    );
    await tabs.activate(initial.attachmentId, initial.ownerSessionId, two.targetId);
    await tabs.close(initial.attachmentId, initial.ownerSessionId, one.targetId);

    expect(api.activateTab).toHaveBeenCalledWith(102);
    expect(api.detachDebugger).toHaveBeenCalledWith(101);
    expect(api.removeTab).toHaveBeenCalledWith(101);
    expect(tabs.getByTarget(one.targetId)).toBeUndefined();
    expect(tabs.getByTarget(two.targetId)?.chromeTabId).toBe(102);
    expect(tabs.getByTarget(initial.targetId)?.chromeTabId).toBe(7);
  });

  it("detaches every session debugger without closing its user tabs on shutdown", async () => {
    const { api, initial, tabs } = createHarness();
    await tabs.create(
      initial.attachmentId,
      initial.ownerSessionId,
      "https://example.test/support",
      initial.chromeTabId,
    );
    await tabs.detachAll(initial.attachmentId, initial.ownerSessionId);

    expect(
      api.detachDebugger.mock.calls
        .map(([tabId]) => tabId)
        .sort((left, right) => left - right),
    ).toEqual([7, 101]);
    expect(api.removeTab).not.toHaveBeenCalled();
    expect(tabs.size).toBe(0);
  });

  it("restores only a complete, valid attachment-scoped map after worker restart", async () => {
    const { api, initial, tabs } = createHarness();
    const child = await tabs.create(
      initial.attachmentId,
      initial.ownerSessionId,
      "https://example.test/support",
      initial.chromeTabId,
    );
    const restored = new OwnedTabs(api);

    expect(restored.restore(tabs.snapshot())).toBe(true);
    expect(restored.getByChromeTab(7)?.targetId).toBe(initial.targetId);
    expect(restored.getBySession(child.tabSessionId)?.targetId).toBe(child.targetId);

    const invalid = new OwnedTabs(api);
    expect(
      invalid.restore([...tabs.snapshot(), { ...tabs.snapshot()[1], chromeTabId: -4 }]),
    ).toBe(false);
    expect(invalid.size).toBe(0);
  });
});

it("parses only bounded credential-free HTTP(S) URLs", () => {
  expect(parseOwnedTabUrl("http://localhost:9000/page").origin).toBe(
    "http://localhost:9000",
  );
  expect(parseOwnedTabUrl("https://example.test/page").protocol).toBe("https:");
});
