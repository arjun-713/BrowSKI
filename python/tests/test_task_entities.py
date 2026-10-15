"""Natural form literals must be grounded in task text and unique controls."""

from __future__ import annotations

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions import CandidatePolicy
from browser_agent.decisions.task_entities import candidate_policy_for_task_entities


def _observation(*elements: PrunedElement) -> AgentObservation:
    return AgentObservation(
        url="http://127.0.0.1/task-mix/form",
        title="Local form",
        state_generation=1,
        elements=list(elements),
    )


def _input(ref: str, name: str, role: str = "textbox") -> PrunedElement:
    return PrunedElement(ref=ref, role=role, name=name, interactable=True)


def _combo(ref: str, name: str) -> PrunedElement:
    return PrunedElement(ref=ref, role="combobox", name=name, interactable=True)


def _option(ref: str, label: str) -> PrunedElement:
    return PrunedElement(ref=ref, role="option", name=label, interactable=False)


def _owned_option(ref: str, label: str, parent_ref: str) -> PrunedElement:
    return PrunedElement(
        ref=ref, role="option", name=label, parent_ref=parent_ref, interactable=False
    )


def _checkbox(ref: str, label: str) -> PrunedElement:
    return PrunedElement(ref=ref, role="checkbox", name=label, interactable=True)


def test_register_phrase_extracts_name_email_and_explicit_organization() -> None:
    observation = _observation(
        _input("@attendee", "Attendee name"),
        _input("@contact", "Contact email"),
        _input("@organization", "Organization"),
    )

    policy = candidate_policy_for_task_entities(
        "Register Nia Patel at nia@example.test, organization Cedar Labs for the event.",
        observation,
    )

    assert policy.values_by_ref == {
        "@attendee": "Nia Patel",
        "@contact": "nia@example.test",
        "@organization": "Cedar Labs",
    }


def test_register_anchor_extracts_name_before_a_following_instruction() -> None:
    observation = _observation(_input("@name", "Full name"))

    policy = candidate_policy_for_task_entities(
        "Register Samira Iqbal and complete the registration.", observation
    )

    assert policy.values_by_ref == {"@name": "Samira Iqbal"}


def test_registration_for_anchor_extracts_a_unique_person_name() -> None:
    observation = _observation(_input("@name", "Contact name"))

    policy = candidate_policy_for_task_entities("Registration for Maya Chen.", observation)

    assert policy.values_by_ref == {"@name": "Maya Chen"}


def test_reservation_anchor_and_comma_adjacent_company_suffix_are_supported() -> None:
    observation = _observation(
        _input("@passenger", "Passenger name"),
        _input("@email", "Email address"),
        _input("@company", "Company name"),
    )

    policy = candidate_policy_for_task_entities(
        "Reserve a seat for Amira Khan, amira@example.test, Acme Group on October 23.",
        observation,
    )

    assert policy.values_by_ref == {
        "@passenger": "Amira Khan",
        "@email": "amira@example.test",
        "@company": "Acme Group",
    }


def test_ordinary_select_and_change_phrasing_use_only_named_unique_options() -> None:
    observation = _observation(
        _combo("@language", "Workspace language"),
        _option("@swahili", "Swahili"),
        _combo("@session", "Preferred session"),
        _option("@morning", "Morning lab"),
    )

    policy = candidate_policy_for_task_entities(
        "Change the workspace language to Swahili, then choose Morning lab in Preferred session.",
        observation,
    )

    assert policy.select_labels_by_ref == {
        "@language": ("Swahili",),
        "@session": ("Morning lab",),
    }


def test_on_day_and_from_until_time_phrases_bind_semantically_unique_controls() -> None:
    observation = _observation(
        _combo("@day", "Day"),
        _option("@tuesday", "Tuesday"),
        _combo("@start", "Starts at"),
        _option("@three", "3:00 PM"),
        _combo("@end", "Ends at"),
        _option("@four", "4:00 PM"),
    )

    policy = candidate_policy_for_task_entities(
        "Schedule the work session on Tuesday from 3:00 PM until 4:00 PM.",
        observation,
    )

    assert policy.select_labels_by_ref == {
        "@day": ("Tuesday",),
        "@start": ("3:00 PM",),
        "@end": ("4:00 PM",),
    }


def test_adjective_weekday_and_trailing_save_clause_bind_unique_day_and_interval_fields() -> None:
    observation = _observation(
        _combo("@day", "Day"),
        _option("@wednesday", "Wednesday"),
        _combo("@start", "Starts at"),
        _option("@two", "2:00 PM"),
        _combo("@end", "Ends at"),
        _option("@four", "4:00 PM"),
    )

    policy = candidate_policy_for_task_entities(
        "Create a Wednesday work session from 2:00 PM to 4:00 PM and save it.",
        observation,
    )

    assert policy.select_labels_by_ref == {
        "@day": ("Wednesday",),
        "@start": ("2:00 PM",),
        "@end": ("4:00 PM",),
    }


def test_negated_weekday_is_not_bound_as_a_requested_day() -> None:
    observation = _observation(
        _combo("@day", "Day"),
        _option("@wednesday", "Wednesday"),
        _combo("@start", "Starts at"),
        _option("@two", "2:00 PM"),
        _combo("@end", "Ends at"),
        _option("@four", "4:00 PM"),
    )

    policy = candidate_policy_for_task_entities(
        "Do not schedule a Wednesday work session from 2:00 PM to 4:00 PM.",
        observation,
    )

    assert policy.select_labels_by_ref == {}


def test_calendar_date_is_not_bound_to_a_day_field() -> None:
    observation = _observation(
        _combo("@day", "Day"),
        _option("@tuesday", "Tuesday"),
        _combo("@date", "Date"),
        _option("@october-23", "October 23"),
    )

    policy = candidate_policy_for_task_entities("Book the visit on October 23.", observation)

    assert policy.select_labels_by_ref == {"@date": ("October 23",)}


def test_duplicate_time_options_resolve_by_observed_combobox_ownership() -> None:
    observation = _observation(
        _combo("@start", "Starts at"),
        _owned_option("@start-four", "4:00 PM", "@start"),
        _combo("@end", "Ends at"),
        _owned_option("@end-four", "4:00 PM", "@end"),
    )

    policy = candidate_policy_for_task_entities(
        "Schedule the work session from 4:00 PM until 4:00 PM.", observation
    )

    assert policy.select_labels_by_ref == {
        "@start": ("4:00 PM",),
        "@end": ("4:00 PM",),
    }


def test_unique_task_named_option_can_select_the_only_relevant_combobox() -> None:
    observation = _observation(
        _combo("@session", "Preferred session"),
        _option("@morning", "Morning lab"),
        _option("@afternoon", "Afternoon studio"),
    )

    policy = candidate_policy_for_task_entities("Choose the Morning lab.", observation)

    assert policy.select_labels_by_ref == {"@session": ("Morning lab",)}


def test_unique_task_named_option_uses_its_observed_owner_without_a_field_name() -> None:
    observation = _observation(
        _combo("@session", "Preferred session"),
        _owned_option("@morning", "Morning lab", "@session"),
        _combo("@language", "Workspace language"),
        _owned_option("@swahili", "Swahili", "@language"),
    )

    policy = candidate_policy_for_task_entities("Choose Morning lab.", observation)

    assert policy.select_labels_by_ref == {"@session": ("Morning lab",)}


def test_checkbox_intents_use_unique_overlapping_labels_and_support_opt_out() -> None:
    observation = _observation(
        _checkbox("@mail", "Send me emails about future workshops"),
        _checkbox("@access", "Step-free access required"),
        _checkbox("@newsletter", "Monthly news updates"),
    )

    policy = candidate_policy_for_task_entities(
        "Include future workshop emails and step-free access, but opt out of monthly news updates.",
        observation,
    )

    assert policy.checked_by_ref == {
        "@mail": True,
        "@access": True,
        "@newsletter": False,
    }


def test_ambiguous_or_conflicting_checkbox_intents_fail_closed() -> None:
    observation = _observation(
        _checkbox("@mail-a", "Future workshop emails"),
        _checkbox("@mail-b", "Future workshop emails"),
        _checkbox("@access", "Step-free access"),
    )

    ambiguous = candidate_policy_for_task_entities("Include future workshop emails.", observation)
    conflict = candidate_policy_for_task_entities(
        "Include step-free access, then leave off step-free access.", observation
    )

    assert ambiguous.checked_by_ref == {}
    assert conflict.checked_by_ref == {}


def test_duplicate_person_or_email_controls_fail_closed_for_that_entity() -> None:
    observation = _observation(
        _input("@name-a", "Full name"),
        _input("@name-b", "Attendee name"),
        _input("@email-a", "Email address"),
        _input("@email-b", "Contact email"),
    )

    policy = candidate_policy_for_task_entities(
        "Registration for Maya Chen at maya@example.test.",
        observation,
    )

    assert policy.values_by_ref == {}


def test_missing_or_conflicting_values_do_not_create_candidates() -> None:
    observation = _observation(
        _input("@name", "Full name"),
        _input("@email", "Email address"),
        _input("@organization", "Organization"),
    )
    missing = candidate_policy_for_task_entities("Complete the registration form.", observation)
    conflicting = candidate_policy_for_task_entities(
        "Register Mia Chen at mia@example.test, then register Nina Park at nina@example.test.",
        observation,
    )
    ungrounded_company = candidate_policy_for_task_entities(
        "Register Mia Chen at mia@example.test, step-free access, October 22.",
        observation,
    )

    assert missing.values_by_ref == {}
    assert conflicting.values_by_ref == {}
    assert ungrounded_company.values_by_ref == {
        "@name": "Mia Chen",
        "@email": "mia@example.test",
    }


def test_duplicate_options_and_conflicting_select_requests_are_rejected() -> None:
    observation = _observation(
        _combo("@session", "Session"),
        _option("@morning-a", "Morning lab"),
        _option("@morning-b", "Morning lab"),
        _option("@afternoon", "Afternoon studio"),
    )
    duplicate = candidate_policy_for_task_entities("Choose Morning lab in Session.", observation)
    conflict = candidate_policy_for_task_entities(
        "Choose Morning lab in Session, then choose Afternoon studio in Session.",
        observation,
    )

    assert duplicate.select_labels_by_ref == {}
    assert conflict.select_labels_by_ref == {}


def test_page_option_text_alone_cannot_authorize_a_selection() -> None:
    observation = _observation(
        _combo("@session", "Preferred session"),
        _option("@morning", "Morning lab"),
    )

    policy = candidate_policy_for_task_entities("Complete the form.", observation)

    assert policy.select_labels_by_ref == {}


def test_existing_policy_values_and_labels_are_preserved() -> None:
    observation = _observation(
        _input("@name", "Full name"),
        _combo("@language", "Language"),
        _option("@hindi", "Hindi"),
    )
    base = CandidatePolicy(
        values_by_ref={"@name": "Approved name"},
        select_labels_by_ref={"@language": ("English",)},
    )

    policy = candidate_policy_for_task_entities(
        "Register Alex Demo and change the language to Hindi.", observation, base
    )

    assert policy.values_by_ref == {"@name": "Approved name"}
    assert policy.select_labels_by_ref == {"@language": ("English",)}
    assert base.values_by_ref == {"@name": "Approved name"}
