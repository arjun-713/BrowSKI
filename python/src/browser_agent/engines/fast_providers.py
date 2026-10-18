"""Local CPU Laya and optional hosted Jev adapters for one Fast request contract."""

from __future__ import annotations

import asyncio
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from browser_agent.engines.fast_contract import FastDecision, FastRequest, normalize_response
from browser_agent.engines.laya_worker import start_worker


class LayaFastProvider:
    name = "laya"
    model = "cklxx/laya-browser@645cf366:v19s"

    def __init__(self, checkpoint: Path, *, timeout_seconds: float = 60, threads: int = 4) -> None:
        if timeout_seconds <= 0 or not 1 <= threads <= 8:
            raise ValueError("Laya requires a positive timeout and 1–8 CPU threads.")
        self.checkpoint = checkpoint
        self.timeout_seconds = timeout_seconds
        self.threads = threads
        self.load_ms: float | None = None
        self.peak_rss_mib: float | None = None
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._lock = asyncio.Lock()

    async def _receive(self) -> dict[str, Any]:
        assert self._connection is not None and self._process is not None
        async with asyncio.timeout(self.timeout_seconds):
            while not self._connection.poll():
                if not self._process.is_alive():
                    raise RuntimeError("Laya inference process exited.")
                await asyncio.sleep(0.02)
            value = self._connection.recv()
        if not isinstance(value, dict) or "error" in value:
            raise RuntimeError("Laya inference failed; no browser action authorized.")
        return cast(dict[str, Any], value)

    async def predict(self, request: FastRequest) -> FastDecision:
        async with self._lock:
            try:
                if self._process is None:
                    self._process, self._connection = start_worker(self.checkpoint, self.threads)
                    ready = await self._receive()
                    if ready.get("ready") is not True:
                        raise RuntimeError("Laya did not become ready.")
                    self.load_ms = float(ready["load_ms"])
                assert self._connection is not None
                self._connection.send(request.body("laya-browser"))
                reply = await self._receive()
                self.peak_rss_mib = reply.get("peak_rss_mib")
                return normalize_response(
                    request,
                    reply["response"],
                    provider=self.name,
                    model=self.model,
                    latency_ms=float(reply["latency_ms"]),
                )
            except BaseException:
                # Timeout/cancellation must terminate inference rather than leave a
                # background to_thread call consuming CPU or sending a stale response.
                await self.aclose()
                raise

    async def aclose(self) -> None:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        if connection is not None:
            try:
                connection.send(None)
            except (EOFError, BrokenPipeError, OSError):
                pass  # Worker already exited; join below still reaps it.
            connection.close()
        if process is not None:
            await asyncio.to_thread(process.join, 1)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 5)
            process.close()


class JevFastProvider:
    name = "jev"

    def __init__(
        self,
        *,
        api_key: str | None,
        allow_paid_api: bool = False,
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        model: str = "jev-latest",
        timeout_seconds: float = 20,
        transport: Any = None,
    ) -> None:
        if not allow_paid_api:
            raise ValueError(
                "Jev is hosted: explicitly enable paid API access or select local Laya."
            )
        if not api_key:
            raise ValueError("Jev credentials are missing; select local Laya instead.")
        try:
            parsed = urlsplit(endpoint)
        except ValueError as error:
            raise ValueError("Jev endpoint is not a valid HTTPS URL.") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Jev requires an HTTPS endpoint without credentials, query or fragment."
            )
        if timeout_seconds <= 0:
            raise ValueError("Jev timeout must be positive.")
        self.model = model
        self.endpoint = endpoint
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._client: Any = None

    async def predict(self, request: FastRequest) -> FastDecision:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            )
        started = time.perf_counter()
        try:
            body = request.body(self.model)
            # Jev scores use an array; Laya uses numeric-keyed criteria. The
            # ordered rubric is identical, but the raw API formats differ.
            body["questions"] = {
                name: {**q.model_dump(), "criteria": list(q.criteria.values())}
                if q.type == "score"
                else q.model_dump()
                for name, q in request.questions.items()
            }
            async with asyncio.timeout(self.timeout_seconds):
                response = await self._client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Jev returned HTTP {response.status_code}; no action authorized."
                )
            raw = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError("Jev request failed; no browser action authorized.") from exc
        return normalize_response(
            request,
            raw,
            provider=self.name,
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
