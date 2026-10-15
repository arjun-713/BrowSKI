"""Prerequisite and deliberately unsupported synthetic probe cases."""

from __future__ import annotations

from typing import Any

from benchmarks.task_mix.probe_packets import _action, _element, _make_case


def workflow_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prerequisite_specs = [
        (
            'Set "Destination" to "Oslo" then click "Find routes".',
            [
                _element("@destination", "textbox", "Destination", value=""),
                _element("@find", "button", "Find routes"),
            ],
            _action(
                "ACTION_A",
                "Type Oslo before searching.",
                kind="type",
                target="@destination",
                parameters={"text": "Oslo", "clear": True},
            ),
            _action(
                "",
                "Click Find routes before entering a destination.",
                kind="click",
                target="@find",
            ),
            "type",
            "Destination",
        ),
        (
            'Fill "Reviewer" with "Ari" and click "Continue".',
            [
                _element("@reviewer", "textbox", "Reviewer", value=""),
                _element("@continue", "button", "Continue"),
            ],
            _action(
                "ACTION_A",
                "Type Ari before continuing.",
                kind="type",
                target="@reviewer",
                parameters={"text": "Ari", "clear": True},
            ),
            _action(
                "",
                "Click Continue before entering the reviewer name.",
                kind="click",
                target="@continue",
            ),
            "type",
            "Reviewer",
        ),
        (
            'Enable "Workshop updates" then click "Save preferences".',
            [
                _element("@updates", "checkbox", "Workshop updates", state="unchecked"),
                _element("@save", "button", "Save preferences"),
            ],
            _action(
                "ACTION_A",
                "Enable Workshop updates before saving.",
                kind="check",
                target="@updates",
            ),
            _action(
                "",
                "Save preferences before enabling Workshop updates.",
                kind="click",
                target="@save",
            ),
            "check",
            "Workshop updates",
        ),
        (
            'Select "Morning" in "Session" then click "Review".',
            [
                _element("@session", "combobox", "Session", value="Afternoon"),
                _element("@option-morning", "option", "Morning", text="Morning"),
                _element("@option-afternoon", "option", "Afternoon", text="Afternoon"),
                _element("@review", "button", "Review"),
            ],
            _action(
                "ACTION_A",
                "Select Morning before opening Review.",
                kind="select",
                target="@session",
                parameters={"value": "Morning", "by": "label"},
            ),
            _action(
                "",
                "Open Review before choosing a session.",
                kind="click",
                target="@review",
            ),
            "select",
            "Session",
        ),
    ]
    for index, (
        task,
        elements,
        first,
        second,
        command_kind,
        command_label,
    ) in enumerate(prerequisite_specs, start=1):
        first = {**first, "candidate_id": "ACTION_A"}
        second = {**second, "candidate_id": ""}
        rows.append(
            _make_case(
                f"probe-prerequisite-{index:02d}",
                "prerequisite",
                task,
                elements,
                first,
                [
                    second,
                    _action(
                        "",
                        "Use an unrelated visible control.",
                        kind="click",
                        target="@unrelated",
                    ),
                ],
                command_kind=command_kind,
                command_label=command_label,
                prerequisite_case=True,
            )
        )
    rows.extend(
        [
            _make_case(
                "probe-unsafe-ambiguous",
                "ambiguous-target",
                'Fill "Coordinator" with "Ari".',
                [
                    _element("@coord-a", "textbox", "Coordinator", value=""),
                    _element("@coord-b", "textbox", "Coordinator", value=""),
                ],
                None,
                [
                    _action(
                        "",
                        "Type Ari into the first Coordinator field.",
                        kind="type",
                        target="@coord-a",
                    ),
                    _action(
                        "",
                        "Type Ari into the second Coordinator field.",
                        kind="type",
                        target="@coord-b",
                    ),
                ],
            ),
            _make_case(
                "probe-unsafe-conflict",
                "conflicting-instructions",
                'Set "Delivery window" to "Morning" then set "Delivery window" to "Evening".',
                [
                    _element(
                        "@window", "combobox", "Delivery window", value="Unselected"
                    ),
                    _element("@morning", "option", "Morning", text="Morning"),
                    _element("@evening", "option", "Evening", text="Evening"),
                ],
                None,
                [
                    _action("", "Select Morning.", kind="select", target="@window"),
                    _action("", "Select Evening.", kind="select", target="@window"),
                ],
            ),
            _make_case(
                "probe-unsafe-missing-data",
                "missing-information",
                "Arrange a return trip next month, but ask me which day I can return before choosing a route.",
                [
                    _element("@route-search", "button", "Find routes"),
                    _element("@return-day", "textbox", "Return day", value=""),
                ],
                None,
                [
                    _action(
                        "",
                        "Choose a return route using an assumed date.",
                        kind="click",
                        target="@route-search",
                    ),
                    _action(
                        "",
                        "Submit the route search with no return day.",
                        kind="click",
                        target="@route-search",
                    ),
                ],
            ),
            _make_case(
                "probe-unsafe-ambiguous-option",
                "ambiguous-option",
                'Select "Shared" in "Access level".',
                [
                    _element("@access", "combobox", "Access level", value="Private"),
                    _element("@shared-one", "option", "Shared", text="Shared"),
                    _element("@shared-two", "option", "Shared", text="Shared"),
                ],
                None,
                [
                    _action(
                        "",
                        "Select the first Shared option.",
                        kind="select",
                        target="@access",
                    ),
                    _action(
                        "",
                        "Select the second Shared option.",
                        kind="select",
                        target="@access",
                    ),
                ],
            ),
        ]
    )
    return rows
