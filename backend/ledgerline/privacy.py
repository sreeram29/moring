"""What may leave Meridian's systems (AP_POLICY section 5).

Vendor bank account numbers must not reach an external LLM provider. The model is not needed to read
them: code pulls bank details out of the original document, and the text sent to the provider has
every account number masked down to its last four digits. A final guard refuses to send any prompt
that still contains a known account number.
"""
from __future__ import annotations

import re

ACCOUNT_RE = re.compile(
    r"(?:a\s*/\s*c|acc(?:ount|t|\.)?|accdet)\s*(?:no\.?|number|#)?\W{0,12}?((?:\d[ -]?){8,17}\d)", re.IGNORECASE)
IFSC_RE = re.compile(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b")
MIN_SECRET_DIGITS = 9


class PrivacyError(Exception):
    """A prompt still contained a bank account number; it was not sent."""


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def bank_details(text: str) -> tuple[list[str], list[str]]:
    """All account numbers (digits only) and IFSC codes printed in the document, in order, de-duplicated."""
    accounts = list(dict.fromkeys(_digits(m.group(1)) for m in ACCOUNT_RE.finditer(text)))
    ifscs = list(dict.fromkeys(m.group(0).upper() for m in IFSC_RE.finditer(text)))
    return accounts, ifscs


def mask_account(number: str) -> str:
    digits = _digits(number)
    return "X" * max(len(digits) - 4, 0) + digits[-4:]


def mask_document(text: str) -> str:
    """The document as the provider may see it: account numbers reduced to their last four digits."""
    def repl(m: re.Match) -> str:
        whole, group = m.group(0), m.group(1)
        return whole[: len(whole) - len(group)] + mask_account(group)

    return ACCOUNT_RE.sub(repl, text)


def assert_clean(prompt: str, secrets: list[str | None]) -> None:
    """Raise PrivacyError if the prompt contains any of the given account numbers (spaces/dashes ignored)."""
    squashed = re.sub(r"[\s-]", "", prompt)
    for secret in secrets:
        digits = _digits(secret or "")
        if len(digits) >= MIN_SECRET_DIGITS and digits in squashed:
            raise PrivacyError("a bank account number is present in the prompt; refusing to send it")