"""Conservative native ownership checks for heading-bound recorded facts."""

from browser_agent._types import SemanticElement, SemanticSnapshot


def scoped_definition_snapshot(
    snapshot: SemanticSnapshot, heading: SemanticElement
) -> SemanticSnapshot:
    """Keep definitions in the selected heading's proven native section.

    Document order alone is not ownership. Require the same frame and native
    ancestry, allow only a definition-list wrapper, and stop at the next
    heading. Other cards, nested sections, missing ancestry, and custom
    widgets remain unsupported rather than supplying guessed field values.
    """
    if not heading.ancestry:
        return snapshot.model_copy(update={"elements": [], "interactive_elements": []})
    later_headings = [
        item.doc_order
        for item in snapshot.elements
        if item.role.casefold() == "heading"
        and item.frame == heading.frame
        and item.frame_path == heading.frame_path
        and item.doc_order > heading.doc_order
    ]
    end = min(later_headings) if later_headings else None
    selected: list[SemanticElement] = []
    for item in snapshot.elements:
        if (
            item.frame != heading.frame
            or item.frame_path != heading.frame_path
            or item.doc_order <= heading.doc_order
            or (end is not None and item.doc_order >= end)
            or item.ancestry[: len(heading.ancestry)] != heading.ancestry
        ):
            continue
        wrappers = item.ancestry[len(heading.ancestry) :]
        if any(wrapper.split(".", 1)[0] != "dl" for wrapper in wrappers):
            continue
        selected.append(item)
    return snapshot.model_copy(update={"elements": selected, "interactive_elements": []})
