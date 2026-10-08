export function allowedOrigin(value: string | undefined): string {
  if (!value) {
    throw new Error("Chrome did not share this tab's origin.");
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Chrome did not share a valid HTTP or HTTPS tab origin.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only HTTP and HTTPS tabs can be attached.");
  }
  return parsed.origin;
}

export async function getTabOrigin(
  tab: Pick<chrome.tabs.Tab, "id" | "url">,
): Promise<string> {
  if (tab.url !== undefined) {
    return allowedOrigin(tab.url);
  }
  if (tab.id === undefined) {
    throw new Error("Chrome did not report a browser tab identity.");
  }

  // A panel opened from Chrome's menu may have no activeTab URL grant. The
  // existing debugger permission can read the reviewed tab's target metadata.
  // Use it only for this explicit user request and match the exact tab ID.
  const targets = await chrome.debugger.getTargets();
  const target = targets.find((item) => item.type === "page" && item.tabId === tab.id);
  return allowedOrigin(target?.url);
}
