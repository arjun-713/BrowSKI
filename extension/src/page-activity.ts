import type { ExtensionSnapshot } from "./protocol";
import type { OwnedTabRecord } from "./owned-tabs";

export const ACTIVITY_CHANNEL = "browski.page-activity";

export type ActivityState = "working" | "approval" | "paused" | "idle";

export type PageActivity = {
  type: typeof ACTIVITY_CHANNEL;
  active: boolean;
  state: ActivityState;
};

function activityState(snapshot: ExtensionSnapshot): ActivityState {
  if (snapshot.host !== "connected" || !snapshot.protocolReady) return "idle";
  switch (snapshot.session?.status) {
    case "running":
      return "working";
    case "awaiting_approval":
      return "approval";
    case "paused":
      return "paused";
    default:
      return "idle";
  }
}

export function pageActivity(
  snapshot: ExtensionSnapshot,
  owned: OwnedTabRecord | undefined,
  relayLeased = false,
): PageActivity {
  const state = activityState(snapshot);
  if (relayLeased) {
    // The agent holds this tab for the whole task, including approval waits.
    return { type: ACTIVITY_CHANNEL, active: state !== "idle", state };
  }
  const active = Boolean(
    state === "working" &&
    snapshot.session?.browserMode !== "managed" &&
    snapshot.attachment &&
    snapshot.attachment.state !== "error" &&
    owned?.attachmentId === snapshot.attachment.attachmentId &&
    owned?.ownerSessionId === snapshot.session?.sessionId,
  );
  return { type: ACTIVITY_CHANNEL, active, state: active ? state : "idle" };
}

/** Only update decoration. A missing content script never changes run state. */
export function createActivityPublisher(
  send: (tabId: number, message: PageActivity) => Promise<unknown>,
) {
  const shownTabs = new Set<number>();
  return (
    snapshot: ExtensionSnapshot,
    records: OwnedTabRecord[],
    relayTabs: readonly number[] = [],
  ): void => {
    const current = new Map(records.map((record) => [record.chromeTabId, record]));
    const relay = new Set(relayTabs);
    const ids = new Set([...shownTabs, ...current.keys(), ...relay]);
    shownTabs.clear();
    for (const tabId of ids) {
      const activity = pageActivity(snapshot, current.get(tabId), relay.has(tabId));
      if (activity.active) shownTabs.add(tabId);
      void send(tabId, activity).catch(() => {
        // Protected pages and tabs open before installation have no indicator.
        // The script reads fresh state when it next loads or navigates.
      });
    }
  };
}
