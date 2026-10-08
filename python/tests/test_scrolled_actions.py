"""Real managed-browser regression for viewport coordinates after scrolling."""

from pathlib import Path

import pytest

from browser_agent import BrowserAction, BrowserSession, ElementRef


@pytest.mark.asyncio
async def test_scrolled_button_is_interactable_and_verified(tmp_path: Path) -> None:
    page = tmp_path / "scrolled-button.html"
    page.write_text(
        "<html><head><title>Before click</title></head><body>"
        "<div style='height:1600px'>Scroll past this spacer</div>"
        "<button onclick=\"document.title='After click';"
        "this.textContent='Local step finished'\">Finish local step</button>"
        "<div style='height:300px'></div></body></html>"
    )
    async with BrowserSession(headless=True) as browser:
        await browser.navigate(page.as_uri())
        scroll_outcome = await browser.act(BrowserAction(type="scroll", dy=1450))
        assert scroll_outcome["verification"]["status"] == "SUCCESS"
        snapshot = await browser.observe()
        button = next(
            element
            for element in snapshot.elements
            if element.accessible_name == "Finish local step"
        )
        assert snapshot.scroll["y"] > 0
        if not button.interactable:
            raise AssertionError(
                {
                    "element": button.model_dump(),
                    "scroll": snapshot.scroll,
                    "viewport": snapshot.viewport,
                }
            )
        target = ElementRef(id=button.id, ref=button.ref, generation=button.generation)
        outcome = await browser.act(BrowserAction(type="click", target=target))
        assert outcome["verification"]["status"] == "SUCCESS", outcome
        assert (await browser.observe()).title == "After click"
