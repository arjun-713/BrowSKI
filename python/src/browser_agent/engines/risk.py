"""Deterministic English-language risk policy for fresh browser targets.

This is a bounded heuristic, not a classifier for every site's business semantics.
Multilingual labels are out of scope. Read live properties before each action;
never retain credential or payment-field values in public diagnostics.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

RiskCategory = Literal["purchase_payment", "send_publish", "destructive", "account_security"]
Risk = tuple[RiskCategory, str]


class RiskTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = ""
    aria_label: str = ""
    value: str = ""
    title: str = ""
    role: str = ""
    tag: str = ""
    input_type: str = ""
    autocomplete: str = ""
    name: str = ""
    href: str = ""
    page_url: str = ""
    form_action: str = ""
    form_submit_labels: tuple[str, ...] = ()
    form_has_password: bool = False
    form_has_payment: bool = False

    @property
    def sensitive(self) -> bool:
        return self.input_type == "password" or self.payment_field

    @property
    def payment_field(self) -> bool:
        words = _normalize(" ".join((self.name, self.aria_label, self.title)))
        return self.autocomplete.startswith("cc-") or bool(
            re.search(
                r"\b(card number|cardnumber|cc number|credit card|debit card|cvv|cvc)\b", words
            )
        )

    @property
    def label(self) -> str:
        # Values can contain credentials even on sites using ordinary input types.
        return (self.aria_label or self.text or self.title or self.name or self.tag or "field")[
            :120
        ]


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[_\-/]+", " ", value.casefold()).split())


def _label_risk(label: str) -> Risk | None:
    label = _normalize(label)
    if re.fullmatch(r"(?:add|remove|delete|clear) (?:a |the )?(?:filter|search filter)", label):
        return None
    # Match action verbs/phrases, not incidental nouns in search/navigation labels.
    patterns: tuple[tuple[str, RiskCategory, str], ...] = (
        (
            r"^(?:place|confirm|submit|complete) (?:an? |the |my |your )?"
            r"(?:order|purchase|payment)\b"
            r"|^(?:buy|purchase|pay|checkout|check out|subscribe|donate|transfer money)\b",
            "purchase_payment",
            "Placing an order or payment",
        ),
        (
            r"^(?:send|post|publish|reply|tweet|share|"
            r"submit (?:a |the )?(?:message|comment|review))\b",
            "send_publish",
            "Sending or publishing content",
        ),
        (
            r"^(?:delete|remove|erase|destroy|wipe|discard|empty (?:the )?trash|"
            r"cancel (?:my |the )?(?:order|subscription|account))\b",
            "destructive",
            "Deleting or making a destructive change",
        ),
        (
            r"^(?:(?:change|update|reset|save|set|disable|enable|revoke|grant|manage) "
            r"(?:my |your |the )?(?:password|security|permissions?|two factor|2fa|mfa|"
            r"recovery|email|account|profile)|"
            r"(?:create|close|deactivate) (?:an? |my |the )?account|"
            r"sign up|register|log out|sign out)\b",
            "account_security",
            "Changing account or security settings",
        ),
    )
    for pattern, category, reason in patterns:
        if re.search(pattern, label):
            return category, reason
    return None


def classify_risk(action: str, target: RiskTarget, *, keys: str = "") -> Risk | None:
    """Classify an action using live target/form context, without inspecting input text."""
    if action in {"input", "select_dropdown", "send_keys"}:
        if target.input_type == "password":
            return "account_security", "Entering a password"
        if target.payment_field:
            return "purchase_payment", "Entering payment-card details"
    if action == "send_keys" and not re.search(r"\b(?:enter|return)\b", keys, re.I):
        return None
    if action not in {"click", "send_keys", "select_dropdown"}:
        return None

    is_link = target.tag == "a" or target.role == "link"
    labels = (target.text, target.aria_label, target.title)
    if target.tag in {"button", "input"}:
        labels += (target.value,)
    for label in labels:
        if risk := _label_risk(label):
            return risk
    # Sign in links only navigate. Actual login by password entry is gated above.
    if is_link:
        return None
    submits = action == "send_keys" or target.input_type == "submit"
    if not submits:
        return None
    for label in target.form_submit_labels:
        if risk := _label_risk(label):
            return risk
    if target.form_has_payment:
        return "purchase_payment", "Submitting a payment form"
    if target.form_has_password:
        return "account_security", "Submitting an account or security form"
    # Generic Continue/Submit controls can hide their purpose in a form endpoint.
    if not target.form_action:
        return None
    endpoint = urlsplit(target.form_action)
    path = endpoint.path
    if re.search(r"/(?:checkout|payment|purchase|place[-_]order)(?:/|$)", path, re.I):
        return "purchase_payment", "Submitting an order or payment form"
    if re.search(r"/(?:delete|destroy|deactivate)(?:/|$)", path, re.I):
        return "destructive", "Submitting a destructive change"
    if re.search(r"/(?:password|security|register)(?:/|$)", path, re.I):
        return "account_security", "Submitting an account or security change"
    return None


# Fixed inspection only. Sensitive values never cross this browser boundary.
RISK_TARGET_SCRIPT = """() => {
    const e = this;
    const form = e.form || e.closest('form');
    const field = e.type === 'password' || (e.autocomplete || '').startsWith('cc-') ||
        /card.?number|cvv|cvc/i.test([e.name, e.id, e.getAttribute('aria-label')].join(' '));
    const trim = x => String(x || '').slice(0, 500);
    return JSON.stringify({
        text: trim(e.innerText || e.textContent), aria_label: trim(e.getAttribute('aria-label') ||
            Array.from(e.labels || []).map(l => l.innerText).join(' ')),
        value: field ? '' : trim(e.value), title: trim(e.title),
        role: trim(e.getAttribute('role')), tag: e.tagName.toLowerCase(),
        input_type: trim(e.type), autocomplete: trim(e.autocomplete), name: trim(e.name || e.id),
        href: trim(e.href), page_url: e.ownerDocument.location.href,
        form_action: form ? form.action : '',
        form_submit_labels: form ? Array.from(form.querySelectorAll(
            'button:not([type]),button[type=submit],input[type=submit]'
        )).slice(0, 30).map(b => trim(b.innerText || b.getAttribute('aria-label') || b.value)) : [],
        form_has_password: !!form && !!form.querySelector('input[type=password]'),
        form_has_payment: !!form && !!form.querySelector(
            '[autocomplete^="cc-"],input[name*="card" i],input[name*="cvv" i],input[name*="cvc" i]'
        )
    });
}"""
