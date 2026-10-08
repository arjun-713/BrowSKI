import { describe, expect, it } from "vitest";
import { isTrustedPanelSender } from "./panel-sender";

const extensionId = "a".repeat(32);

describe("panel sender identity", () => {
  it("accepts the browser-reported identity of the packaged panel", () => {
    expect(
      isTrustedPanelSender(
        { id: extensionId, url: `chrome-extension://${extensionId}/panel.html` },
        extensionId,
      ),
    ).toBe(true);
  });

  it.each([
    undefined,
    { id: extensionId, url: "https://malicious.example/panel.html" },
    { id: "b".repeat(32), url: `chrome-extension://${extensionId}/panel.html` },
    { id: extensionId, url: `chrome-extension://${extensionId}/content.html` },
    { id: extensionId, url: "not-a-url" },
  ])("rejects a webpage, other extension, or unexpected view", (sender) => {
    expect(isTrustedPanelSender(sender, extensionId)).toBe(false);
  });
});
