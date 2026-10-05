"""Typer CLI for the browser agent."""

from __future__ import annotations

import asyncio
import json

import typer
from rich import print as rprint

app = typer.Typer(name="agent", help="BROWSKI browser runtime.")


@app.command()
def run(
    url: str = typer.Argument(..., help="URL to navigate to and observe."),
    headless: bool = typer.Option(True, help="Run Chromium headless."),
) -> None:
    """Navigate to URL and print the observed snapshot (vertical slice)."""
    from browser_agent import BrowserSession

    async def _run() -> None:
        async with BrowserSession.launch(headless=headless) as browser:
            await browser.navigate(url)
            snapshot = await browser.observe()
            rprint(json.dumps(snapshot.model_dump(), indent=2))

    asyncio.run(_run())


@app.command()
def task(
    goal: str = typer.Argument(..., help="Natural-language browser task."),
    url: str | None = typer.Option(None, help="Optional starting page URL."),
    headless: bool = typer.Option(True, help="Run Chromium headless."),
    provider: str = typer.Option("laya", help="System One provider: laya, jev, or adaptive."),
    checkpoint_db: str = typer.Option(
        "browski-checkpoints.sqlite",
        help="SQLite checkpoint database for this task.",
    ),
) -> None:
    """Run a task through System One, Luna escalation, and the verified browser graph."""
    from browser_agent import BrowserSession
    from browser_agent.agent import AgentRuntime, LunaDecisionAgent
    from browser_agent.decisions import (
        DecisionConfig,
        DecisionProviderName,
        create_decision_provider,
    )
    from browser_agent.reasoning import OpenAILunaProvider

    try:
        selected_provider = DecisionProviderName(provider)
    except ValueError as exc:
        raise typer.BadParameter("choose laya, jev, or adaptive") from exc

    async def _run_task() -> None:
        config = DecisionConfig(provider=selected_provider)
        decisions = create_decision_provider(config)
        agent = LunaDecisionAgent(decisions, OpenAILunaProvider())
        async with BrowserSession.launch(headless=headless) as browser:
            if url:
                await browser.navigate(url)
            async with AgentRuntime.open_sqlite(
                agent,
                browser,
                database=checkpoint_db,
                decision_provider=decisions,
            ) as runtime:
                result = await runtime.run(goal)
        rprint(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "done": result.done,
                    "steps_taken": result.steps_taken,
                    "result_summary": result.result_summary,
                    "recovery_history": result.recovery_history,
                },
                indent=2,
            )
        )

    asyncio.run(_run_task())


@app.command()
def resume(run_id: str = typer.Argument(...)) -> None:  # pragma: no cover
    rprint(
        f"[yellow]resume {run_id}[/yellow]: use AgentRuntime.resume(run_id); "
        "the CLI command is not wired yet."
    )


@app.command()
def inspect(run_id: str = typer.Argument(...)) -> None:  # pragma: no cover
    rprint(f"[yellow]inspect {run_id}[/yellow]: lands with the trace viewer.")


@app.command()
def benchmark(suite: str = typer.Argument("synthetic")) -> None:  # pragma: no cover
    rprint(f"[yellow]benchmark {suite}[/yellow]: see benchmarks/README.md (Milestone 9).")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
