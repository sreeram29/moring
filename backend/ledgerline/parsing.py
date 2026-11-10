"""Turn the strings the model copies off the page into Python values (AP_POLICY section 1)."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as dateparser

_MULTIPLIERS = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
                "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CURRENCY_WORDS = re.compile(r"\b(?:rs|inr|usd|us|eur|gbp|rupees?|only)\b\.?|[₹$€£]", re.IGNORECASE)


def parse_decimal(value) -> Decimal | None:
    """Exact decimal from what the document printed.

    Handles Indian grouping (1,23,456.78), Rs./₹/INR/USD prefixes, a /- suffix, (negative) brackets,
    a unicode minus, and the words lakh and crore ("1.2 lakh" -> 120000). Raises ValueError if it
    cannot read the amount: a document with an unreadable amount must go to review, not be guessed.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"cannot read an amount from {value!r}")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace("−", "-").replace("–", "-")
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = _CURRENCY_WORDS.sub(" ", text)
    text = re.sub(r"/-\s*$", "", text.strip()).replace(",", "")
    multiplier = 1
    word = re.search(r"([A-Za-z]+)\s*$", text)
    if word and word.group(1).lower() in _MULTIPLIERS:
        multiplier = _MULTIPLIERS[word.group(1).lower()]
        text = text[: word.start()]
    match = _NUMBER.fullmatch(re.sub(r"[\s()\-+]", "", text))
    if not match:
        raise ValueError(f"cannot read an amount from {value!r}")
    try:
        amount = Decimal(match.group(0)) * multiplier
    except InvalidOperation as exc:
        raise ValueError(f"cannot read an amount from {value!r}") from exc
    return -amount if negative else amount


def parse_amount(value) -> float | None:
    """Like parse_decimal, as the float the rest of the code still stores (all arithmetic goes via Decimal)."""
    amount = parse_decimal(value)
    return None if amount is None else float(amount)


def parse_quantity(value) -> float | None:
    """'10 box' -> 10.0, '2,000 kg' -> 2000.0"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.match(r"\s*([\d,]+(?:\.\d+)?)", str(value))
    if not match:
        raise ValueError(f"cannot read a quantity from {value!r}")
    return float(match.group(1).replace(",", ""))


_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
_NUMERIC = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\s*$")


def parse_date(value, month_first: bool = False) -> date | None:
    """The date printed on the document.

    Indian vendors print day first (DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY); vendors whose country is US print
    month first. ISO dates are read as year-month-day. Anything impossible (31/02/2026) raises ValueError.
    """
    if not value:
        return None
    text = str(value).strip()
    iso = _ISO.match(text)
    if iso:
        year, month, day = (int(g) for g in iso.groups())
        return date(year, month, day)
    numeric = _NUMERIC.match(text)
    if numeric:
        first, second, year = int(numeric.group(1)), int(numeric.group(2)), int(numeric.group(3))
        if year < 100:
            year += 2000
        day, month = (second, first) if month_first else (first, second)
        return date(year, month, day)
    try:  # "25 Apr 2026", "April 25, 2026": month is spelled out, so there is nothing to guess
        return dateparser.parse(text, dayfirst=not month_first).date()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"cannot read a date from {value!r}") from exc