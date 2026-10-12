"""Natural search topics bind only to unique task-authorized search fields."""

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions.task_search import (
    extract_task_search_query,
    task_search_values_by_ref,
)


def _observation(*elements: PrunedElement) -> AgentObservation:
    return AgentObservation(
        url="https://shop.example/search",
        title="Shop search",
        state_generation=5,
        elements=list(elements),
    )


def test_extracts_user_search_topic_and_preserves_configuration_terms() -> None:
    query = extract_task_search_query(
        "Buy a 16GB 512GB laptop on Amazon, then compare battery life"
    )

    assert query == "a 16GB 512GB laptop"


def test_search_topic_binds_to_unique_observed_searchbox_or_labeled_textbox() -> None:
    searchbox = PrunedElement(
        ref="@search",
        role="searchbox",
        name="Search Amazon",
        interactable=True,
    )
    policy = task_search_values_by_ref(
        "Search for 16GB 512GB laptop on Amazon",
        _observation(searchbox),
    )

    assert policy == {"@search": "16GB 512GB laptop"}


def test_textbox_named_keywords_is_a_search_control() -> None:
    policy = task_search_values_by_ref(
        "Find noise cancelling headphones from the catalog",
        _observation(
            PrunedElement(
                ref="@keywords",
                role="textbox",
                name="Keywords",
                interactable=True,
            )
        ),
    )

    assert policy == {"@keywords": "noise cancelling headphones"}


def test_textbox_named_search_amazon_is_a_search_control() -> None:
    policy = task_search_values_by_ref(
        "Find quiet desk fans on the store",
        _observation(
            PrunedElement(
                ref="@search-amazon",
                role="textbox",
                name="SearchAmazon",
                interactable=True,
            )
        ),
    )

    assert policy == {"@search-amazon": "quiet desk fans"}


def test_ambiguous_or_credential_fields_do_not_receive_search_topics() -> None:
    ambiguous = task_search_values_by_ref(
        "Find laptop stands",
        _observation(
            PrunedElement(
                ref="@nav-search",
                role="searchbox",
                name="Search products",
                interactable=True,
            ),
            PrunedElement(
                ref="@page-search",
                role="textbox",
                name="Search products",
                interactable=True,
            ),
        ),
    )
    credentials = task_search_values_by_ref(
        "Buy laptop stands",
        _observation(
            PrunedElement(
                ref="@email",
                role="searchbox",
                name="Email address",
                interactable=True,
            ),
            PrunedElement(
                ref="@password",
                role="textbox",
                name="Search password",
                interactable=True,
            ),
        ),
    )

    assert ambiguous == {}
    assert credentials == {}


def test_non_search_task_and_inert_controls_do_not_create_bindings() -> None:
    controls = _observation(
        PrunedElement(
            ref="@search",
            role="searchbox",
            name="Search",
            interactable=False,
        )
    )

    assert task_search_values_by_ref("Complete the account form", controls) == {}
    assert task_search_values_by_ref("Buy a compact camera", controls) == {}


def test_search_intent_must_be_unambiguous_and_query_bounded() -> None:
    assert extract_task_search_query("Find chairs and buy a table") is None
    assert extract_task_search_query("Find " + "x " * 130) is None
