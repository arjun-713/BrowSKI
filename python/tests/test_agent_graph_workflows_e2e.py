"""Graph workflows for browser state changes and recovery on local pages."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticElement, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime

pytestmark = pytest.mark.asyncio

STALE_PAGE = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Rerender form</title></head>
  <body>
    <main>
      <label for="email">Email address</label>
      <input id="email" type="email">
      <button id="refresh" type="button">Refresh field</button>
      <p id="status" role="status"></p>
    </main>
    <script>
      document.querySelector('#refresh').addEventListener('click', () => {
        const field = document.querySelector('#email');
        const replacement = field.cloneNode(true);
        replacement.id = 'updated-email';
        replacement.setAttribute('aria-label', 'Updated email address');
        field.replaceWith(replacement);
        document.querySelector('label[for="email"]').textContent = 'Updated email address';
        document.querySelector('#status').textContent = 'Field was refreshed';
      });
    </script>
  </body>
</html>"""

TAB_HOME = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Research index</title></head>
  <body><main><h1>Research index</h1><p>Open the report for details.</p></main></body>
</html>"""

TAB_REPORT = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Quarterly report</title></head>
  <body>
    <main>
      <h1>Quarterly report</h1>
      <h2>The verified project code is ORBIT-42.</h2>
    </main>
  </body>
</html>"""

MULTI_LINK_HOME = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Product links</title></head>
  <body>
    <main>
      <h1>Products</h1>
      <a href="/product-a" target="_blank">Product A</a>
      <a href="/product-b" target="_blank">Product B</a>
    </main>
  </body>
</html>"""

PRODUCT_PAGE = """<!doctype html>
<html lang="en"><head><title>Product</title></head><body><h1>Product details</h1></body></html>"""

OVERLAY_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Notice overlay</title>
    <style>
      #notice {
        position: fixed;
        inset: 0;
        z-index: 10;
        background: rgb(0 0 0 / 45%);
      }
      #dismiss { position: relative; z-index: 11; }
    </style>
  </head>
  <body>
    <main>
      <h1>Protected action</h1>
      <button id="continue" type="button">Continue</button>
      <p id="status" role="status"></p>
    </main>
    <div id="notice" aria-hidden="true"></div>
    <button id="dismiss" type="button">Dismiss notice</button>
    <script>
      document.querySelector('#dismiss').addEventListener('click', () => {
        document.querySelector('#notice').remove();
        document.querySelector('#status').textContent = 'Notice dismissed';
      });
      document.querySelector('#continue').addEventListener('click', () => {
        document.querySelector('#status').textContent = 'Protected action complete';
      });
    </script>
  </body>
</html>"""

VALIDATION_PAGE = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Code validation</title></head>
  <body>
    <main>
      <h1>Access code</h1>
      <label for="code">Six-digit code</label>
      <input id="code" inputmode="numeric">
      <button id="check" type="button">Check code</button>
      <p id="status" role="status"></p>
    </main>
    <script>
      document.querySelector('#check').addEventListener('click', () => {
        const value = document.querySelector('#code').value;
        const accepted = /^\\d{6}$/.test(value);
        document.querySelector('#status').textContent = accepted
          ? 'Code accepted'
          : 'Use exactly six digits';
        document.querySelector('#check').textContent = accepted
          ? 'Code accepted'
          : 'Correct code';
      });
    </script>
  </body>
</html>"""


class _RouteHandler(BaseHTTPRequestHandler):
    pages: Mapping[str, str] = {}

    def do_GET(self) -> None:
        body = self.pages.get(self.path, "Not found").encode("utf-8")
        self.send_response(200 if self.path in self.pages else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextmanager
def serve_pages(pages: Mapping[str, str]) -> Generator[str, None, None]:
    handler = type("RouteHandler", (_RouteHandler,), {"pages": pages})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _element(snapshot: SemanticSnapshot, accessible_name: str) -> ElementRef:
    element = next(
        item
        for item in snapshot.elements
        if item.accessible_name == accessible_name or item.text == accessible_name
    )
    return ElementRef(ref=element.ref, id=element.id, generation=element.generation)


def _input(snapshot: SemanticSnapshot, accessible_name: str) -> SemanticElement:
    return next(item for item in snapshot.elements if item.accessible_name == accessible_name)


class RerenderRecoveryAgent(Agent):
    def __init__(self, page_url: str) -> None:
        self.page_url = page_url
        self.old_email_ref: ElementRef | None = None
        self.sent_stale_ref = False

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = memory
        if snapshot.url != self.page_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.page_url))

        updated_field_present = any(
            item.accessible_name == "Updated email address" for item in snapshot.elements
        )
        field_name = "Updated email address" if updated_field_present else "Email address"
        email = _input(snapshot, field_name)
        if email.value == "agent@example.test":
            return AgentDecision(done=True, result_summary="The refreshed field was filled.")
        if task.recovery_count and self.sent_stale_ref:
            return AgentDecision(
                action=BrowserAction(
                    type="type",
                    target=ElementRef(
                        ref=email.ref,
                        id=email.id,
                        generation=email.generation,
                    ),
                    text="agent@example.test",
                )
            )
        if updated_field_present:
            self.sent_stale_ref = True
            assert self.old_email_ref is not None
            return AgentDecision(
                action=BrowserAction(
                    type="type",
                    target=self.old_email_ref,
                    text="agent@example.test",
                )
            )

        self.old_email_ref = ElementRef(
            ref=email.ref,
            id=email.id,
            generation=email.generation,
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=_element(snapshot, "Refresh field"),
            )
        )


class NewTabResearchAgent(Agent):
    def __init__(self, home_url: str, report_url: str) -> None:
        self.home_url = home_url
        self.report_url = report_url
        self.home_tab: str | None = None
        self.opened_report = False

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url != self.home_url and not self.opened_report:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.home_url))

        if self.home_tab is None:
            self.home_tab = snapshot.active_tab
        if not self.opened_report:
            self.opened_report = True
            return AgentDecision(action=BrowserAction(type="new_tab"))

        if snapshot.active_tab == self.home_tab:
            report_tab = next(tab for tab in snapshot.tabs if tab != self.home_tab)
            return AgentDecision(action=BrowserAction(type="activate_tab", tab=report_tab))

        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=self.report_url))

        observed_text = [
            value
            for item in snapshot.elements
            for value in (item.accessible_name, item.text)
            if value
        ]
        observed_text.extend(block.text for block in snapshot.text_blocks)
        if any("ORBIT-42" in value for value in observed_text):
            return AgentDecision(
                done=True,
                result_summary="The report contains project code ORBIT-42.",
            )
        return AgentDecision(
            action=BrowserAction(type="wait", ms=250),
        )


class MultiLinkOpenAgent(Agent):
    def __init__(self, home_url: str) -> None:
        self.home_url = home_url
        self.source_tab: str | None = None
        self.opened: set[str] = set()
        self.proof_counts: list[int] = []

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = memory
        self.proof_counts.append(len(task.verified_link_opens))
        if snapshot.url != self.home_url and self.source_tab is None:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.home_url))
        if self.source_tab is None:
            self.source_tab = snapshot.active_tab
        if snapshot.active_tab != self.source_tab:
            return AgentDecision(action=BrowserAction(type="activate_tab", tab=self.source_tab))
        for label in ("Product A", "Product B"):
            if label in self.opened:
                continue
            link = next(
                item
                for item in snapshot.elements
                if item.role == "link" and item.accessible_name == label
            )
            self.opened.add(label)
            return AgentDecision(
                action=BrowserAction(
                    type="click",
                    target=ElementRef(ref=link.ref, id=link.id, generation=link.generation),
                )
            )
        return AgentDecision(ask_user=["End the regression flow after both links are opened."])


class OverlayRecoveryAgent(Agent):
    def __init__(self, page_url: str) -> None:
        self.page_url = page_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = memory
        if snapshot.url != self.page_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.page_url))
        status = next((item for item in snapshot.elements if item.role == "status"), None)
        status_text = status.text if status is not None and status.text is not None else ""
        if "Protected action complete" in status_text:
            return AgentDecision(done=True, result_summary="The protected action completed.")
        continue_button = next(
            (
                item
                for item in snapshot.elements
                if item.accessible_name == "Continue" or item.text == "Continue"
            ),
            None,
        )
        target_name = (
            "Continue"
            if task.recovery_count == 0
            or (continue_button is not None and continue_button.interactable)
            else "Dismiss notice"
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=_element(snapshot, target_name),
            )
        )


class ValidationCorrectionAgent(Agent):
    def __init__(self, page_url: str) -> None:
        self.page_url = page_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url != self.page_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.page_url))

        code = _input(snapshot, "Six-digit code")
        status = next((item for item in snapshot.elements if item.role == "status"), None)
        status_text = status.text if status is not None and status.text is not None else ""
        if status_text == "Code accepted":
            return AgentDecision(done=True, result_summary="The access code was accepted.")
        if status_text == "Use exactly six digits" and code.value != "123456":
            return AgentDecision(
                action=BrowserAction(
                    type="type",
                    target=ElementRef(ref=code.ref, id=code.id, generation=code.generation),
                    text="123456",
                )
            )
        if code.value:
            check_name = (
                "Correct code"
                if any(
                    item.accessible_name == "Correct code" or item.text == "Correct code"
                    for item in snapshot.elements
                )
                else "Check code"
            )
            return AgentDecision(
                action=BrowserAction(type="click", target=_element(snapshot, check_name))
            )
        return AgentDecision(
            action=BrowserAction(
                type="type",
                target=ElementRef(ref=code.ref, id=code.id, generation=code.generation),
                text="12",
            )
        )


async def test_graph_recovers_from_stale_reference_after_rerender() -> None:
    pages = {"/stale": STALE_PAGE}
    with serve_pages(pages) as base_url:
        page_url = f"{base_url}/stale"
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                RerenderRecoveryAgent(page_url),
                browser,
                config=AgentConfig(
                    max_steps=12,
                    max_recovery_actions=4,
                    confirm_high_risk=False,
                ),
            )
            result = await runtime.run("Fill the refreshed email field.")
            snapshot = await browser.observe()

    assert result.done
    assert result.recovery_count == 1
    assert _input(snapshot, "Updated email address").value == "agent@example.test"


async def test_graph_opens_new_tab_and_extracts_its_information() -> None:
    pages = {"/home": TAB_HOME, "/report": TAB_REPORT}
    with serve_pages(pages) as base_url:
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                NewTabResearchAgent(f"{base_url}/home", f"{base_url}/report"),
                browser,
                config=AgentConfig(max_steps=10),
            )
            result = await runtime.run("Read the project code in a new report tab.")
            tabs = await browser.tabs()

    assert result.done
    assert len(tabs) == 2
    assert any(tab.url.endswith("/report") for tab in tabs)


async def test_graph_records_fresh_proof_for_each_sequential_target_blank_link() -> None:
    pages = {
        "/home": MULTI_LINK_HOME,
        "/product-a": PRODUCT_PAGE,
        "/product-b": PRODUCT_PAGE,
    }
    with serve_pages(pages) as base_url:
        agent = MultiLinkOpenAgent(f"{base_url}/home")
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                agent,
                browser,
                config=AgentConfig(max_steps=16, confirm_high_risk=False),
            )
            result = await runtime.run("Open each product link in separate tabs.")
            tabs = await browser.tabs()

    assert result.status == "awaiting_user"
    assert agent.proof_counts == [0, 0, 1, 2]
    assert len(tabs) == 3


async def test_graph_dismisses_recoverable_overlay_before_proceeding() -> None:
    pages = {"/overlay": OVERLAY_PAGE}
    with serve_pages(pages) as base_url:
        page_url = f"{base_url}/overlay"
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                OverlayRecoveryAgent(page_url),
                browser,
                config=AgentConfig(max_steps=8),
            )
            result = await runtime.run("Dismiss the notice and continue.")
            snapshot = await browser.observe()

    assert result.done
    assert result.recovery_count == 1
    status = next(item for item in snapshot.elements if item.role == "status")
    assert status.text == "Protected action complete"
    assert not snapshot.dialogs


async def test_graph_corrects_field_after_validation_error() -> None:
    pages = {"/validation": VALIDATION_PAGE}
    with serve_pages(pages) as base_url:
        page_url = f"{base_url}/validation"
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                ValidationCorrectionAgent(page_url),
                browser,
                config=AgentConfig(max_steps=12, confirm_high_risk=False),
            )
            result = await runtime.run("Enter a valid six-digit access code.")
            snapshot = await browser.observe()

    assert result.done
    status = next(item for item in snapshot.elements if item.role == "status")
    assert status.text == "Code accepted"
    assert _input(snapshot, "Six-digit code").value == "123456"
