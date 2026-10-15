"""Compare independent local fixture state against a case's gold state."""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "task_mix"
MAX_STATE_BYTES = 64 * 1024

COLLECTOR_SCRIPT = r"""<script>
(() => {
  const injectedCaseId = __ACTIVE_CASE_ID__;
  try {
    const queryCaseId = new URL(location.href).searchParams.get("benchmark_case");
    if (!sessionStorage.getItem("benchmark_case") && (queryCaseId || injectedCaseId)) {
      sessionStorage.setItem("benchmark_case", queryCaseId || injectedCaseId);
    }
  } catch (_) {}
  let caseId = null;
  try { caseId = sessionStorage.getItem("benchmark_case"); } catch (_) {}
  if (!caseId || location.pathname.startsWith("/__bench_state")) return;

  let timer;
  const capture = () => {
    const inputs = {}, checked = {}, selected = {};
    for (const element of document.querySelectorAll("input[id],textarea[id],select[id]")) {
      if (element.type === "checkbox" || element.type === "radio") {
        checked[element.id] = Boolean(element.checked);
      } else if (element.tagName === "SELECT") {
        selected[element.id] = element.selectedOptions[0]?.textContent?.trim() || "";
      } else {
        inputs[element.id] = String(element.value || "").slice(0, 1000);
      }
    }
    const body = {
      case_id: caseId, url: location.href, inputs, checked, selected,
      visible_text: (document.body?.innerText || "").slice(0, 20000),
      submitted: Boolean(window.__benchmarkSubmitted),
    };
    const encoded = JSON.stringify(body);
    if (encoded.length > 60000) return;
    fetch("/__bench_state", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: encoded, keepalive: true,
    }).catch(() => {});
  };
  document.addEventListener("submit", () => {
    window.__benchmarkSubmitted = true;
    capture();
  }, true);
  document.addEventListener("input", capture, true);
  document.addEventListener("change", capture, true);
  document.addEventListener("click", () => {
    clearTimeout(timer);
    timer = setTimeout(capture, 30);
  }, true);
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(capture, 60);
  }).observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true,
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", capture, {once: true});
  } else {
    capture();
  }
})();
</script>"""


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.state_lock = threading.Lock()
        self.active_case_id: str | None = None
        super().__init__(("127.0.0.1", 0), FixtureHandler)

    @property
    def base_url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"

    def activate_case(self, case_id: str) -> None:
        with self.state_lock:
            self.active_case_id = case_id
            self.states.pop(case_id, None)


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith("/task-mix/"):
            self.send_error(404)
            return
        fixture = (FIXTURE_ROOT / path.removeprefix("/task-mix/")).resolve()
        if not fixture.is_relative_to(FIXTURE_ROOT.resolve()) or not fixture.is_file():
            self.send_error(404)
            return
        payload = fixture.read_bytes()
        with self.server.state_lock:
            active_case_id = self.server.active_case_id
        if b"</body>" in payload:
            payload = payload.replace(
                b"</body>",
                COLLECTOR_SCRIPT.replace(
                    "__ACTIVE_CASE_ID__", json.dumps(active_case_id)
                ).encode()
                + b"</body>",
                1,
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/__bench_state":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 2 or size > MAX_STATE_BYTES:
                raise ValueError("state size outside limit")
            state = json.loads(self.rfile.read(size))
            case_id = state.get("case_id")
            if not isinstance(case_id, str) or len(case_id) > 80:
                raise ValueError("invalid case id")
            with self.server.state_lock:
                if case_id != self.server.active_case_id:
                    raise ValueError("state is not for the active case")
                current = self.server.states.setdefault(case_id, {"pages": {}})
                page_path = urlsplit(str(state.get("url", ""))).path
                pages = current["pages"]
                previous = pages.get(page_path, {})
                page = dict(state)
                for field in ("inputs", "checked", "selected"):
                    page[field] = {**previous.get(field, {}), **state.get(field, {})}
                page["submitted"] = bool(
                    previous.get("submitted") or state.get("submitted")
                )
                pages[page_path] = page
                for field in ("inputs", "checked", "selected"):
                    current[field] = {
                        key: value
                        for page_state in pages.values()
                        for key, value in page_state.get(field, {}).items()
                    }
                current["submitted"] = any(
                    page_state.get("submitted", False) for page_state in pages.values()
                )
                self.server.states[case_id] = current
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


class FixtureStateServer(FixtureServer):
    """Named benchmark-only fixture host with an evaluator state endpoint."""


def evaluate_case(
    case: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
    *,
    runtime_status: str,
    tab_urls: Sequence[str] = (),
    active_url: str | None = None,
) -> dict[str, Any]:
    """Return per-assertion outcomes; absent evidence is always a failure."""
    gold = case["gold"]
    state = observed or {}
    actual_inputs = state.get("inputs", {})
    actual_checked = state.get("checked", {})
    actual_selected = state.get("selected", {})
    pages = state.get("pages", {})
    active_path = urlsplit(active_url or "").path
    active_page = pages.get(active_path, {}) if active_path else {}
    actual_text = str(active_page.get("visible_text", ""))

    checks: dict[str, bool] = {}
    for key, value in gold["inputs"].items():
        checks[f"input:{key}"] = actual_inputs.get(key) == value
    for key, value in gold["checked"].items():
        checks[f"checked:{key}"] = actual_checked.get(key) is value
    for key, value in gold["selected"].items():
        checks[f"selected:{key}"] = actual_selected.get(key) == value
    for value in gold["visible_text"]:
        checks[f"visible_text:{value}"] = value in actual_text

    actual_paths = {urlsplit(url).path for url in tab_urls}
    for path in gold.get("tab_paths", []):
        checks[f"tab_path:{path}"] = path in actual_paths

    expected_outcome = gold.get("user_outcome", "none")
    if expected_outcome == "ask_user":
        checks["user_outcome"] = runtime_status == "awaiting_user"
    elif expected_outcome == "confirmation_required":
        checks["user_outcome"] = runtime_status == "pending_confirmation"
        checks["confirmation_status"] = (
            runtime_status == "pending_confirmation"
            if gold.get("confirmation_status") == "pending"
            else runtime_status != "pending_confirmation"
        )
    else:
        checks["user_outcome"] = runtime_status == "completed"

    expected_submitted = bool(gold.get("submitted", False))
    checks["submitted"] = bool(state.get("submitted", False)) is expected_submitted
    return {
        "success": observed is not None and bool(checks) and all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "observed_state_available": observed is not None,
    }


def write_summary_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    """Write every case, retaining failure details instead of filtering rows."""
    fields = (
        "case_id",
        "split",
        "difficulty",
        "variant",
        "order",
        "success",
        "runtime_status",
        "latency_ms",
        "startup_ms",
        "actions_completed",
        "luna_calls",
        "laya_calls",
        "laya_accept_count",
        "laya_fallback_count",
        "escalation_count",
        "failed_checks",
        "errors",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in fields}
            for key in ("failed_checks", "errors"):
                value = (
                    record.get("evaluation", {}).get("failed_checks", [])
                    if key == "failed_checks"
                    else record.get("errors", [])
                )
                row[key] = " | ".join(str(item) for item in value)
            writer.writerow(row)
