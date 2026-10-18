"""Local-first Fast commands and explicit checkpoint preparation."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import typer

from browser_agent.engines.contracts import CompletionCriteria, EngineEvent, EngineStatus


def prepare_laya(
    directory: str = typer.Option(
        ".browser-data/laya-browser-v19s", help="Ignored local checkpoint directory."
    ),
) -> None:
    """Download the pinned browser-tuned checkpoint; never run inference or training."""
    from pathlib import Path

    from browser_agent.engines.laya_worker import LAYA_REVISION, validate_checkpoint

    try:
        import huggingface_hub
    except ImportError:
        typer.echo("Install browser-agent[laya-cpu] before preparing Laya.", err=True)
        raise typer.Exit(1) from None
    typer.echo("Downloading pinned Laya browser v19s (about 644 MB plus tokenizer).", err=True)
    target = Path(directory)
    try:
        cast(Any, huggingface_hub).snapshot_download(
            "cklxx/laya-browser",
            revision=LAYA_REVISION,
            local_dir=target,
            allow_patterns=[
                "model.safetensors",
                "config.json",
                "modeling_laya_browser.py",
                "rl_agent_config.json",
                "tokenizer/*",
                "README.md",
            ],
        )
        (target / "REVISION").write_text(LAYA_REVISION + "\n")
        validate_checkpoint(target)
    except Exception as exc:
        typer.echo(
            f"Laya preparation failed ({type(exc).__name__}); no inference was started.", err=True
        )
        raise typer.Exit(1) from None
    typer.echo(f"Laya v19s ready at {target}; revision {LAYA_REVISION}.")


def fast(
    goal: str = typer.Argument(..., help="Same-site navigation task; no text model is called."),
    start_url: str = typer.Option(..., help="Explicit starting page for the task-owned browser."),
    provider: str = typer.Option(
        "laya", help="Fast decision provider: laya (local) or jev (hosted)."
    ),
    checkpoint: str = typer.Option(
        ".browser-data/laya-browser-v19s", help="Prepared local Laya checkpoint."
    ),
    allow_paid_api: bool = typer.Option(
        False, "--allow-paid-api", help="Explicit opt-in for hosted Jev."
    ),
    verify_url: str | None = typer.Option(None, help="Independent exact final URL criterion."),
    verify_heading: str | None = typer.Option(None, help="Independent visible H1 criterion."),
    max_steps: int = typer.Option(12, min=1, max=100, help="Hard Fast decision budget."),
    headless: bool = typer.Option(True, help="Use an isolated headless Chrome session."),
) -> None:
    """Run local Laya by default; Jev requires explicit selection, permission and credentials."""
    import os
    from pathlib import Path

    from browser_agent.engines.fast import FastConfig, run_fast
    from browser_agent.engines.fast_contract import FastDecisionProvider
    from browser_agent.engines.fast_providers import JevFastProvider, LayaFastProvider

    if bool(verify_url) != bool(verify_heading):
        raise typer.BadParameter("Supply both --verify-url and --verify-heading, or neither.")
    try:
        selected: FastDecisionProvider
        if provider == "laya":
            from browser_agent.engines.laya_worker import validate_checkpoint

            validate_checkpoint(Path(checkpoint))
            selected = LayaFastProvider(Path(checkpoint))
        elif provider == "jev":
            selected = JevFastProvider(
                api_key=os.environ.get("TYPESAFE_API_KEY"),
                allow_paid_api=allow_paid_api,
            )
        else:
            raise ValueError("Choose --provider laya or --provider jev.")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    async def progress(event: EngineEvent) -> None:
        detail = f" / {event.operation}" if event.operation else ""
        typer.echo(f"fast / {event.provider} · step {event.step} · {event.kind}{detail}", err=True)

    criteria = (
        CompletionCriteria(url=verify_url, heading=verify_heading)
        if verify_url is not None and verify_heading is not None
        else None
    )
    try:
        result = asyncio.run(
            run_fast(
                goal,
                start_url,
                selected,
                FastConfig(max_steps=max_steps, headless=headless),
                criteria=criteria,
                event_sink=progress,
            )
        )
    except KeyboardInterrupt:
        typer.echo("Fast task cancelled; closing its browser and inference process.", err=True)
        raise typer.Exit(130) from None
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(result.model_dump_json(indent=2))
    if result.status is not EngineStatus.COMPLETED:
        raise typer.Exit(2)


def compare_fast(
    input_path: str = typer.Argument(
        ..., help="Saved Fast request JSON (v2 or legacy v1); no browser actions."
    ),
    checkpoint: str = typer.Option(
        ".browser-data/laya-browser-v19s", help="Prepared CPU Laya checkpoint."
    ),
    allow_paid_api: bool = typer.Option(
        False, "--allow-paid-api", help="Explicit opt-in for the Jev comparison request."
    ),
    jev_endpoint: str = typer.Option(
        "https://api.typesafe.ai/v1/systemone", help="Configured Jev HTTPS endpoint."
    ),
) -> None:
    """Compare local Laya and optional hosted Jev on exactly the same saved input."""
    import json
    import os
    from pathlib import Path

    from browser_agent.engines.fast_contract import FastRequest
    from browser_agent.engines.fast_providers import JevFastProvider, LayaFastProvider
    from browser_agent.engines.laya_worker import validate_checkpoint

    # Check permission/credentials before loading a local model or reading input.
    try:
        jev = JevFastProvider(
            api_key=os.environ.get("TYPESAFE_API_KEY"),
            allow_paid_api=allow_paid_api,
            endpoint=jev_endpoint,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None
    try:
        source = Path(input_path)
        if not source.is_file() or source.stat().st_size > 256 * 1024:
            raise ValueError("Input exceeds comparison budget")
        with source.open("rb") as stream:
            data = stream.read(256 * 1024 + 1)
        if len(data) > 256 * 1024:
            raise ValueError("Input exceeds comparison budget")
        request = FastRequest.model_validate_json(data)
        path = Path(checkpoint)
        validate_checkpoint(path)
    except (OSError, ValueError):
        raise typer.BadParameter(
            "Use a valid bounded browski.fast.v2 input and a prepared checkpoint. "
            "No inference started."
        ) from None
    laya = LayaFastProvider(path)

    async def compare() -> dict[str, object]:
        try:
            local = await laya.predict(request)
            hosted = await jev.predict(request)
            return {
                "contract_version": request.version,
                "observation_id": request.observation.id,
                "laya": local.model_dump(mode="json"),
                "jev": hosted.model_dump(mode="json"),
                "same_choice": (local.operation, local.candidate_id)
                == (hosted.operation, hosted.candidate_id),
                "browser_actions": 0,
            }
        finally:
            await laya.aclose()
            await jev.aclose()

    try:
        output = asyncio.run(compare())
    except KeyboardInterrupt:
        typer.echo("Comparison cancelled; inference resources closed.", err=True)
        raise typer.Exit(130) from None
    except Exception as error:
        typer.echo(
            f"Comparison failed ({type(error).__name__}); no browser action executed.", err=True
        )
        raise typer.Exit(1) from None
    typer.echo(json.dumps(output, indent=2))
