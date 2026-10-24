import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { ExtensionSnapshot } from "../../src/protocol";

const runtime = vi.hoisted(() => ({
  snapshot: {} as ExtensionSnapshot,
  dispatch: vi.fn(),
}));
vi.mock("./useRuntimeConnection", () => ({
  useRuntimeConnection: () => ({
    snapshot: runtime.snapshot,
    busy: false,
    panelError: null,
    autoConnect: false,
    dispatch: runtime.dispatch,
    saveAutoConnect: vi.fn(),
  }),
}));

beforeEach(() => {
  vi.stubGlobal("chrome", { runtime: { getManifest: () => ({ version: "0.3.0" }) } });
  runtime.snapshot = {
    host: "connected",
    hostError: null,
    protocolReady: true,
    session: {
      sessionId: "session",
      runId: "run",
      status: "idle",
      updatedAt: "2026-10-22T10:00:00Z",
    },
    events: [],
    pendingApproval: null,
    openAiKeyConfigured: true,
    settingsError: null,
    runtimeSettings: {
      engine: "general",
      textProvider: "openai",
      textModel: "gpt-6-luna",
      allowPaidApi: true,
      fastProvider: "laya",
      effort: "none",
      privacyMode: "standard",
      traceLevel: "standard",
      layaMode: "disabled",
      confirmHighRiskActions: true,
      extensionTransport: "native_host",
    },
    selectedTab: null,
    attachment: null,
  };
  runtime.dispatch.mockReset().mockImplementation(async () => runtime.snapshot);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("agent panel", () => {
  it("keeps attachment and version out of the main view and preserves drafts through Settings", async () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: "Capture active tab" })).toBeNull();
    expect(screen.queryByText("0.3.0")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Summarize this page" }));
    expect(screen.getByRole("textbox", { name: "Task instruction" })).toHaveProperty(
      "value",
      "Summarize the key points on this page.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText("0.3.0")).toBeTruthy();
    expect(screen.getByLabelText("Engine")).toHaveProperty("value", "general");
    expect(screen.queryByRole("button", { name: "Capture active tab" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back to task" }));
    expect(screen.getByRole("textbox", { name: "Task instruction" })).toHaveProperty(
      "value",
      "Summarize the key points on this page.",
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send task" })).toHaveProperty(
        "disabled",
        false,
      ),
    );
  });

  it("shows last results, session history and a full task draft on Run again", async () => {
    const { rerender } = render(<App />);
    const task = "Read and summarize this page. ".repeat(15).trim();
    const input = screen.getByRole("textbox", { name: "Task instruction" });
    fireEvent.change(input, { target: { value: task } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(runtime.dispatch).toHaveBeenCalledWith({ type: "task.submit", task }),
    );
    runtime.snapshot = {
      ...runtime.snapshot,
      session: {
        ...runtime.snapshot.session!,
        status: "completed",
        taskLabel: task.slice(0, 200),
      },
      lastResult: {
        sessionId: "session",
        runId: "run",
        outcome: "verified_success",
        summary: "Found the answer",
        answer: "The final answer.",
        verdict: { verified: true, reason: "Confirmed on the page." },
        finishedAt: "2026-10-22T10:01:00Z",
      },
    };
    rerender(<App />);
    expect(screen.getByText("Verified")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(screen.getByRole("textbox", { name: "Task instruction" })).toHaveProperty(
      "value",
      task,
    );
    fireEvent.click(screen.getByRole("button", { name: "Task history" }));
    expect(screen.getByRole("region", { name: "Recent tasks" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Read and summarize this page/ }),
    ).toBeTruthy();
  });

  it("brings a new risky-action request back from Settings into the thread", async () => {
    const { rerender } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    runtime.snapshot = {
      ...runtime.snapshot,
      session: {
        ...runtime.snapshot.session!,
        status: "awaiting_approval",
        taskLabel: "Post a reply",
      },
      pendingApproval: {
        approvalId: "approval",
        sessionId: "session",
        title: "Post this reply?",
        summary: "A reply is ready to post.",
        risk: "high",
        details: { reason: "Sending or publishing content" },
      },
    };
    rerender(<App />);
    await screen.findByRole("button", { name: "Approve action" });
    expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull();
    expect(screen.getByRole("button", { name: "New task" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    await waitFor(() =>
      expect(runtime.dispatch).toHaveBeenCalledWith({
        type: "approval.respond",
        approvalId: "approval",
        approved: false,
      }),
    );
  });
});
