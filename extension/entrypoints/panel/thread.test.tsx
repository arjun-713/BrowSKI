import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionTimeline } from "../../components/ActionTimeline";
import { ConfirmationCard } from "../../components/ConfirmationCard";
import { EmptyState } from "../../components/EmptyState";
import { AnswerText, ResultCard } from "../../components/ResultCard";
import { TaskComposer } from "../../components/TaskComposer";
import {
  isNativeHostMessage,
  isTimelineEvent,
  type ExtensionSnapshot,
  type PendingApproval,
  type TaskResult,
  type TimelineEvent,
} from "../../src/protocol";

const snapshot: ExtensionSnapshot = {
  host: "connected",
  hostError: null,
  protocolReady: true,
  session: { sessionId: "session", status: "idle", updatedAt: "2026-10-22T10:00:00Z" },
  events: [],
  pendingApproval: null,
  openAiKeyConfigured: true,
  settingsError: null,
  runtimeSettings: null,
  selectedTab: null,
  attachment: null,
};
const result: TaskResult = {
  sessionId: "session",
  runId: "run",
  outcome: "verified_success",
  summary: "Task verified",
  finishedAt: "2026-10-22T10:01:00Z",
  answer:
    "Alan Turing was born on **23 June 1912**.\n\n- [Source](https://en.wikipedia.org/wiki/Alan_Turing)\n- Mathematician and computer scientist",
  verdict: { verified: true, reason: "The biography and final page agree." },
  stats: { steps: 8, actions: 4, modelCalls: 6, durationMs: 65000 },
};
const approval: PendingApproval = {
  approvalId: "approval",
  sessionId: "session",
  title: "Place this order?",
  summary: "Confirm the order on this page.",
  risk: "high",
  details: {
    action: "Click Place order",
    target: "https://shop.example/checkout",
    reason: "Placing an order or payment",
  },
};
const events: TimelineEvent[] = Array.from({ length: 8 }, (_, index) => ({
  eventId: `event-${index}`,
  sessionId: "session",
  sequence: index + 1,
  createdAt: "2026-10-22T10:00:00Z",
  type: "ActionCompleted",
  label: `Read page ${index + 1}`,
  detail: `Find source ${index + 1} for the requested answer.`,
  pageUrl: "https://en.wikipedia.org/wiki/Alan_Turing",
  status: "completed",
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("task thread", () => {
  it("fills examples and provides runtime reconnect and missing-key actions", () => {
    const onExample = vi.fn();
    const onConnect = vi.fn();
    const onSettings = vi.fn();
    const props = { busy: false, onExample, onConnect, onSettings };
    const { rerender } = render(
      <EmptyState {...props} snapshot={{ ...snapshot, protocolReady: false }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Summarize this page" }));
    expect(onExample).toHaveBeenCalledWith("Summarize the key points on this page.");
    fireEvent.click(screen.getByRole("button", { name: /Retry connection/ }));
    expect(onConnect).toHaveBeenCalledOnce();
    expect(screen.getByText("browski serve")).toBeTruthy();
    rerender(
      <EmptyState {...props} snapshot={{ ...snapshot, openAiKeyConfigured: false }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Open Settings/ }));
    expect(onSettings).toHaveBeenCalledOnce();
  });

  it("collapses long runs, exposes public details and routes pause", () => {
    const onControl = vi.fn();
    render(<ActionTimeline events={events} status="running" onControl={onControl} />);
    expect(screen.getByText("Working on en.wikipedia.org…")).toBeTruthy();
    expect(screen.queryByText("Read page 1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all 8 steps" }));
    expect(screen.getByText("Read page 1")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
    fireEvent.click(screen.getByText("Read page 1"));
    expect(screen.getByText("Find source 1 for the requested answer.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pause task" }));
    expect(onControl).toHaveBeenCalledWith("pause");
  });

  it("renders a verified answer, safe links, stats, copy and run-again", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const onRunAgain = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<ResultCard result={result} onRunAgain={onRunAgain} />);
    expect(screen.getByText("Verified")).toBeTruthy();
    expect(screen.getByText(result.verdict!.reason)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Source" }).getAttribute("rel")).toBe(
      "noopener noreferrer",
    );
    expect(screen.getByRole("link", { name: "Source" }).getAttribute("target")).toBe(
      "_blank",
    );
    expect(screen.getByLabelText("Run statistics").textContent).toBe(
      "8 steps · 4 actions · 6 model calls · 1m 5s",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy answer" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(writeText).toHaveBeenCalledWith(result.answer);
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(onRunAgain).toHaveBeenCalledOnce();
  });

  it("uses legacy summaries and never renders answer HTML or dangerous links", () => {
    const text = '<img src=x onerror="alert(1)"> [bad](javascript:alert(1))';
    const { container } = render(
      <ResultCard
        result={{
          ...result,
          answer: undefined,
          summary: text,
          outcome: "partially_completed",
          verdict: { verified: false, reason: "Final state could not be confirmed." },
        }}
        onRunAgain={vi.fn()}
      />,
    );
    expect(screen.getByText("Not verified")).toBeTruthy();
    expect(screen.getByText("Partially completed")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText(text)).toBeTruthy();
  });

  it("focuses approvals, shows site and reason, sends decline once", async () => {
    const onRespond = vi.fn().mockResolvedValue(undefined);
    render(<ConfirmationCard approval={approval} busy={false} onRespond={onRespond} />);
    expect(document.activeElement?.getAttribute("aria-labelledby")).toBe(
      "approval-heading",
    );
    expect(screen.getByText("shop.example")).toBeTruthy();
    expect(screen.getByText("Placing an order or payment")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    await waitFor(() => expect(onRespond).toHaveBeenCalledWith(approval, false));
    expect(screen.getByRole("button", { name: "Approve action" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("expires approvals locally and refuses stale approval clicks", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-22T10:00:00Z"));
    const onRespond = vi.fn();
    render(
      <ConfirmationCard
        approval={{ ...approval, expiresAt: "2026-10-22T10:00:02Z" }}
        busy={false}
        onRespond={onRespond}
      />,
    );
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("timer").textContent).toBe("Expired");
    fireEvent.click(screen.getByRole("button", { name: "Approve action" }));
    expect(onRespond).not.toHaveBeenCalled();
  });

  it("switches send to Stop while running, preserving next-task drafting", async () => {
    const onDispatch = vi.fn().mockResolvedValue({});
    render(
      <TaskComposer
        protocolReady
        session={{ status: "running", runId: "run" }}
        events={[]}
        busy={false}
        engine="general"
        onDispatch={onDispatch}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task instruction" }), {
      target: { value: "Next task" },
    });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Task instruction" }), {
      key: "Enter",
    });
    expect(onDispatch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop task" }));
    await waitFor(() =>
      expect(onDispatch).toHaveBeenCalledWith({ type: "task.control", control: "stop" }),
    );
  });
});

describe("additive panel contracts", () => {
  it("accepts bounded answers and HTTP page URLs, rejects invalid values", () => {
    const frame = (payload: TaskResult) => ({
      protocolVersion: 1,
      eventId: "result",
      type: "runtime.task.result",
      payload,
    });
    expect(isNativeHostMessage(frame(result))).toBe(true);
    expect(isNativeHostMessage(frame({ ...result, answer: "x".repeat(4001) }))).toBe(false);
    expect(
      isNativeHostMessage(
        frame({ ...result, verdict: { verified: true, reason: "x".repeat(501) } }),
      ),
    ).toBe(false);
    expect(
      isNativeHostMessage(frame({ ...result, stats: { ...result.stats!, actions: -1 } })),
    ).toBe(false);
    expect(isTimelineEvent(events[0])).toBe(true);
    expect(isTimelineEvent({ ...events[0], pageUrl: "javascript:alert(1)" })).toBe(false);
    expect(
      isTimelineEvent({ ...events[0], pageUrl: "https://name:password@example.org" }),
    ).toBe(false);
  });
});

describe("answer rendering", () => {
  it("renders an agent's pipe table as a real table with escaped cells", () => {
    render(
      <AnswerText
        text={[
          "Compared prices:",
          "",
          "| Retailer | Observed price |",
          "|---|---:|",
          "| Flipkart | ₹1,23,900 |",
          "| <b>Amazon.in</b> | ₹1,23,900 |",
        ].join("\n")}
      />,
    );
    const table = screen.getByRole("table");
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Retailer",
      "Observed price",
    ]);
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(table.textContent).not.toContain("---");
    expect(screen.getByText("<b>Amazon.in</b>")).toBeTruthy();
  });
});
