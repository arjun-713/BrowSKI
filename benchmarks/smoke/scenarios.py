"""Synthetic local browser tasks used by the live Luna smoke runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SmokeCase:
    name: str
    start_path: str
    prompt: str
    expected_visible_text: str
    max_steps: int
    max_llm_calls: int
    max_seconds: int
    minimum_tabs: int = 1
    expected_element_values: tuple[tuple[str, str], ...] = ()
    expected_tab_urls: tuple[str, ...] = ()


def cases(base_url: str) -> tuple[SmokeCase, ...]:
    """Return small, medium, and long fixture tasks with isolated evidence."""
    studio_14 = f"{base_url}/product/studio-14"
    studio_16 = f"{base_url}/product/studio-16"
    travel_13 = f"{base_url}/product/travel-13"
    shortlist = f"{base_url}/shortlist"
    return (
        SmokeCase(
            name="short-picker",
            start_path="/short",
            prompt=(
                'Select "Pune" in "Service region", then click '
                '"Confirm region". Finish when visible text contains '
                '"Service region: Pune".'
            ),
            expected_visible_text="Service region: Pune",
            max_steps=8,
            max_llm_calls=8,
            max_seconds=120,
            expected_element_values=(
                # SemanticSnapshot.value is the AX selected label. The HTML
                # option's machine value "pune" is a different representation.
                ("@service_region", "Pune"),
                ("@status", "Service region: Pune"),
            ),
        ),
        SmokeCase(
            name="medium-preferences",
            start_path="/registration",
            prompt=(
                'Set "Full name" to "Ada Lovelace" and fill "Email address" with '
                '"ada@example.test". Click "Continue to preferences", '
                'Select "Morning lab" in "Preferred session", and check '
                '"Send me workshop updates". Click "Save preferences". '
                "Finish when visible text contains "
                '"Registration saved for Ada Lovelace (ada@example.test); '
                'Morning lab; updates: yes."'
            ),
            expected_visible_text=(
                "Registration saved for Ada Lovelace (ada@example.test); "
                "Morning lab; updates: yes."
            ),
            max_steps=16,
            max_llm_calls=18,
            max_seconds=120,
            expected_element_values=(("@status", expected_medium_status()),),
        ),
        SmokeCase(
            name="long-shopping-tabs",
            start_path="/shop",
            prompt=(
                f'Open the exact pages "{studio_14}", "{studio_16}", and '
                f'"{travel_13}" in separate browser tabs. Compare their visible '
                "Memory and Storage labels. The requested specifications are "
                '"Memory: 16 GB" and "Storage: 512 GB". On the matching page, '
                'click "Add this laptop to shortlist". Then open the exact page '
                f'"{shortlist}" in a new tab and finish when visible text contains '
                '"Shortlisted laptop: Northstar Studio 14". Do not purchase.'
            ),
            expected_visible_text="Shortlisted laptop: Northstar Studio 14",
            max_steps=20,
            max_llm_calls=20,
            max_seconds=120,
            minimum_tabs=5,
            expected_element_values=(
                ("@status", "Shortlisted laptop: Northstar Studio 14"),
            ),
            expected_tab_urls=(
                f"{base_url}/shop",
                studio_14,
                studio_16,
                travel_13,
                shortlist,
            ),
        ),
    )


def expected_medium_status() -> str:
    return (
        "Registration saved for Ada Lovelace (ada@example.test); "
        "Morning lab; updates: yes."
    )
