"""English risk heuristics: consequential actions and ordinary navigation negatives."""

from __future__ import annotations

import pytest

from browser_agent.engines.risk import RiskTarget, classify_risk


@pytest.mark.parametrize(
    "label,category",
    [
        ("Place order", "purchase_payment"),
        ("Place my order", "purchase_payment"),
        ("Confirm payment", "purchase_payment"),
        ("Submit purchase", "purchase_payment"),
        ("Buy now", "purchase_payment"),
        ("Pay $10", "purchase_payment"),
        ("Checkout", "purchase_payment"),
        ("Check out", "purchase_payment"),
        ("Donate", "purchase_payment"),
        ("Subscribe", "purchase_payment"),
        ("Transfer money", "purchase_payment"),
        ("Send", "send_publish"),
        ("Send message", "send_publish"),
        ("Post comment", "send_publish"),
        ("Publish", "send_publish"),
        ("Reply", "send_publish"),
        ("Submit review", "send_publish"),
        ("Share", "send_publish"),
        ("Delete account", "destructive"),
        ("Remove member", "destructive"),
        ("Erase all data", "destructive"),
        ("Discard changes", "destructive"),
        ("Empty trash", "destructive"),
        ("Cancel subscription", "destructive"),
        ("Change password", "account_security"),
        ("Reset password", "account_security"),
        ("Update email", "account_security"),
        ("Enable 2FA", "account_security"),
        ("Revoke permissions", "account_security"),
        ("Create account", "account_security"),
        ("Sign up", "account_security"),
        ("Register", "account_security"),
        ("Sign out", "account_security"),
    ],
)
def test_consequential_button_labels(label: str, category: str) -> None:
    risk = classify_risk("click", RiskTarget(text=label, tag="button"))
    assert risk is not None and risk[0] == category
    assert 0 < len(risk[1]) <= 300


@pytest.mark.parametrize(
    "label",
    [
        "Search",
        "Next",
        "Previous",
        "Add filter",
        "Remove filter",
        "Delete filter",
        "Clear filter",
        "Sign in",
        "Log in",
        "Login",
        "Learn about payments",
        "Order history",
        "Payment options",
        "Publication date",
        "Alan Turing",
        "Open article",
        "Read more",
        "Shopping cart",
        "Security documentation",
    ],
)
def test_navigation_negatives(label: str) -> None:
    assert classify_risk("click", RiskTarget(text=label, tag="a", role="link")) is None


@pytest.mark.parametrize(
    "action,target,keys,category",
    [
        ("input", RiskTarget(input_type="password"), "", "account_security"),
        ("input", RiskTarget(input_type="text", autocomplete="cc-number"), "", "purchase_payment"),
        ("input", RiskTarget(input_type="tel", name="card-number"), "", "purchase_payment"),
        ("input", RiskTarget(aria_label="Credit card"), "", "purchase_payment"),
        ("input", RiskTarget(name="cvv"), "", "purchase_payment"),
        ("input", RiskTarget(autocomplete="cc-exp"), "", "purchase_payment"),
        ("input", RiskTarget(autocomplete="cc-csc"), "", "purchase_payment"),
        ("send_keys", RiskTarget(form_submit_labels=("Place order",)), "Enter", "purchase_payment"),
        ("send_keys", RiskTarget(form_submit_labels=("Send message",)), "Return", "send_publish"),
        ("send_keys", RiskTarget(form_submit_labels=("Delete",)), "Enter", "destructive"),
        ("send_keys", RiskTarget(form_has_password=True), "Enter", "account_security"),
        ("send_keys", RiskTarget(form_has_payment=True), "Control+Enter", "purchase_payment"),
        (
            "click",
            RiskTarget(input_type="submit", form_action="https://shop.test/checkout"),
            "",
            "purchase_payment",
        ),
        (
            "click",
            RiskTarget(input_type="submit", form_action="https://site.test/delete/42"),
            "",
            "destructive",
        ),
        (
            "click",
            RiskTarget(input_type="submit", form_action="https://site.test/security"),
            "",
            "account_security",
        ),
        ("click", RiskTarget(aria_label="Publish", text="Go"), "", "send_publish"),
        ("click", RiskTarget(title="Place order"), "", "purchase_payment"),
        ("click", RiskTarget(tag="input", value="Pay now"), "", "purchase_payment"),
        ("select_dropdown", RiskTarget(autocomplete="cc-exp-month"), "", "purchase_payment"),
    ],
)
def test_fresh_context(action: str, target: RiskTarget, keys: str, category: str) -> None:
    risk = classify_risk(action, target, keys=keys)
    assert risk is not None and risk[0] == category


@pytest.mark.parametrize(
    "action,target,keys",
    [
        ("input", RiskTarget(aria_label="Search", form_submit_labels=("Send",)), ""),
        ("input", RiskTarget(aria_label="Email", form_has_password=True), ""),
        ("send_keys", RiskTarget(form_submit_labels=("Search",)), "Enter"),
        ("send_keys", RiskTarget(form_submit_labels=("Delete",)), "Tab"),
        ("click", RiskTarget(text="Sign in", tag="a", href="https://site.test/login"), ""),
        (
            "click",
            RiskTarget(
                text="Next", tag="button", input_type="button", page_url="https://shop.test/cart"
            ),
            "",
        ),
        ("select_dropdown", RiskTarget(aria_label="Country"), ""),
        (
            "click",
            RiskTarget(
                text="Search", input_type="submit", form_action="https://search.test/search"
            ),
            "",
        ),
    ],
)
def test_context_negatives(action: str, target: RiskTarget, keys: str) -> None:
    assert classify_risk(action, target, keys=keys) is None
