import { describe, expect, it, vi } from "vitest";
import { createActivityPublisher, pageActivity } from "./page-activity";
import type { OwnedTabRecord } from "./owned-tabs";
import type { ExtensionSnapshot } from "./protocol";

const owned: OwnedTabRecord = {
  attachmentId: "attachment-1",
  ownerSessionId: "session-1",
  chromeTabId: 7,
  targetId: "target-1",
  tabSessionId: "session-1",
  title: "Example",
  url: "https://example.org/",
  origin: "https://example.org",
  initial: true,
};
const running: ExtensionSnapshot = {
  host: "connected",
  hostError: null,
  protocolReady: true,
  session: { sessionId: "session-1", status: "running", updatedAt: "2026-10-16T00:00:00Z" },
  events: [],
  pendingApproval: null,
  openAiKeyConfigured: true,
  settingsError: null,
  runtimeSettings: null,
  selectedTab: null,
  attachment: {
    attachmentId: "attachment-1",
    tabId: 7,
    origin: "https://example.org",
    sessionId: "session-1",
    state: "attached",
    message: "",
  },
};

describe("page activity ownership and lifecycle", () => {
  it("shows activity only for a connected running session's owned tabs", () => {
    expect(pageActivity(running, owned).active).toBe(true);
    expect(
      pageActivity(
        { ...running, session: { ...running.session!, browserMode: "managed" } },
        owned,
      ).active,
    ).toBe(false);
    expect(pageActivity(running, undefined).active).toBe(false);
    expect(pageActivity(running, { ...owned, ownerSessionId: "other" }).active).toBe(false);
    expect(pageActivity(running, { ...owned, attachmentId: "other" }).active).toBe(false);
    expect(pageActivity({ ...running, attachment: null }, owned).active).toBe(false);
    expect(pageActivity({ ...running, host: "disconnected" }, owned).active).toBe(false);
    expect(pageActivity({ ...running, protocolReady: false }, owned).active).toBe(false);
  });

  it("clears activity on pause, approval, completion, stop, or failure", () => {
    for (const status of [
      "idle",
      "paused",
      "awaiting_approval",
      "completed",
      "stopped",
      "failed",
    ] as const) {
      expect(
        pageActivity(
          {
            ...running,
            session: { sessionId: "session-1", status, updatedAt: "2026-10-16T00:00:00Z" },
          },
          owned,
        ).active,
      ).toBe(false);
    }
  });

  it("sends a final clear message to removed tabs and contains presentation failures", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const publish = createActivityPublisher(send);
    publish(running, [owned]);
    publish({ ...running, attachment: null }, []);
    expect(send).toHaveBeenNthCalledWith(1, 7, {
      type: "browski.page-activity",
      active: true,
    });
    expect(send).toHaveBeenNthCalledWith(2, 7, {
      type: "browski.page-activity",
      active: false,
    });
    send.mockRejectedValue(new Error("No content script on this protected page"));
    publish(running, [owned]);
    await Promise.resolve();
  });
});
