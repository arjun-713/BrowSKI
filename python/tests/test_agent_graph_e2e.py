"""Graph-level browser workflows against small local HTTP fixtures."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime

pytestmark = pytest.mark.asyncio

SPA_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>SPA routes</title>
  </head>
  <body>
    <main>
      <h1 id="heading">Landing</h1>
      <button id="to-a">Section A</button>
      <button id="to-b">Section B</button>
    </main>
    <script>
      function go(name, hash) {
        history.pushState({}, '', hash);
        document.querySelector('#heading').textContent = name;
      }
      document.querySelector('#to-a').addEventListener('click', () => go('Alpha', '#/a'));
      document.querySelector('#to-b').addEventListener('click', () => go('Beta', '#/b'));
    </script>
  </body>
</html>"""

STAGNANT_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Stagnation fixture</title>
  </head>
  <body>
    <main>
      <h1>Unchanged page</h1>
      <button type="button">Repeat action</button>
    </main>
  </body>
</html>"""


class _FixtureHandler(BaseHTTPRequestHandler):
    html = ""

    def do_GET(self) -> None:
        body = self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextmanager
def serve_fixture(html: str) -> Generator[str, None, None]:
    """Serve one deterministic HTML page on an ephemeral loopback port."""

    handler = type("FixtureHandler", (_FixtureHandler,), {"html": html})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _element(snapshot: SemanticSnapshot, name: str) -> ElementRef:
    element = next(
        item for item in snapshot.elements if item.accessible_name == name or item.text == name
    )
    return ElementRef(ref=element.ref, id=element.id, generation=element.generation)


class SpaWizardAgent(Agent):
    def __init__(self, fixture_url: str) -> None:
        self.fixture_url = fixture_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url.split("#", maxsplit=1)[0] != self.fixture_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.fixture_url))

        if snapshot.url.endswith("#/b"):
            return AgentDecision(done=True, result_summary="The SPA reached section Beta.")
        next_section = "Section B" if snapshot.url.endswith("#/a") else "Section A"
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=_element(snapshot, next_section),
            )
        )


class RepeatingMissingTargetAgent(Agent):
    def __init__(self, fixture_url: str) -> None:
        self.fixture_url = fixture_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url != self.fixture_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.fixture_url))
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(
                    ref="@missing_target",
                    id=999_999,
                    generation=snapshot.state_generation,
                ),
            )
        )


async def test_graph_completes_multi_step_spa_form() -> None:
    with serve_fixture(SPA_HTML) as fixture_url:
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                SpaWizardAgent(fixture_url),
                browser,
                config=AgentConfig(max_steps=12, max_llm_calls=16),
            )
            result = await runtime.run("Navigate through two SPA sections.")
            snapshot = await browser.observe()

    assert result.done
    assert result.status == "completed"
    # The first verified action navigates from the browser's blank tab to the fixture.
    assert result.steps_taken == 3
    assert "Beta" in (snapshot.text_excerpt or "")


async def test_graph_stops_when_stagnation_budget_is_exhausted() -> None:
    with serve_fixture(STAGNANT_HTML) as fixture_url:
        async with BrowserSession.launch() as browser:
            runtime = AgentRuntime(
                RepeatingMissingTargetAgent(fixture_url),
                browser,
                config=AgentConfig(
                    max_steps=20,
                    max_llm_calls=20,
                    max_stagnant_steps=1,
                    max_recovery_actions=8,
                ),
            )
            result = await runtime.run("Repeat the unavailable control until stopped.")

    assert result.status == "awaiting_user"
    assert not result.done
    assert result.stagnant_steps == 1
    assert result.recovery_count == 1
    assert result.recovery_count < 8
    assert "Recovery:" in (result.result_summary or "")
