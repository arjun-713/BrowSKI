import type { ExtensionSnapshot } from "./protocol";
import type { OwnedTabRecord } from "./owned-tabs";

export const ACTIVITY_CHANNEL = "browski.page-activity";

export type PageActivity = {
  type: typeof ACTIVITY_CHANNEL;
  active: boolean;
};

export function pageActivity(
  snapshot: ExtensionSnapshot,
  owned: OwnedTabRecord | undefined,
): PageActivity {
  return {
    type: ACTIVITY_CHANNEL,
    active: Boolean(
      snapshot.host === "connected" &&
      snapshot.protocolReady &&
      snapshot.session?.status === "running" &&
      snapshot.attachment &&
      snapshot.attachment.state !== "error" &&
      owned?.attachmentId === snapshot.attachment.attachmentId &&
      owned?.ownerSessionId === snapshot.session.sessionId,
    ),
  };
}

/** Only update decoration. A missing content script never changes run state. */
export function createActivityPublisher(
  send: (tabId: number, message: PageActivity) => Promise<unknown>,
) {
  const shownTabs = new Set<number>();
  return (snapshot: ExtensionSnapshot, records: OwnedTabRecord[]): void => {
    const current = new Map(records.map((record) => [record.chromeTabId, record]));
    const ids = new Set([...shownTabs, ...current.keys()]);
    shownTabs.clear();
    for (const tabId of ids) {
      const activity = pageActivity(snapshot, current.get(tabId));
      if (activity.active) shownTabs.add(tabId);
      void send(tabId, activity).catch(() => {
        // Protected pages and tabs open before installation have no indicator.
        // The script reads fresh state when it next loads or navigates.
      });
    }
  };
}
