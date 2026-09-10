"""Typer CLI for the browser agent."""

from __future__ import annotations

import asyncio
import json

import typer
from rich import print as rprint

app = typer.Typer(name="agent", help="General-purpose browser agent (scaffold v0.1).")


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
def resume(run_id: str = typer.Argument(...)) -> None:  # pragma: no cover
    rprint(f"[yellow]resume {run_id}[/yellow]: lands in Milestone 5 (persistence).")


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
