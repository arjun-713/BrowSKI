import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmationCard } from "../../components/ConfirmationCard";
import { ConnectionStatus } from "../../components/ConnectionStatus";
import { SettingsPanel } from "../../components/SettingsPanel";
import { TaskComposer } from "../../components/TaskComposer";
import type {
  ExtensionSnapshot,
  PendingApproval,
  RuntimeSettingsUpdate,
} from "../../src/protocol";
import { useRuntimeConnection } from "./useRuntimeConnection";

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

beforeEach(() => {
  vi.stubGlobal("chrome", { runtime: { getManifest: () => ({ version: "0.3.0" }) } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("panel components", () => {
  it("shows unavailable and host-error connection states", () => {
    const { rerender } = render(
      <ConnectionStatus snapshot={EMPTY_SNAPSHOT} busy={false} onDispatch={vi.fn()} />,
    );

    expect(screen.getByRole("heading", { name: "Browser companion" })).toBeTruthy();
    expect(screen.getByText("Disconnected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect runtime host" })).toBeTruthy();

    rerender(
      <ConnectionStatus
        snapshot={{
          ...EMPTY_SNAPSHOT,
          host: "error",
          hostError: "Native host unavailable",
        }}
        busy={false}
        onDispatch={vi.fn()}
      />,
    );

    expect(screen.getByText("Connection error")).toBeTruthy();
    expect(screen.getByText("Native host unavailable")).toBeTruthy();
  });

  it("refuses a new task while the runtime session is paused", () => {
    const onDispatch = vi.fn().mockResolvedValue({});
    render(
      <TaskComposer
        protocolReady
        session={{ status: "paused" }}
        events={[]}
        busy={false}
        onDispatch={onDispatch}
      />,
    );

    expect(screen.queryByRole("button", { name: "Send task" })).toBeNull();
    fireEvent.submit(screen.getByRole("button", { name: "Stop task" }).closest("form")!);

    expect(onDispatch).not.toHaveBeenCalled();
  });

  it("routes approval once and disables repeated responses", async () => {
    const approval: PendingApproval = {
      approvalId: "approval-1",
      sessionId: "session-1",
      title: "Confirm navigation",
      summary: "The runtime is waiting for permission to navigate.",
      risk: "medium",
    };
    const onRespond = vi.fn().mockResolvedValue(undefined);
    render(<ConfirmationCard approval={approval} busy={false} onRespond={onRespond} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve action" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve action" }));

    await waitFor(() => {
      expect(onRespond).toHaveBeenNthCalledWith(1, approval, true);
      expect(onRespond).toHaveBeenCalledTimes(1);
    });
  });

  it("saves only supported runtime settings and shows fixed safety state", async () => {
    const settings = {
      effort: "low",
      privacyMode: "standard",
      layaMode: "shadow",
      traceLevel: "standard",
      confirmHighRiskActions: true,
      extensionTransport: "native_host",
    } as const;
    const onSaveRuntimeSettings = vi.fn<(value: RuntimeSettingsUpdate) => Promise<void>>();
    render(
      <SettingsPanel
        snapshot={{
          ...EMPTY_SNAPSHOT,
          protocolReady: true,
          runtimeSettings: settings,
        }}
        busy={false}
        autoConnect={false}
        onDispatch={vi.fn().mockResolvedValue({})}
        onSaveAutoConnect={vi.fn().mockResolvedValue(undefined)}
        onSaveRuntimeSettings={onSaveRuntimeSettings.mockResolvedValue(undefined)}
      />,
    );
    fireEvent.click(screen.getByText("Advanced"));

    fireEvent.change(screen.getByLabelText("Default reasoning effort"), {
      target: { value: "none" },
    });
    fireEvent.change(screen.getByLabelText("Privacy mode"), {
      target: { value: "offline" },
    });
    fireEvent.change(screen.getByLabelText("Laya comparison"), {
      target: { value: "disabled" },
    });
    fireEvent.change(screen.getByLabelText("Debug capture"), {
      target: { value: "detailed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(onSaveRuntimeSettings).toHaveBeenCalledWith({
        effort: "none",
        privacyMode: "offline",
        layaMode: "disabled",
        traceLevel: "detailed",
      });
    });
    expect(screen.getByText("always require your approval")).toBeTruthy();
    expect(screen.getByText(/cannot be disabled here/)).toBeTruthy();
    expect(screen.getByText(/Legacy uses an explicitly attached tab/)).toBeTruthy();
  });
});

describe("useRuntimeConnection", () => {
  it("surfaces a runtime messaging failure without treating it as success", async () => {
    const sendMessage = vi.fn().mockRejectedValue(new Error("Native host unavailable"));
    const connect = vi.fn(() => ({
      onMessage: { addListener: vi.fn() },
      disconnect: vi.fn(),
    }));
    vi.stubGlobal("chrome", {
      runtime: { connect, sendMessage },
      storage: { local: { get: vi.fn().mockResolvedValue({}), set: vi.fn() } },
    });

    const { result } = renderHook(() => useRuntimeConnection());
    await act(async () => {
      await result.current.dispatch({ type: "host.connect" });
    });

    expect(result.current.panelError).toBe("Native host unavailable");
    expect(result.current.snapshot.host).toBe("disconnected");
  });
});
