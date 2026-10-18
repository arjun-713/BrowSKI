"""Typer CLI for the browser agent."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint

from browser_agent.cli.config import (
    BrowskiConfig,
    ConfigError,
    DecisionMode,
    ExtensionTransportMode,
    load_config,
)
from browser_agent.cli.doctor import doctor
from browser_agent.cli.engines import general
from browser_agent.cli.fast import fast, prepare_laya
from browser_agent.persistence import RunMetadataError, SQLiteRunMetadataStore
from browser_agent.reasoning import ReasoningProvider
from browser_agent.vision.contracts import VisionProvider

app = typer.Typer(name="agent", help="BROWSKI browser runtime.")
app.command()(doctor)
app.command()(general)
app.command()(fast)
app.command()(prepare_laya)
runs_app = typer.Typer(name="runs", help="Inspect and clean local run metadata.")
app.add_typer(runs_app, name="runs")
ConfigPathOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help="Optional TOML configuration file.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
]
DatabasePathOption = Annotated[
    Path,
    typer.Option(
        "--database",
        help="SQLite database containing LangGraph checkpoints.",
    ),
]
SocketPathOption = Annotated[
    Path | None,
    typer.Option(
        "--socket-path",
        help="Private Unix socket path for the extension bridge.",
    ),
]


def _load_runtime_config(config_path: Path | None) -> BrowskiConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc), param_hint="--config") from exc


@app.command()
def serve(
    socket_path: SocketPathOption = None,
    config_path: ConfigPathOption = None,
    database: DatabasePathOption = Path("browski-checkpoints.sqlite"),
) -> None:
    """Serve the authenticated extension bridge and attached-browser runtime."""
    from browser_agent.extension.service import (
        BridgeServiceError,
        ExtensionBridgeService,
        default_socket_path,
    )

    config = load_config(config_path)
    if config.extension.transport_mode is ExtensionTransportMode.DISABLED:
        raise typer.BadParameter(
            "extension transport is disabled; set extension.transport_mode = 'native_host'"
        )

    service = ExtensionBridgeService(
        socket_path or default_socket_path(),
        config_path=config_path,
        database_path=database,
    )

    async def _serve() -> None:
        await service.start()
        typer.echo(
            "BROWSKI extension runtime listening at "
            f"{service.socket_path}. Attach a tab in the side panel to start a task."
        )
        await service.wait_closed()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        typer.echo("BROWSKI bridge stopped.")
    except (BridgeServiceError, OSError) as exc:
        typer.echo(f"Could not start BROWSKI extension bridge: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _resolve_provider(provider: str | None, config: BrowskiConfig) -> str | None:
    selected = provider or config.decision.provider.value
    if selected in {"jev", "adaptive"}:
        raise typer.BadParameter(
            "Jev and adaptive provider routing are disabled. Luna is the only "
            "active decision path; Laya may run as a non-executing shadow.",
            param_hint="--provider",
        )
    if selected != "laya":
        raise typer.BadParameter("only Laya shadow comparison is configurable")
    if (
        config.decision.mode != DecisionMode.SHADOW
        or not config.decision.shadow_telemetry
        or config.privacy.mode.value != "standard"
    ):
        return None
    return "laya"


def _create_luna_reasoning_provider(config: BrowskiConfig) -> ReasoningProvider | None:
    if not config.reasoning.enabled:
        return None
    if config.reasoning.provider != "openai":
        raise typer.BadParameter("only the OpenAI Luna reasoning adapter is supported")

    from browser_agent.credentials import configured_openai_api_key
    from browser_agent.providers.privacy import PrivacyMode as BoundaryPrivacyMode
    from browser_agent.providers.privacy import ProviderBoundary
    from browser_agent.reasoning import OpenAILunaProvider

    inner_provider = OpenAILunaProvider(api_key=configured_openai_api_key())
    privacy_mode = BoundaryPrivacyMode(config.privacy.mode.value)
    return ProviderBoundary(inner_provider, mode=privacy_mode)


def create_luna_reasoning_provider(config: BrowskiConfig) -> ReasoningProvider | None:
    """Create the configured Luna provider behind the privacy boundary."""
    return _create_luna_reasoning_provider(config)


def _create_luna_vision_provider(config: BrowskiConfig) -> VisionProvider | None:
    if not config.vision.enabled or not config.reasoning.enabled:
        return None

    from browser_agent.credentials import configured_openai_api_key
    from browser_agent.providers.privacy import PrivacyMode as BoundaryPrivacyMode
    from browser_agent.providers.privacy import VisionProviderBoundary
    from browser_agent.vision import OpenAILunaVisionProvider

    return VisionProviderBoundary(
        OpenAILunaVisionProvider(api_key=configured_openai_api_key()),
        mode=BoundaryPrivacyMode(config.privacy.mode.value),
    )


def create_luna_vision_provider(config: BrowskiConfig) -> VisionProvider | None:
    """Create the configured on-demand Luna vision provider."""
    return _create_luna_vision_provider(config)


@app.command("config")
def show_config(config_path: ConfigPathOption = None) -> None:
    """Show effective local policy without exposing credential values."""
    config = _load_runtime_config(config_path)
    from browser_agent.credentials import configured_openai_api_key

    key_configured = configured_openai_api_key() is not None
    laya_status = (
        "shadow only"
        if config.decision.mode == DecisionMode.SHADOW and config.decision.shadow_telemetry
        else "disabled"
    )
    rprint("[bold]BROWSKI configuration[/bold]")
    rprint("Browser modes: managed CLI and attached extension")
    rprint(f"Reasoning: {config.reasoning.provider} / {config.reasoning.model}")
    rprint(f"OpenAI key: {'configured' if key_configured else 'not configured'}")
    rprint(f"Laya: {laya_status}")
    rprint("Jev: disabled")
    rprint(f"Privacy: {config.privacy.mode.value}")
    rprint(f"High-risk confirmation: {config.safety.confirm_high_risk_actions}")
    rprint(f"On-demand vision: {'enabled' if config.vision.enabled else 'disabled'}")
    rprint(f"Extension transport: {config.extension.transport_mode.value}")


@runs_app.command("list")
def list_runs(
    database: DatabasePathOption = Path("browski-checkpoints.sqlite"),
    limit: int = typer.Option(100, min=1, max=1_000, help="Maximum records to show."),
) -> None:
    """List safe run metadata without reading task or browser content."""
    store = SQLiteRunMetadataStore(database)
    try:
        records = asyncio.run(store.list_runs(limit=limit))
    except (RunMetadataError, ValueError) as exc:
        typer.echo(f"Could not list runs: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            [
                {
                    "run_id": record.run_id,
                    "started_at": record.started_at,
                    "updated_at": record.updated_at,
                    "status": record.status,
                    "steps": record.steps,
                    "reasoning_calls": record.reasoning_calls,
                    "metrics": record.metrics.to_dict(),
                }
                for record in records
            ],
            indent=2,
        )
    )


@runs_app.command("clean")
def clean_runs(
    database: DatabasePathOption = Path("browski-checkpoints.sqlite"),
    older_than_days: int = typer.Option(
        30,
        "--older-than-days",
        min=1,
        max=36_500,
        help="Select runs whose last update is older than this many days.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Delete the selected run metadata and associated graph checkpoints.",
    ),
    include_running: bool = typer.Option(
        False,
        "--include-running",
        help="Also select runs still marked running; verify the runtime is stopped first.",
    ),
) -> None:
    """Preview old runs; remove metadata and checkpoints only with --apply."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    store = SQLiteRunMetadataStore(database)
    try:
        records = asyncio.run(
            store.clean_before(cutoff, apply=apply, include_running=include_running)
        )
    except (RunMetadataError, ValueError, OSError) as exc:
        typer.echo(f"Could not clean runs: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "mode": "applied" if apply else "preview",
                "selected": len(records),
                "run_ids": [record.run_id for record in records],
                "next_step": None if apply or not records else "rerun with --apply to delete",
            },
            indent=2,
        )
    )


@app.command("observe")
def observe(
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
def run(
    goal: str = typer.Argument(..., help="Natural-language browser task."),
    start_url: str | None = typer.Option(None, "--start-url", help="Optional starting page URL."),
    headless: bool = typer.Option(True, help="Run Chromium headless."),
    provider: str | None = typer.Option(
        None,
        help="Optional Laya shadow comparison override; Jev is disabled.",
    ),
    checkpoint_db: str = typer.Option(
        "browski-checkpoints.sqlite",
        help="SQLite checkpoint database for this task.",
    ),
    config_path: ConfigPathOption = None,
) -> None:
    """Run a browser task through the autonomous graph."""
    if config_path is None:
        task(
            goal=goal,
            url=start_url,
            headless=headless,
            provider=provider,
            checkpoint_db=checkpoint_db,
        )
    else:
        task(
            goal=goal,
            url=start_url,
            headless=headless,
            provider=provider,
            checkpoint_db=checkpoint_db,
            config_path=config_path,
        )


@app.command()
def task(
    goal: str = typer.Argument(..., help="Natural-language browser task."),
    url: str | None = typer.Option(None, help="Optional starting page URL."),
    headless: bool = typer.Option(True, help="Run Chromium headless."),
    provider: str | None = typer.Option(
        None,
        help="Optional Laya shadow comparison override; Jev is disabled.",
    ),
    checkpoint_db: str = typer.Option(
        "browski-checkpoints.sqlite",
        help="SQLite checkpoint database for this task.",
    ),
    config_path: ConfigPathOption = None,
) -> None:
    """Run a task through Luna and the verified browser graph."""
    config = _load_runtime_config(config_path)
    selected_provider_name = _resolve_provider(provider, config)

    from browser_agent import BrowserSession
    from browser_agent.agent import AgentRuntime, LunaDecisionAgent
    from browser_agent.decisions import DecisionConfig, create_decision_provider
    from browser_agent.decisions.config import DecisionProviderName

    async def _run_task() -> None:
        decisions = None
        if selected_provider_name is not None:
            decisions = create_decision_provider(
                DecisionConfig(
                    provider=DecisionProviderName.LAYA,
                    laya_endpoint=config.decision.laya_endpoint,
                )
            )
        reasoning = _create_luna_reasoning_provider(config)
        async with BrowserSession.launch(
            headless=headless, browser_code_enabled=config.browser_code.enabled
        ) as browser:
            if url:
                await browser.navigate(url)
            agent = LunaDecisionAgent(
                decisions,
                reasoning,
                model=config.reasoning.model,
                vision_provider=_create_luna_vision_provider(config),
                screenshot_capture=browser.capture_viewport_screenshot,
                browser_code_enabled=config.browser_code.enabled,
                default_effort=config.reasoning.effort,
                site_aliases=config.site_aliases,
            )
            async with AgentRuntime.open_sqlite(
                agent,
                browser,
                database=checkpoint_db,
                # Laya is attached only to the agent's non-executing shadow
                # comparison path. It must not classify graph recovery or
                # otherwise influence run control.
                decision_provider=None,
                debug_config=config.debug,
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
def resume(
    run_id: str = typer.Argument(..., help="Checkpoint thread id printed by `agent task`."),
    url: str | None = typer.Option(
        None,
        help="Optional page to open in the resumed browser session.",
    ),
    headless: bool = typer.Option(True, help="Run Chromium headless."),
    provider: str | None = typer.Option(
        None,
        help="Optional Laya shadow comparison override; Jev is disabled.",
    ),
    checkpoint_db: str = typer.Option(
        "browski-checkpoints.sqlite",
        help="SQLite checkpoint database used by the original task.",
    ),
    approve: bool = typer.Option(False, "--approve", help="Approve a pending high-risk action."),
    deny: bool = typer.Option(False, "--deny", help="Deny a pending high-risk action."),
    config_path: ConfigPathOption = None,
) -> None:
    """Resume a SQLite-backed task in a newly launched browser session."""
    if approve and deny:
        raise typer.BadParameter("choose at most one of --approve and --deny")

    config = _load_runtime_config(config_path)
    selected_provider_name = _resolve_provider(provider, config)

    from browser_agent import BrowserSession
    from browser_agent.agent import AgentRuntime, LunaDecisionAgent
    from browser_agent.decisions import DecisionConfig, create_decision_provider
    from browser_agent.decisions.config import DecisionProviderName

    async def _resume_task() -> None:
        decisions = None
        if selected_provider_name is not None:
            decisions = create_decision_provider(
                DecisionConfig(
                    provider=DecisionProviderName.LAYA,
                    laya_endpoint=config.decision.laya_endpoint,
                )
            )
        reasoning = _create_luna_reasoning_provider(config)
        async with BrowserSession.launch(
            headless=headless, browser_code_enabled=config.browser_code.enabled
        ) as browser:
            if url:
                await browser.navigate(url)
            agent = LunaDecisionAgent(
                decisions,
                reasoning,
                model=config.reasoning.model,
                vision_provider=_create_luna_vision_provider(config),
                screenshot_capture=browser.capture_viewport_screenshot,
                browser_code_enabled=config.browser_code.enabled,
                default_effort=config.reasoning.effort,
                site_aliases=config.site_aliases,
            )
            async with AgentRuntime.open_sqlite(
                agent,
                browser,
                database=checkpoint_db,
                # Keep shadow decisions out of recovery and graph routing.
                decision_provider=None,
                debug_config=config.debug,
            ) as runtime:
                if approve or deny:
                    result = await runtime.resume_with_confirmation(run_id, approved=approve)
                else:
                    result = await runtime.resume(run_id)
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

    asyncio.run(_resume_task())


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
