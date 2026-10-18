import { allowedOrigin, getTabOrigin } from "../src/browser-origin";
import { DebuggerProxy } from "../src/debugger-proxy";
import { NativeHostController } from "../src/native-host";
import { createPanelMessageHandler } from "../src/panel-router";
import { isTrustedPanelSender } from "../src/panel-sender";
import { OwnedTabs } from "../src/owned-tabs";
import { StartupGate, withStartupTimeout } from "../src/startup-gate";
import { createActivityPublisher, pageActivity } from "../src/page-activity";
import type { ExtensionSnapshot } from "../src/protocol";

const ATTACHMENT_STORAGE_KEY = "browserAttachment";
const OWNED_TABS_STORAGE_KEY = "ownedBrowserTabs";
const SELECTED_TAB_STORAGE_KEY = "selectedBrowserTab";
const PANEL_CHANNEL = "extension.snapshot";
const startupGate = new StartupGate();

type Attachment = NonNullable<ExtensionSnapshot["attachment"]>;

const snapshot: ExtensionSnapshot = {
  host: "disconnected",
  hostError: null,
  protocolReady: false,
  session: null,
  events: [],
  pendingApproval: null,
  openAiKeyConfigured: false,
  settingsError: null,
  runtimeSettings: null,
  selectedTab: null,
  attachment: null,
};

const panelPorts = new Set<chrome.runtime.Port>();
const ownedTabs = new OwnedTabs({
  createTab: async (properties) => {
    const tab = await chrome.tabs.create(properties);
    return { id: tab.id, title: tab.title, url: tab.url };
  },
  getDebuggerTarget: async (tabId) => {
    const targets = await chrome.debugger.getTargets();
    return targets.find((target) => target.tabId === tabId && target.attached);
  },
  attachDebugger: (tabId) => chrome.debugger.attach({ tabId }, "1.3"),
  detachDebugger: (tabId) => chrome.debugger.detach({ tabId }),
  activateTab: async (tabId) => {
    await chrome.tabs.update(tabId, { active: true });
  },
  removeTab: async (tabId) => {
    await chrome.tabs.remove(tabId);
  },
});

const publishActivity = createActivityPublisher((tabId, message) =>
  chrome.tabs.sendMessage(tabId, message),
);

const nativeHost = new NativeHostController({
  snapshot,
  publishSnapshot,
  detachOwnedTab,
  clearSelectedTab,
  handleDebuggerCommand: (payload) => {
    void debuggerProxy.handleCommand(payload);
  },
  handleDetachRequest: handleHostDetachRequest,
});

const debuggerProxy = new DebuggerProxy({
  getAttachment: () => snapshot.attachment,
  getNegotiatedMethods: () => nativeHost.getNegotiatedMethods(),
  getNegotiatedEvents: () => nativeHost.getNegotiatedEvents(),
  ownedTabs,
  sendNative: (type, payload) => nativeHost.sendNative(type, payload),
  setHostError: (message) => nativeHost.setHostError(message),
  persistOwnedTabs,
  stopOwnedTabs,
  detachOwnedTab,
  sendCommand: (tabId, method, params) =>
    chrome.debugger.sendCommand({ tabId }, method, params),
  detachDebugger: (tabId) => chrome.debugger.detach({ tabId }),
  setInitialLoadingState: (state, message) => {
    if (!snapshot.attachment) return;
    snapshot.attachment = { ...snapshot.attachment, state, message };
    publishSnapshot();
  },
});

function requestId(): string {
  return crypto.randomUUID();
}

function sendToPanel(): void {
  for (const port of panelPorts) {
    try {
      port.postMessage({ type: PANEL_CHANNEL, snapshot: { ...snapshot } });
    } catch {
      panelPorts.delete(port);
    }
  }
}

function publishSnapshot(): void {
  sendToPanel();
  publishActivity(snapshot, ownedTabs.snapshot());
}

async function stopOwnedTabs(attachment: Attachment): Promise<void> {
  await ownedTabs.detachAll(attachment.attachmentId, attachment.sessionId);
  await persistOwnedTabs();
  if (snapshot.attachment?.attachmentId === attachment.attachmentId) {
    snapshot.attachment = null;
    await chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
    await clearSelectedTab();
    publishSnapshot();
  }
}

async function persistOwnedTabs(): Promise<void> {
  await chrome.storage.session.set({ ownedBrowserTabs: ownedTabs.snapshot() });
}

async function captureActiveTab(): Promise<void> {
  await startupGate.wait();
  if (!snapshot.protocolReady) {
    throw new Error("Connect to the local BROWSKI runtime before choosing a tab.");
  }
  if (snapshot.attachment) {
    throw new Error("Clear the current attachment before choosing another tab.");
  }
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (typeof tab?.id !== "number") {
    throw new Error("Chrome did not report an active tab in the focused window.");
  }
  snapshot.selectedTab = { tabId: tab.id, origin: await getTabOrigin(tab) };
  await chrome.storage.session.set({ [SELECTED_TAB_STORAGE_KEY]: snapshot.selectedTab });
  publishSnapshot();
}

async function attachSelectedTab(): Promise<void> {
  await startupGate.wait();
  if (!snapshot.protocolReady) {
    throw new Error("Connect to the local BROWSKI runtime before attaching a tab.");
  }
  if (snapshot.attachment) {
    throw new Error("A tab is already attached. Clear it before choosing another.");
  }
  const selectedTab = snapshot.selectedTab;
  if (!selectedTab) {
    throw new Error("Choose a tab and review its origin first.");
  }
  const currentTab = await chrome.tabs.get(selectedTab.tabId);
  if ((await getTabOrigin(currentTab)) !== selectedTab.origin) {
    await clearSelectedTab();
    throw new Error("The selected tab navigated. Capture it again before attaching.");
  }
  await chrome.debugger.attach({ tabId: selectedTab.tabId }, "1.3");
  const session = snapshot.session ?? {
    sessionId: requestId(),
    updatedAt: new Date().toISOString(),
    status: "idle" as const,
  };
  snapshot.session = session;
  const attachment: Attachment = {
    attachmentId: requestId(),
    tabId: selectedTab.tabId,
    origin: selectedTab.origin,
    sessionId: session.sessionId,
    state: "attached",
    message: "Attached to the origin reviewed in this panel.",
  };
  ownedTabs.registerInitial({
    attachmentId: attachment.attachmentId,
    ownerSessionId: attachment.sessionId,
    chromeTabId: attachment.tabId,
    title: currentTab.title ?? "",
    url: currentTab.url ?? "",
    origin: attachment.origin,
  });
  snapshot.attachment = attachment;
  await chrome.storage.session.set({ [ATTACHMENT_STORAGE_KEY]: attachment });
  await persistOwnedTabs();
  nativeHost.sendNative("browser.tab.attached", {
    attachmentId: attachment.attachmentId,
    tabId: attachment.tabId,
    origin: attachment.origin,
    sessionId: attachment.sessionId,
  });
  publishSnapshot();
}

async function clearSelectedTab(): Promise<void> {
  snapshot.selectedTab = null;
  await chrome.storage.session.remove(SELECTED_TAB_STORAGE_KEY);
  publishSnapshot();
}

async function detachOwnedTab(reason: string, retainError = false): Promise<void> {
  try {
    await startupGate.wait();
  } catch {
    // The failed restoration has already cleared persisted ownership.
  }
  const attachment = snapshot.attachment;
  if (!attachment) {
    return;
  }

  snapshot.attachment = retainError
    ? { ...attachment, state: "error", message: reason }
    : null;
  await ownedTabs.detachAll(attachment.attachmentId, attachment.sessionId);
  await chrome.storage.session.remove(OWNED_TABS_STORAGE_KEY);
  if (retainError) {
    await clearSelectedTab();
  }
  await chrome.storage.session.remove(ATTACHMENT_STORAGE_KEY);
  try {
    await chrome.debugger.detach({ tabId: attachment.tabId });
  } catch {
    // Chrome may already have detached because the tab closed or DevTools took over.
  }
  nativeHost.sendNative("browser.tab.detached", {
    attachmentId: attachment.attachmentId,
    reason,
  });
  publishSnapshot();
}

function handleHostDetachRequest(payload: Record<string, unknown>): void {
  if (
    typeof payload.attachmentId !== "string" ||
    payload.attachmentId !== snapshot.attachment?.attachmentId
  ) {
    return;
  }

  void detachOwnedTab(
    typeof payload.reason === "string" ? payload.reason : "Runtime requested detach.",
  );
}

export default defineBackground(() => {
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (
      message?.type !== "activity.read" ||
      sender.id !== chrome.runtime.id ||
      sender.tab?.id === undefined
    ) {
      return false;
    }
    respond(pageActivity(snapshot, ownedTabs.getByChromeTab(sender.tab.id)));
    return false;
  });
  chrome.action.onClicked.addListener(async (tab) => {
    if (typeof tab.windowId === "number") {
      await chrome.sidePanel.open({ windowId: tab.windowId });
    }
  });

  chrome.debugger.onEvent.addListener((source, method, params) =>
    debuggerProxy.onEvent(source, method, params),
  );
  chrome.debugger.onDetach.addListener((source, reason) =>
    debuggerProxy.onDetach(source, reason),
  );

  chrome.tabs.onRemoved.addListener((tabId) => {
    if (snapshot.attachment?.tabId === tabId) {
      void detachOwnedTab("The attached tab was closed.");
    } else {
      const removed = ownedTabs.detachByChromeTab(tabId);
      if (removed) {
        void persistOwnedTabs();
        debuggerProxy.notifyTabDestroyed(removed);
      }
    }
    if (snapshot.selectedTab?.tabId === tabId) {
      void clearSelectedTab();
    }
  });

  chrome.tabs.onActivated.addListener(({ tabId }) => {
    if (snapshot.attachment && snapshot.attachment.tabId !== tabId) {
      snapshot.attachment.message =
        "Another tab is active. BROWSKI remains attached to the original tab.";
      publishSnapshot();
    }
  });

  chrome.runtime.onConnect.addListener((port) => {
    if (
      port.name !== "browski-panel" ||
      !isTrustedPanelSender(port.sender, chrome.runtime.id)
    ) {
      return;
    }
    panelPorts.add(port);
    port.onDisconnect.addListener(() => panelPorts.delete(port));
    port.postMessage({ type: PANEL_CHANNEL, snapshot: { ...snapshot } });
  });

  chrome.runtime.onMessage.addListener(
    createPanelMessageHandler({
      extensionId: chrome.runtime.id,
      getSnapshot: () => snapshot,
      sendNative: nativeHost.sendNative,
      connectHost: nativeHost.connectHost,
      disconnectHost: nativeHost.disconnectHost,
      captureActiveTab,
      attachSelectedTab,
      detachOwnedTab: (reason) => detachOwnedTab(reason),
      clearSelectedTab,
    }),
  );

  void withStartupTimeout(
    chrome.storage.session.get([
      ATTACHMENT_STORAGE_KEY,
      OWNED_TABS_STORAGE_KEY,
      SELECTED_TAB_STORAGE_KEY,
    ]),
    "Saved browser state read",
  )
    .then(async (value) => {
      const selected = value[SELECTED_TAB_STORAGE_KEY] as
        { tabId?: unknown; origin?: unknown } | undefined;
      if (typeof selected?.tabId === "number" && typeof selected.origin === "string") {
        try {
          const tab = await withStartupTimeout(
            chrome.tabs.get(selected.tabId),
            "Saved tab lookup",
          );
          if (allowedOrigin(tab.url) === selected.origin) {
            snapshot.selectedTab = { tabId: selected.tabId, origin: selected.origin };
          } else {
            await withStartupTimeout(clearSelectedTab(), "Saved selection cleanup");
          }
        } catch {
          snapshot.selectedTab = null;
          await withStartupTimeout(
            chrome.storage.session.remove(SELECTED_TAB_STORAGE_KEY),
            "Saved selection cleanup",
          );
        }
      }

      const restored = value[ATTACHMENT_STORAGE_KEY] as Attachment | undefined;
      if (!restored || typeof restored.tabId !== "number") {
        return;
      }

      const targets = await withStartupTimeout(
        chrome.debugger.getTargets(),
        "Attached tab lookup",
      );
      const stillAttached = targets.some(
        (target) => target.tabId === restored.tabId && target.attached,
      );
      if (stillAttached) {
        if (
          snapshot.session?.sessionId === restored.sessionId &&
          snapshot.selectedTab?.tabId === restored.tabId &&
          snapshot.selectedTab.origin === restored.origin
        ) {
          const restoredTabs = ownedTabs.restore(value[OWNED_TABS_STORAGE_KEY]);
          let recordsMatch = restoredTabs;
          if (recordsMatch) {
            for (const record of ownedTabs.snapshot()) {
              if (
                record.attachmentId !== restored.attachmentId ||
                record.ownerSessionId !== restored.sessionId ||
                !targets.some(
                  (target) => target.tabId === record.chromeTabId && target.attached,
                )
              ) {
                recordsMatch = false;
                break;
              }
              try {
                const tab = await withStartupTimeout(
                  chrome.tabs.get(record.chromeTabId),
                  "Owned tab lookup",
                );
                const currentOrigin = record.initial
                  ? allowedOrigin(tab.url)
                  : new URL(tab.url ?? "").origin;
                if (currentOrigin !== record.origin) recordsMatch = false;
              } catch {
                recordsMatch = false;
              }
              if (!recordsMatch) break;
            }
          }
          if (recordsMatch) {
            snapshot.attachment = restored;
          } else {
            await withStartupTimeout(
              ownedTabs.detachAll(restored.attachmentId, restored.sessionId),
              "Stale owned-tab detach",
            );
            await withStartupTimeout(
              chrome.storage.session.remove([
                ATTACHMENT_STORAGE_KEY,
                OWNED_TABS_STORAGE_KEY,
              ]),
              "Stale attachment cleanup",
            );
            await withStartupTimeout(
              chrome.debugger.detach({ tabId: restored.tabId }).catch(() => undefined),
              "Stale debugger detach",
            );
            snapshot.attachment = {
              ...restored,
              state: "error",
              message: "The owned-tab map changed. Attach again to continue.",
            };
          }
        } else {
          await withStartupTimeout(
            chrome.storage.session.remove([ATTACHMENT_STORAGE_KEY, OWNED_TABS_STORAGE_KEY]),
            "Stale attachment cleanup",
          );
          snapshot.attachment = {
            ...restored,
            state: "error",
            message: "The runtime session changed. Attach again to continue.",
          };
          await withStartupTimeout(
            chrome.debugger.detach({ tabId: restored.tabId }).catch(() => undefined),
            "Stale debugger detach",
          );
        }
      } else {
        await withStartupTimeout(
          chrome.storage.session.remove([ATTACHMENT_STORAGE_KEY, OWNED_TABS_STORAGE_KEY]),
          "Stale attachment cleanup",
        );
        snapshot.attachment = null;
      }
      publishSnapshot();
    })
    .catch(async () => {
      startupGate.fail(
        "Saved browser state could not be checked. Restart the extension before attaching a tab.",
      );
      const owner = ownedTabs.snapshot().find((record) => record.initial);
      if (owner) {
        try {
          await withStartupTimeout(
            ownedTabs.detachAll(owner.attachmentId, owner.ownerSessionId),
            "Saved owned-tab detach",
          );
        } catch {
          // The attachment gate stays failed until the extension is restarted.
        }
      }
      snapshot.attachment = null;
      snapshot.selectedTab = null;
      try {
        await withStartupTimeout(
          chrome.storage.session.remove([
            ATTACHMENT_STORAGE_KEY,
            OWNED_TABS_STORAGE_KEY,
            SELECTED_TAB_STORAGE_KEY,
          ]),
          "Saved state cleanup",
        );
      } catch {
        // Keep attaching disabled after a failed best-effort restore.
      }
      publishSnapshot();
    })
    .finally(() => startupGate.release());
});
