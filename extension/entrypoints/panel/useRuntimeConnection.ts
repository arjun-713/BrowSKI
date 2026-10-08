import { useCallback, useEffect, useState } from "react";
import type { ExtensionSnapshot } from "../../src/protocol";

const EMPTY_SNAPSHOT: ExtensionSnapshot = {
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

type BackgroundErrorResponse = {
  snapshot: ExtensionSnapshot;
  error?: string;
};

export type DispatchResult = ExtensionSnapshot & { error?: string };

export function useRuntimeConnection() {
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoConnect, setAutoConnect] = useState(false);

  useEffect(() => {
    const port = chrome.runtime.connect({ name: "browski-panel" });
    port.onMessage.addListener((message: { snapshot?: ExtensionSnapshot }) => {
      if (message.snapshot) {
        setSnapshot(message.snapshot);
      }
    });

    void chrome.runtime
      .sendMessage({ type: "panel.snapshot" })
      .then((result) => {
        if (isSnapshot(result)) {
          setSnapshot(result);
        }
      })
      .catch(() => undefined);

    void chrome.storage.local.get("autoConnectNativeHost").then((value) => {
      const enabled = value.autoConnectNativeHost === true;
      setAutoConnect(enabled);
      if (enabled) {
        void chrome.runtime.sendMessage({ type: "host.connect" }).catch(() => undefined);
      }
    });

    return () => port.disconnect();
  }, []);

  useEffect(() => {
    if (snapshot.protocolReady) {
      void chrome.runtime.sendMessage({ type: "settings.get" }).catch(() => undefined);
    }
  }, [snapshot.protocolReady]);

  const dispatch = useCallback(
    async (message: Record<string, unknown>): Promise<DispatchResult> => {
      setPanelError(null);
      setBusy(true);
      try {
        const result = await chrome.runtime.sendMessage(message);
        if (isPanelResponse(result)) {
          setSnapshot(result.snapshot);
          if (result.error) {
            setPanelError(result.error);
          }
          return { ...result.snapshot, error: result.error };
        }
        if (isSnapshot(result)) {
          setSnapshot(result);
          return result;
        }
        throw new Error("The extension background did not return a valid response.");
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        setPanelError(detail);
        return { ...snapshot, error: detail };
      } finally {
        setBusy(false);
      }
    },
    [snapshot],
  );

  const saveAutoConnect = useCallback(
    async (enabled: boolean): Promise<void> => {
      setAutoConnect(enabled);
      await chrome.storage.local.set({ autoConnectNativeHost: enabled });
      if (enabled && snapshot.host === "disconnected") {
        await dispatch({ type: "host.connect" });
      }
    },
    [dispatch, snapshot.host],
  );

  return { snapshot, panelError, busy, autoConnect, dispatch, saveAutoConnect };
}

function isSnapshot(value: unknown): value is ExtensionSnapshot {
  return typeof value === "object" && value !== null && "host" in value;
}

function isPanelResponse(value: unknown): value is BackgroundErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "snapshot" in value &&
    isSnapshot(value.snapshot)
  );
}
