import { parseOwnedTabUrl } from "./owned-tabs";

export const MAX_TASK_LENGTH = 4000;
export const MAX_CONTEXT_ITEMS = 5;
export const MAX_FILE_BYTES = 32 * 1024;

export type ComposerContext = {
  id: string;
  kind: "tab" | "link" | "file";
  label: string;
  content: string;
};

export type TabReference = { id: number; title: string; url: string };

export const SHORTCUTS = [
  {
    id: "summarize",
    label: "Summarize this page",
    detail: "Start with the main points",
    prompt: "Summarize the key information on the attached page.",
  },
  {
    id: "extract",
    label: "Extract information",
    detail: "Turn page details into a list",
    prompt: "Extract the following information from the attached page: ",
  },
  {
    id: "compare",
    label: "Compare sources",
    detail: "Add tabs or links with @",
    prompt: "Compare the referenced sources. Focus on: ",
  },
] as const;

export function composeTask(task: string, context: ComposerContext[]): string {
  if (context.length === 0) return task.trim();
  const references = context.map((item) => {
    const heading = item.kind === "file" ? "Reference file" : "Reference link";
    return `${heading}: ${item.label}\n${item.content}`;
  });
  return [
    task.trim(),
    "User-provided reference context (mentioning a tab does not grant control):",
    ...references,
  ].join("\n\n");
}

export function linkContext(value: string, label?: string): ComposerContext {
  const url = parseOwnedTabUrl(value).href;
  return {
    id: `link:${url}`,
    kind: "link",
    label: label?.slice(0, 160) || new URL(url).hostname,
    content: url,
  };
}

export async function readTextAttachment(file: File): Promise<ComposerContext> {
  if (!/\.(txt|md|csv|json)$/i.test(file.name)) {
    throw new Error(
      "Choose a .txt, .md, .csv, or .json file. PDF and images are not supported yet.",
    );
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(`${file.name} is too large. Choose a text file under 32 KB.`);
  }
  const content = await file.text();
  if (!content.trim() || content.includes("\0") || content.includes("\uFFFD")) {
    throw new Error(`${file.name} must contain readable UTF-8 text.`);
  }
  return { id: crypto.randomUUID(), kind: "file", label: file.name.slice(0, 160), content };
}

export async function listReferenceTabs(): Promise<TabReference[]> {
  const tabs = await chrome.tabs.query({ currentWindow: true });
  return tabs.flatMap((tab) => {
    if (tab.id === undefined || !tab.url) return [];
    try {
      const url = parseOwnedTabUrl(tab.url).href;
      return [
        { id: tab.id, title: (tab.title || new URL(url).hostname).slice(0, 160), url },
      ];
    } catch {
      // Browser settings and extension pages cannot be task references.
      return [];
    }
  });
}

export type ComposerTrigger = { kind: "/" | "@"; query: string; start: number };

export function getComposerTrigger(text: string, caret: number): ComposerTrigger | null {
  const match = /(?:^|\s)([/@])([^\s]*)$/.exec(text.slice(0, caret));
  if (!match) return null;
  return {
    kind: match[1] as "/" | "@",
    query: match[2],
    start: caret - match[2].length - 1,
  };
}
