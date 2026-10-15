"""Button, checkbox, type, and select synthetic probe cases."""

from __future__ import annotations

from typing import Any

from benchmarks.task_mix.probe_packets import _action, _element, _make_case


def simple_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    button_specs = [
        ("Reveal outline", 'Click "Reveal outline" exactly once.', "Outline opened."),
        ("Pin board", 'Click "Pin board" exactly once.', "Board pinned."),
        ("Open notes", 'Click "Open notes" exactly once.', "Notes opened."),
        ("Archive memo", 'Click "Archive memo" exactly once.', "Memo archived."),
    ]
    for index, (label, task, result) in enumerate(button_specs, start=1):
        ref = f"@button-{index}"
        rows.append(
            _make_case(
                f"probe-button-{index:02d}",
                "button",
                task,
                [
                    _element(ref, "button", label),
                    _element(f"@other-{index}", "button", "Discard draft"),
                    _element("@status", "status", result, text=result),
                ],
                _action(
                    "ACTION_A",
                    f"Click the unique {label!r} button once.",
                    kind="click",
                    target=ref,
                ),
                [
                    _action(
                        "",
                        "Click Discard draft.",
                        kind="click",
                        target=f"@other-{index}",
                    ),
                    _action("", "Click the button twice.", kind="click", target=ref),
                ],
                command_kind="click",
                command_label=label,
            )
        )
    checkbox_specs = [
        ("Daily brief", 'Enable "Daily brief".', True),
        ("Automatic backup", 'Disable "Automatic backup".', False),
        ("Sound alerts", 'Check "Sound alerts".', True),
        ("Release notes", 'Uncheck "Release notes".', False),
    ]
    for index, (label, task, checked) in enumerate(checkbox_specs, start=1):
        ref = f"@toggle-{index}"
        opposite = not checked
        rows.append(
            _make_case(
                f"probe-check-{index:02d}",
                "checkbox",
                task,
                [
                    _element(
                        ref,
                        "checkbox",
                        label,
                        state="checked" if opposite else "unchecked",
                    ),
                    _element(
                        f"@nearby-{index}",
                        "checkbox",
                        "Product announcements",
                        state="unchecked",
                    ),
                ],
                _action(
                    "ACTION_A",
                    f"Set {label!r} to checked={checked}.",
                    kind="check",
                    target=ref,
                    parameters={"checked": checked},
                ),
                [
                    _action(
                        "",
                        f"Set Product announcements to checked={checked}.",
                        kind="check",
                        target=f"@nearby-{index}",
                        parameters={"checked": checked},
                    ),
                    _action(
                        "",
                        f"Set {label!r} to checked={opposite}.",
                        kind="check",
                        target=ref,
                        parameters={"checked": opposite},
                    ),
                ],
                command_kind="check",
                command_label=label,
                command_checked=checked,
            )
        )
    type_specs = [
        ("Notebook title", "Paper Kite", 'Fill "Notebook title" with "Paper Kite".'),
        (
            "Search phrase",
            "quiet workspace",
            'Type "quiet workspace" into "Search phrase".',
        ),
        ("Display alias", "Mina", 'Set "Display alias" to "Mina".'),
        ("Project tag", "AX-52", 'Fill "Project tag" with "AX-52".'),
    ]
    for index, (label, value, task) in enumerate(type_specs, start=1):
        ref = f"@field-{index}"
        rows.append(
            _make_case(
                f"probe-type-{index:02d}",
                "type",
                task,
                [
                    _element(ref, "textbox", label, value=""),
                    _element(
                        f"@other-field-{index}", "textbox", "Reference code", value=""
                    ),
                ],
                _action(
                    "ACTION_A",
                    f"Type {value!r} into {label!r}.",
                    kind="type",
                    target=ref,
                    parameters={"text": value, "clear": True},
                ),
                [
                    _action(
                        "",
                        f"Type {value!r} into Reference code.",
                        kind="type",
                        target=f"@other-field-{index}",
                        parameters={"text": value, "clear": True},
                    ),
                    _action(
                        "",
                        f"Type a different value into {label!r}.",
                        kind="type",
                        target=ref,
                        parameters={"text": "different value", "clear": True},
                    ),
                ],
                command_kind="type",
                command_label=label,
            )
        )
    select_specs = [
        ("Workspace language", "Swahili", 'Select "Swahili" in "Workspace language".'),
        ("Meeting time", "Evening", 'Choose "Evening" from "Meeting time".'),
        ("Map region", "North", 'Select "North" in "Map region".'),
        ("Display density", "Compact", 'Choose "Compact" from "Display density".'),
    ]
    for index, (label, value, task) in enumerate(select_specs, start=1):
        ref = f"@choice-{index}"
        options = [value, "Default", "Alternate"]
        rows.append(
            _make_case(
                f"probe-select-{index:02d}",
                "select",
                task,
                [
                    _element(ref, "combobox", label, value="Default"),
                    *[
                        _element(
                            f"@option-{index}-{option_index}",
                            "option",
                            option,
                            text=option,
                        )
                        for option_index, option in enumerate(options, start=1)
                    ],
                ],
                _action(
                    "ACTION_A",
                    f"Select the exact option {value!r} in {label!r}.",
                    kind="select",
                    target=ref,
                    parameters={"value": value, "by": "label"},
                ),
                [
                    _action(
                        "",
                        f"Select Default in {label!r}.",
                        kind="select",
                        target=ref,
                        parameters={"value": "Default", "by": "label"},
                    ),
                    _action(
                        "",
                        f"Select {value!r} in another control.",
                        kind="select",
                        target="@other-choice",
                        parameters={"value": value, "by": "label"},
                    ),
                ],
                command_kind="select",
                command_label=label,
            )
        )
    return rows
