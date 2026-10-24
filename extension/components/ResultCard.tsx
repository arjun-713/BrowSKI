import { useState, type ReactNode } from "react";
import type { TaskResult } from "../src/protocol";
import { Icon } from "./Icon";
import { formatDuration } from "./display";

function safeLink(value: string): string | null {
  try {
    const url = new URL(value);
    if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password)
      return url.href;
  } catch {
    // Incomplete links stay readable as plain text.
  }
  return null;
}

function inlineText(text: string): ReactNode[] {
  return text
    .split(/(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>]+|\*\*[^*\n]+\*\*)/g)
    .map((part, index) => {
      const markdown = part.match(/^\[([^\]]+)\]\((.+)\)$/);
      const candidate = markdown?.[2] ?? part.replace(/[.,;]+$/, "");
      const href = safeLink(candidate);
      if (href)
        return (
          <a key={index} href={href} target="_blank" rel="noopener noreferrer">
            {markdown?.[1] ?? candidate}
          </a>
        );
      if (part.startsWith("**") && part.endsWith("**"))
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      return part;
    });
}

const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

/** A GitHub-style pipe table: header row, rule row, body rows. */
function AnswerTable({ lines }: { lines: string[] }) {
  const header = tableCells(lines[0]);
  const alignments = tableCells(lines[1]).map((rule) =>
    rule.endsWith(":") ? "right" : "left",
  );
  const rows = lines.slice(2).map(tableCells);
  return (
    <div className="answer-table-wrap">
      <table className="answer-table">
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th
                key={index}
                className={alignments[index] === "right" ? "numeric" : undefined}
              >
                {inlineText(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {header.map((_, index) => (
                <td
                  key={index}
                  className={alignments[index] === "right" ? "numeric" : undefined}
                >
                  {inlineText(row[index] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AnswerText({ text }: { text: string }) {
  return (
    <div className="answer-text">
      {text.split(/\n\s*\n/).map((block, index) => {
        const lines = block.split("\n").filter((line) => line.trim());
        if (lines.length >= 2 && TABLE_ROW.test(lines[0]) && TABLE_RULE.test(lines[1])) {
          return <AnswerTable key={index} lines={lines} />;
        }
        if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
          return (
            <ul key={index}>
              {lines.map((line, i) => (
                <li key={i}>{inlineText(line.replace(/^\s*[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
          return (
            <ol key={index}>
              {lines.map((line, i) => (
                <li key={i}>{inlineText(line.replace(/^\s*\d+\.\s+/, ""))}</li>
              ))}
            </ol>
          );
        }
        return <p key={index}>{inlineText(block)}</p>;
      })}
    </div>
  );
}

const OUTCOME_LABELS: Partial<Record<TaskResult["outcome"], string>> = {
  partially_completed: "Partially completed",
  blocked: "Blocked",
  failed: "Task failed",
  stopped: "Stopped",
  cancelled: "Stopped",
};

export function ResultCard({
  result,
  onRunAgain,
  disabled = false,
}: {
  result: TaskResult;
  onRunAgain: () => void;
  disabled?: boolean;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const verified = result.verdict?.verified ?? result.outcome === "verified_success";
  const answer = result.answer?.trim() || result.summary;
  const reason =
    result.verdict?.reason ||
    (verified ? "The runtime verified the requested outcome." : result.summary);
  const outcome = OUTCOME_LABELS[result.outcome];

  async function copyAnswer(): Promise<void> {
    try {
      await navigator.clipboard.writeText(answer);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  return (
    <section className="result-card" aria-label="Task result">
      <div className="tear" aria-hidden="true" />
      <AnswerText text={answer} />
      <div className={`verdict ${verified ? "verdict-verified" : "verdict-unverified"}`}>
        <span className="stamp">
          <Icon name={verified ? "checkCircle" : "info"} size={15} />
          <strong>{verified ? "Verified" : "Not verified"}</strong>
        </span>
        {outcome && <span className="verdict-outcome">{outcome}</span>}
      </div>
      {reason !== answer && <p className="verdict-reason">{reason}</p>}
      <div className="receipt-footer">
        {result.stats && (
          <p className="result-stats" aria-label="Run statistics">
            {[
              `${result.stats.steps} steps`,
              `${result.stats.actions} actions`,
              `${result.stats.modelCalls} model calls`,
              formatDuration(result.stats.durationMs),
            ].join(" · ")}
          </p>
        )}
        <div className="result-actions">
          <button className="text-button" onClick={() => void copyAnswer()}>
            <Icon name={copyState === "copied" ? "check" : "copy"} size={14} />
            {copyState === "copied" ? "Copied" : "Copy answer"}
          </button>
          <button className="text-button" disabled={disabled} onClick={onRunAgain}>
            <Icon name="refresh" size={14} />
            Run again
          </button>
        </div>
      </div>
      {copyState === "error" && (
        <p className="inline-error" role="alert">
          Couldn’t copy. Select the answer text and copy it manually.
        </p>
      )}
    </section>
  );
}
