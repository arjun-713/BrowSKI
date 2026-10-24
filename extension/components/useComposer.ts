import { useEffect, useRef, useState } from "react";
import {
  composeTask,
  getComposerTrigger,
  linkContext,
  listReferenceTabs,
  MAX_CONTEXT_ITEMS,
  MAX_TASK_LENGTH,
  readTextAttachment,
  SHORTCUTS,
  type ComposerContext,
  type ComposerTrigger,
  type TabReference,
} from "../src/composer-context";
import { permittedRunControls, type RunControl } from "../src/run-controls";
import type { RuntimeStatus } from "../src/protocol";
import type { ComposerOption } from "./CommandMenu";

export function useComposer({
  status,
  onControl,
  initialTask = "",
}: {
  status?: RuntimeStatus;
  initialTask?: string;
  onControl: (control: RunControl) => Promise<void>;
}) {
  const [task, setTask] = useState(initialTask);
  const [context, setContext] = useState<ComposerContext[]>([]);
  const [trigger, setTrigger] = useState<ComposerTrigger | null>(null);
  const [selected, setSelected] = useState(0);
  const [tabs, setTabs] = useState<TabReference[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const triggerKind = trigger?.kind;

  useEffect(() => {
    if (triggerKind !== "@") return;
    let cancelled = false;
    void listReferenceTabs()
      .then((result) => {
        if (!cancelled) setTabs(result);
      })
      .catch(() => {
        if (!cancelled) setError("Tabs could not be loaded. Try @ again, or paste a link.");
      });
    return () => {
      cancelled = true;
    };
  }, [triggerKind]);

  function updateTask(value: string, caret = value.length): void {
    setTask(value);
    setTrigger(getComposerTrigger(value, caret));
    setSelected(0);
    setError(null);
  }

  function insertTrigger(kind: "/" | "@"): void {
    const element = input.current;
    const start = element?.selectionStart ?? task.length;
    const end = element?.selectionEnd ?? start;
    const prefix = start > 0 && !/\s/.test(task[start - 1]) ? " " : "";
    const value = task.slice(0, start) + prefix + kind + task.slice(end);
    const caret = start + prefix.length + 1;
    updateTask(value, caret);
    requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(caret, caret);
    });
  }

  function replaceTrigger(value: string): string {
    if (!trigger) return task;
    const end = trigger.start + trigger.query.length + 1;
    return task.slice(0, trigger.start) + value + task.slice(end);
  }

  function addContext(item: ComposerContext): void {
    const next = context.some((entry) => entry.id === item.id)
      ? context
      : [...context, item];
    const nextTask = replaceTrigger("");
    if (!validateContext(nextTask, next)) return;
    setContext(next);
    setTask(nextTask);
  }

  function validateContext(value: string, items: ComposerContext[]): boolean {
    if (items.length > MAX_CONTEXT_ITEMS) {
      setError("You can add up to 5 references. Remove one to add another.");
      return false;
    }
    if (composeTask(value, items).length > MAX_TASK_LENGTH) {
      setError(
        "The task and references exceed 4,000 characters. Use a shorter file or remove a reference.",
      );
      return false;
    }
    setError(null);
    return true;
  }

  async function attachFiles(files: File[]): Promise<void> {
    if (reading || files.length === 0) return;
    setReading(true);
    setError(null);
    try {
      if (files.length + context.length > MAX_CONTEXT_ITEMS) {
        throw new Error("You can add up to 5 references. Remove one to add another.");
      }
      const additions = await Promise.all(files.map(readTextAttachment));
      const next = [...context, ...additions];
      if (validateContext(task, next)) setContext(next);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The file could not be read. Try another text file.",
      );
    } finally {
      setReading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  let options: ComposerOption[] = [];
  if (trigger?.kind === "/") {
    options = SHORTCUTS.map((shortcut) => ({
      ...shortcut,
      icon: "slash" as const,
      select: () => setTask(replaceTrigger(shortcut.prompt)),
    }));
    for (const control of status ? permittedRunControls(status) : []) {
      options.push({
        id: control,
        label: `${control[0].toUpperCase()}${control.slice(1)} task`,
        detail: "Control the current run",
        icon: control === "resume" ? "play" : control,
        select: () => {
          setTask(replaceTrigger(""));
          void onControl(control);
        },
      });
    }
    options = options.filter((option) =>
      `${option.id} ${option.label}`.toLowerCase().includes(trigger.query.toLowerCase()),
    );
  } else if (trigger?.kind === "@") {
    options = tabs
      .filter((tab) =>
        `${tab.title} ${tab.url}`.toLowerCase().includes(trigger.query.toLowerCase()),
      )
      .slice(0, 20)
      .map((tab) => ({
        id: String(tab.id),
        label: tab.title,
        detail: new URL(tab.url).hostname,
        icon: "tab",
        select: () => addContext({ ...linkContext(tab.url, tab.title), kind: "tab" }),
      }));
    try {
      const link = linkContext(trigger.query);
      options.unshift({
        id: link.id,
        label: "Add link",
        detail: link.content,
        icon: "link",
        select: () => addContext(link),
      });
    } catch {
      // Partial URLs remain a search query until they are valid HTTP(S) links.
    }
  }

  function choose(option: ComposerOption): void {
    option.select();
    setTrigger(null);
    setSelected(0);
    input.current?.focus();
  }

  return {
    task,
    context,
    setContext,
    input,
    fileInput,
    error,
    setError,
    reading,
    trigger,
    setTrigger,
    selected,
    setSelected,
    options,
    choose,
    updateTask,
    insertTrigger,
    attachFiles,
    serializedTask: composeTask(task, context),
    clear: () => {
      setTask("");
      setContext([]);
      setTrigger(null);
      setError(null);
    },
  };
}
