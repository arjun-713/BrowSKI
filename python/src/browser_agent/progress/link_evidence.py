"""Runtime checks for source-bound links opened into currently owned tabs."""

from browser_agent._types import SemanticSnapshot, TaskState


def required_link_open_checks(task: TaskState, snapshot: SemanticSnapshot) -> dict[str, bool]:
    """Expose true/false checks without treating a click alone as a new tab."""
    checks: dict[str, bool] = {}
    for ref in task.required_link_refs:
        checks[f"required_link_open:{ref}"] = any(
            proof.source_tab_id == task.required_link_source_tab_id
            and proof.source_ref == ref
            and proof.source_generation == task.required_link_source_generation
            and proof.source_page_fingerprint == task.required_link_source_fingerprint
            and proof.opened_tab_id in snapshot.tabs
            for proof in task.verified_link_opens
        )
    return checks
