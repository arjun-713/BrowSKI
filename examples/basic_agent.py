"""Minimal vertical-slice example: navigate + observe through the Rust core."""

import asyncio

from browser_agent import BrowserSession


async def main() -> None:
    async with BrowserSession.launch() as browser:
        await browser.navigate("https://example.com")
        snapshot = await browser.observe()
        print(snapshot.title)


if __name__ == "__main__":
    asyncio.run(main())
