import { afterEach, describe, expect, it, vi } from "vitest";

import { getTabOrigin } from "./browser-origin";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("user-requested tab origin review", () => {
  it("uses a granted tab URL without enumerating debugger targets", async () => {
    const getTargets = vi.fn();
    vi.stubGlobal("chrome", { debugger: { getTargets } });

    await expect(getTabOrigin({ id: 7, url: "https://example.com/path" })).resolves.toBe(
      "https://example.com",
    );
    expect(getTargets).not.toHaveBeenCalled();
  });

  it("uses only the explicitly selected tab's debugger metadata", async () => {
    vi.stubGlobal("chrome", {
      debugger: {
        getTargets: vi.fn().mockResolvedValue([
          { type: "page", tabId: 8, url: "https://other.example/" },
          { type: "page", tabId: 7, url: "http://127.0.0.1:8080/demo" },
        ]),
      },
    });

    await expect(getTabOrigin({ id: 7 })).resolves.toBe("http://127.0.0.1:8080");
  });

  it("refuses missing metadata instead of selecting a different tab", async () => {
    vi.stubGlobal("chrome", {
      debugger: {
        getTargets: vi
          .fn()
          .mockResolvedValue([{ type: "page", tabId: 8, url: "https://other.example/" }]),
      },
    });

    await expect(getTabOrigin({ id: 7 })).rejects.toThrow(
      "did not share this tab's origin",
    );
  });

  it("rejects browser and extension pages", async () => {
    await expect(getTabOrigin({ id: 7, url: "chrome://settings" })).rejects.toThrow(
      "Only HTTP and HTTPS",
    );
  });
});
