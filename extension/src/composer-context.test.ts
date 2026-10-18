import { afterEach, describe, expect, it, vi } from "vitest";
import {
  composeTask,
  getComposerTrigger,
  linkContext,
  listReferenceTabs,
  MAX_FILE_BYTES,
  readTextAttachment,
} from "./composer-context";

afterEach(() => vi.unstubAllGlobals());

describe("task reference context", () => {
  it("preserves URL paths and rejects executable, credentialed, or browser URLs", () => {
    expect(linkContext("https://example.org/CaseSensitive?Name=Value").content).toBe(
      "https://example.org/CaseSensitive?Name=Value",
    );
    for (const value of [
      "javascript:alert(1)",
      "chrome://settings",
      "https://user:pass@example.org/",
    ]) {
      expect(() => linkContext(value)).toThrow();
    }
  });

  it("only serializes selected references without changing attachment authority", () => {
    expect(
      composeTask("  Compare these  ", [linkContext("https://example.org/")]),
    ).toContain("mentioning a tab does not grant control");
    expect(composeTask("  Plain task  ", [])).toBe("Plain task");
  });

  it("detects commands at the caret without treating email addresses as mentions", () => {
    expect(getComposerTrigger("Email test@example.org", 22)).toBeNull();
    expect(getComposerTrigger("Compare @Example", 16)).toEqual({
      kind: "@",
      query: "Example",
      start: 8,
    });
    expect(getComposerTrigger("/ext after", 4)).toEqual({
      kind: "/",
      query: "ext",
      start: 0,
    });
  });

  it("reads only bounded readable text files", async () => {
    const text = new File(["Reference details"], "brief.md");
    Object.defineProperty(text, "text", { value: async () => "Reference details" });
    expect(await readTextAttachment(text)).toMatchObject({
      kind: "file",
      label: "brief.md",
      content: "Reference details",
    });
    await expect(readTextAttachment(new File(["binary"], "brief.pdf"))).rejects.toThrow(
      "not supported",
    );
    await expect(
      readTextAttachment(new File(["x".repeat(MAX_FILE_BYTES + 1)], "large.txt")),
    ).rejects.toThrow("too large");
    const binary = new File(["binary"], "binary.txt");
    Object.defineProperty(binary, "text", { value: async () => "\0binary" });
    await expect(readTextAttachment(binary)).rejects.toThrow("readable UTF-8");
  });

  it("lists HTTP(S) references in the current window without sharing the tab inventory", async () => {
    const query = vi
      .fn()
      .mockResolvedValue([
        { id: 1, title: "A page", url: "https://example.org/A" },
        { id: 2, title: "Settings", url: "chrome://settings" },
        { id: 3 },
      ]);
    vi.stubGlobal("chrome", { tabs: { query } });
    expect(await listReferenceTabs()).toEqual([
      { id: 1, title: "A page", url: "https://example.org/A" },
    ]);
    expect(query).toHaveBeenCalledWith({ currentWindow: true });
  });
});
