"""Explicit migration engine commands; progress stays separate from JSON results."""

from __future__ import annotations

import asyncio

import typer

from browser_agent.engines.contracts import CompletionCriteria, EngineEvent, EngineStatus


def general(
    goal: str = typer.Argument(
        ..., help="Navigation or reading task for the official Browser Use Agent."
    ),
    allow_paid_api: bool = typer.Option(False, help="Explicitly permit this bounded OpenAI run."),
    model: str = typer.Option(
        "gpt-6-luna", help="OpenAI generative model; no silent model fallback."
    ),
    max_calls: int = typer.Option(3, min=1, max=10, help="Hard limit on paid inference requests."),
    max_steps: int = typer.Option(4, min=1, max=20, help="Bounded Browser Use decision steps."),
    verify_url: str | None = typer.Option(None, help="Independent exact final URL criterion."),
    verify_heading: str | None = typer.Option(None, help="Independent visible H1 criterion."),
    headless: bool = typer.Option(True, help="Use an isolated headless Chrome session."),
) -> None:
    """Run the General migration slice. Hosted inference is off until explicitly permitted."""
    if not allow_paid_api:
        raise typer.BadParameter(
            "General needs generative inference. Use --allow-paid-api for a bounded OpenAI run; "
            "Laya Fast mode remains the local target."
        )
    if bool(verify_url) != bool(verify_heading):
        raise typer.BadParameter("Supply both --verify-url and --verify-heading, or neither.")
    from browser_agent.credentials import configured_openai_api_key
    from browser_agent.engines.general import GeneralConfig, run_general

    async def progress(event: EngineEvent) -> None:
        detail = f" / {event.operation}" if event.operation else ""
        typer.echo(f"general / openai · step {event.step} · {event.kind}{detail}", err=True)

    criteria = (
        CompletionCriteria(url=verify_url, heading=verify_heading)
        if verify_url is not None and verify_heading is not None
        else None
    )
    try:
        result = asyncio.run(
            run_general(
                goal,
                GeneralConfig(
                    model=model,
                    allow_paid_api=True,
                    max_calls=max_calls,
                    max_steps=max_steps,
                    headless=headless,
                ),
                api_key=configured_openai_api_key(),
                criteria=criteria,
                event_sink=progress,
            )
        )
    except KeyboardInterrupt:
        typer.echo("General task cancelled; closing its browser.", err=True)
        raise typer.Exit(130) from None
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(result.model_dump_json(indent=2))
    if result.status is not EngineStatus.COMPLETED:
        raise typer.Exit(2)
