"""M2 observation demo: full snapshot, model-facing render, incremental delta."""

import asyncio

from browser_agent import BrowserSession


async def main() -> None:
    async with BrowserSession.launch() as browser:
        await browser.navigate("https://example.com")
        snapshot = await browser.observe()
        print(f"url={snapshot.url} title={snapshot.title}")
        print(
            f"elements={len(snapshot.elements)} fingerprint={snapshot.page_fingerprint}"
        )

        tab_id = await browser.active_tab_id()
        assert tab_id is not None
        print(f"--- agent observation for {tab_id} ---")
        print(await browser.render_observation(tab_id))

        # Second observation with no changes: delta must be empty.
        await browser.observe()
        delta = await browser.observe_delta(tab_id)
        print(f"delta empty (no changes): {delta.is_empty()}")

        tabs = await browser.tabs()
        print(f"tabs: {[(t.id[:8], t.url) for t in tabs]}")


if __name__ == "__main__":
    asyncio.run(main())
