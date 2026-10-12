"""Resolve user-named websites through trusted local configuration, not page text."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from browser_agent.decisions.task_tabs import explicit_task_destinations

DEFAULT_SITE_ALIASES: dict[str, str] = {
    "amazon": "https://www.amazon.in/",
    "flipkart": "https://www.flipkart.com/",
    "apple": "https://www.apple.com/in/shop/",
}


def validate_site_aliases(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("site aliases must be a table containing at most 16 websites")
    entries = cast(dict[object, object], value)
    if len(entries) > 16:
        raise ValueError("site aliases must be a table containing at most 16 websites")
    aliases: dict[str, str] = {}
    for name, url in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", name):
            raise ValueError("site aliases must use short lowercase names")
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError("site alias destinations must be bounded HTTP(S) URLs")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as error:
            raise ValueError("invalid site destination") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or port == 0
            or any(character.isspace() or ord(character) < 32 for character in url)
        ):
            raise ValueError("site destinations cannot contain credentials, queries or fragments")
        aliases[name] = url
    return aliases


def requested_sites(task: str, aliases: Mapping[str, str]) -> dict[str, str]:
    if len(task) > 8000:
        return {}
    # A brand in form data is not a request to open that company's website.
    intent = re.search(r"\b(?:open|visit|browse|compare|shopping|shop|buy|purchase)\b", task, re.I)
    if intent is None:
        return {}
    named = {
        name: url
        for name, url in aliases.items()
        if re.search(rf"\b{re.escape(name)}\b", task, re.I) and not _excluded_site(task, name)
    }
    if re.search(r"\b(?:all|multiple|several)\s+shopping\s+(?:websites|sites)\b", task, re.I):
        defaults = {
            name: url
            for name, url in aliases.items()
            if name in DEFAULT_SITE_ALIASES and not _excluded_site(task, name)
        }
        return defaults | named
    return named


def _excluded_site(task: str, name: str) -> bool:
    negative = r"(?:do\s+not|don't|never|avoid|except|excluding|without|not)"
    # Conservatively refuse a named destination following a negative clause,
    # including lists such as "do not open Apple or Amazon".
    return bool(re.search(rf"\b{negative}\b[^.;\n]{{0,160}}\b{re.escape(name)}\b", task, re.I))


def destination_task(task: str, sites: Mapping[str, str]) -> str:
    return task + "\n" + "\n".join(f'Open "{url}" in a new tab.' for url in sites.values())


def task_tab_labels(
    task: str, sites: Mapping[str, str], tab_urls: Mapping[str, str]
) -> dict[str, str]:
    """Return task aliases only: never export unrelated URLs or tab titles."""
    labels: dict[str, str] = {}
    for tab_id, url in tab_urls.items():
        normalized_url = normalize_task_url(url)
        for alias, destination in sites.items():
            if normalized_url and normalized_url == normalize_task_url(destination):
                labels[tab_id] = alias
                break
        # Explicit URLs were already supplied by the user to the provider.
        if tab_id not in labels:
            for index, destination in enumerate(explicit_task_destinations(task), start=1):
                if normalized_url and normalized_url == normalize_task_url(destination):
                    labels[tab_id] = f"task destination {index}"
                    break
    return labels


def normalize_task_url(url: str) -> str:
    """Normalize only URL authority and trailing slash for exact URL evidence."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    host = hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    default_port = 80 if scheme == "http" else 443
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))
