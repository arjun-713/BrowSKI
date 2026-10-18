import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TaskComposer } from "../../components/TaskComposer";

beforeEach(() => {
  vi.stubGlobal("chrome", {
    tabs: {
      query: vi
        .fn()
        .mockResolvedValue([
          { id: 1, title: "Reference page", url: "https://example.org/Docs" },
        ]),
    },
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function setup(status: "idle" | "running" = "idle", protocolReady = true) {
  const onDispatch = vi.fn().mockResolvedValue({});
  render(
    <TaskComposer
      protocolReady={protocolReady}
      session={{ status }}
      events={[]}
      busy={false}
      onDispatch={onDispatch}
    />,
  );
  return { input: screen.getByRole("textbox", { name: "Task instruction" }), onDispatch };
}

describe("composer interactions", () => {
  it("keeps drafts editable offline and refuses to send them", () => {
    const { input, onDispatch } = setup("idle", false);
    fireEvent.change(input, { target: { value: "Draft offline" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input).toHaveProperty("value", "Draft offline");
    expect(screen.getByRole("button", { name: "Send task" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(onDispatch).not.toHaveBeenCalled();
  });

  it("selects a shortcut with the keyboard without submitting it", () => {
    const { input, onDispatch } = setup();
    fireEvent.change(input, { target: { value: "/" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input).toHaveProperty(
      "value",
      "Extract the following information from the attached page: ",
    );
    expect(onDispatch).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("adds and removes tab mentions, sending only selected context", async () => {
    const { input, onDispatch } = setup();
    fireEvent.change(input, { target: { value: "Read @" } });
    fireEvent.click(await screen.findByRole("option", { name: /Reference page/ }));
    expect(screen.getByRole("list", { name: "Attached references" })).toBeTruthy();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(onDispatch).toHaveBeenCalledWith({
        type: "task.submit",
        task: expect.stringContaining("https://example.org/Docs"),
      }),
    );
    await waitFor(() => expect(input).toHaveProperty("value", ""));
    expect(screen.queryByRole("list", { name: "Attached references" })).toBeNull();
    fireEvent.change(input, { target: { value: "Read @" } });
    fireEvent.click(await screen.findByRole("option", { name: /Reference page/ }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Reference page" }));
    expect(screen.queryByRole("list", { name: "Attached references" })).toBeNull();
  });

  it("retains a failed submission and never sends IME or Shift+Enter", async () => {
    const { input, onDispatch } = setup();
    onDispatch.mockResolvedValue({ error: "Disconnected" });
    fireEvent.change(input, { target: { value: "Keep my task" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onDispatch).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onDispatch).toHaveBeenCalledOnce());
    expect(input).toHaveProperty("value", "Keep my task");
  });

  it("routes /pause to the existing run control", async () => {
    const { input, onDispatch } = setup("running");
    fireEvent.change(input, { target: { value: "/pause" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(onDispatch).toHaveBeenCalledWith({ type: "task.control", control: "pause" }),
    );
  });

  it("includes file content in the bounded task and rejects excess context", async () => {
    const { input, onDispatch } = setup();
    const file = new File(["Reference text"], "brief.txt");
    Object.defineProperty(file, "text", { value: async () => "Reference text" });
    fireEvent.change(screen.getByLabelText("Attach reference files"), {
      target: { files: [file] },
    });
    await screen.findByRole("button", { name: "Remove brief.txt" });
    fireEvent.change(input, { target: { value: "Use this reference" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(onDispatch).toHaveBeenCalledWith({
        type: "task.submit",
        task: expect.stringContaining("Reference text"),
      }),
    );
    await waitFor(() => expect(input).toHaveProperty("value", ""));
    const large = new File(["x".repeat(4100)], "long.txt");
    Object.defineProperty(large, "text", { value: async () => "x".repeat(4100) });
    fireEvent.change(screen.getByLabelText("Attach reference files"), {
      target: { files: [large] },
    });
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("exceed 4,000"),
    );
    expect(screen.queryByRole("button", { name: "Remove long.txt" })).toBeNull();
  });
});
