"""Trusted local site mappings provide destinations, never browser-page policy."""

import tomllib
from pathlib import Path

import pytest

from browser_agent.cli.config import ConfigError, parse_config
from browser_agent.decisions.task_sites import (
    DEFAULT_SITE_ALIASES,
    destination_task,
    requested_sites,
    task_tab_labels,
    validate_site_aliases,
)
from browser_agent.decisions.task_tabs import explicit_task_destinations


def test_user_requested_shopping_sites_use_trusted_configured_destinations() -> None:
    sites = requested_sites(
        "I want to buy a MacBook. Open all shopping websites with 16GB and 512GB.",
        DEFAULT_SITE_ALIASES,
    )
    assert sites == DEFAULT_SITE_ALIASES
    assert explicit_task_destinations(destination_task("Shop for my laptop.", sites)) == list(
        sites.values()
    )


def test_brand_form_data_is_not_a_navigation_request() -> None:
    assert requested_sites('Type "Apple" into "Brand".', DEFAULT_SITE_ALIASES) == {}


def test_excluded_sites_do_not_receive_new_tab_candidates() -> None:
    sites = requested_sites("Open all shopping websites except Apple.", DEFAULT_SITE_ALIASES)
    assert set(sites) == {"amazon", "flipkart"}
    assert requested_sites("Do not open Apple or Amazon.", DEFAULT_SITE_ALIASES) == {}


def test_provider_tab_labels_never_export_unrequested_destinations() -> None:
    labels = task_tab_labels(
        'Open "https://demo.example/product" in a new tab.',
        {},
        {
            "requested-tab": "https://demo.example/product",
            "unrelated-tab": "https://private.example/account?secret=do-not-export",
        },
    )
    assert labels == {"requested-tab": "task destination 1"}
    assert "private.example" not in str(labels)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@example.com/",
        "https://example.com/?credential=private",
        "https://example.com/#credential",
        "https://example.com:0/",
        "https://example.com/\n",
    ],
)
def test_site_mapping_rejects_unsafe_or_private_destinations(url: str) -> None:
    with pytest.raises(ValueError):
        validate_site_aliases({"shop": url})


def test_navigation_configuration_is_optional_and_strict() -> None:
    path = Path(__file__).parents[1] / "src/browser_agent/cli/default.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parse_config(document).site_aliases == DEFAULT_SITE_ALIASES
    document.pop("navigation")
    assert parse_config(document).site_aliases == DEFAULT_SITE_ALIASES
    document["navigation"] = {"site_aliases": {"store": "https://store.example/"}}
    assert parse_config(document).site_aliases == {"store": "https://store.example/"}
    document["navigation"] = {"site_aliases": {"store": "https://secret@example.com/"}}
    with pytest.raises(ConfigError):
        parse_config(document)
