export function isTrustedPanelSender(
  sender: Pick<chrome.runtime.MessageSender, "id" | "url"> | undefined,
  extensionId: string,
): boolean {
  if (sender?.id !== extensionId || typeof sender.url !== "string") {
    return false;
  }
  try {
    const url = new URL(sender.url);
    return (
      url.protocol === "chrome-extension:" &&
      url.hostname === extensionId &&
      url.pathname === "/panel.html"
    );
  } catch {
    return false;
  }
}
