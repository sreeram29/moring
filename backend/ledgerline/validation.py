"""Deterministic policy checks (AP_POLICY.md section 3).

Routing is decided here, in code, and nowhere else. The LLM only extracts fields; whatever it says
about review or approval is ignored (it is kept as a warning so a human can see the disagreement).
Money is compared as Decimal, never as binary floats.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal

from .models import Invoice
from .privacy import bank_details
from .reference import ReferenceData

GSTIN_PATTERN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOTALS_TOLERANCE = Decimal("1.00")
HIGH_VALUE_THRESHOLD = Decimal("500000.00")
NEW_VENDOR_DAYS = 90

# Text addressed to automated systems / AI, or embedded markup (policy: suspicious_content).
# Deliberately broad: the AP Lead would rather have an extra review than a missed one.
_TAG = r"(?:script|img|iframe|svg|style|link|object|embed|form|input|body|html|div|span|a|b|i|p|br|table|meta|base|video|audio|details|marquee)"
SUSPICIOUS_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    rf"<\s*/?\s*{_TAG}(?:\s[^>]*)?/?\s*>",              # html tags (not "<name@host>" in email headers)
    r"javascript\s*:", r"\bon[a-z]{3,}\s*=\s*[\"'`]",     # script handlers / urls
    r"\bAI\b(?:\s+(?:assistants?|agents?|systems?|models?))?",
    r"\b(?:LLM|chatbot|language model)\b",
    r"\bautomat\w*\s+(?:invoice\s+)?(?:processing|system|systems|software|tool|checks?)\b",
    r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions?\b",
    r"\brequires_review\b", r"\breview_reasons\b",
    r"\bpre-?approved\b", r"\bskip\s+(?:the\s+)?(?:checks?|review|validation)\b",
    r"\bdo\s+not\s+(?:flag|mention|report)\b",
)]


def D(value) -> Decimal:
    """Exact decimal from the float/str the pipeline holds. None counts as zero."""
    return Decimal(str(value)) if value is not None else Decimal("0")


# ---------------------------------------------------------------- identity helpers

def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str | None) -> bool:
    """Format AND check digit (Appendix A)."""
    if not gstin:
        return False
    g = gstin.strip().upper()
    return GSTIN_PATTERN.fullmatch(g) is not None and gstin_checksum(g[:14]) == g[14]


def normalize_invoice_number(number: str | None) -> str:
    """Uppercase, strip spaces and / - # . ; leading zeros stay."""
    return re.sub(r"[\s/\-#.]", "", (number or "").upper())


def name_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def is_domestic(inv: Invoice) -> bool:
    return (inv.currency or "").strip().upper() == "INR"


def supplier_key(gstin: str | None, name: str | None, domestic: bool) -> str:
    return (gstin or "").strip().upper() if domestic else name_key(name)


def financial_year(d: date | None) -> int | None:
    if d is None:
        return None
    return d.year if d.month >= 4 else d.year - 1


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _parse_iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- individual rules

def find_vendor(ref: ReferenceData, inv: Invoice) -> dict | None:
    """Domestic: by GSTIN alone (the printed name proves nothing). Foreign: by name key."""
    if is_domestic(inv):
        gstin = (inv.supplier_gstin or "").strip().upper()
        if not gstin:
            return None
        return next((v for v in ref.vendors if (v.get("gstin") or "").strip().upper() == gstin), None)
    key = name_key(inv.supplier_name)
    if not key:
        return None
    return next((v for v in ref.vendors if name_key(v.get("legal_name")) == key), None)


def check_vendor(vendor: dict | None) -> list[str]:
    return [] if vendor else ["vendor_unknown"]


def check_new_vendor(inv: Invoice, vendor: dict | None) -> list[str]:
    onboarded = _parse_iso(vendor.get("onboarded_on")) if vendor else None
    if onboarded and inv.invoice_date and (inv.invoice_date - onboarded).days < NEW_VENDOR_DAYS:
        return ["vendor_new"]
    return []


def check_gstin(inv: Invoice) -> list[str]:
    if is_domestic(inv) and not is_valid_gstin(inv.supplier_gstin):
        return ["gstin_invalid"]
    return []


def check_tax_type(inv: Invoice, buyer_state: str = "27") -> list[str]:
    gstin = (inv.supplier_gstin or "").strip()
    if not is_domestic(inv) or len(gstin) < 2:
        return []
    intra_state = gstin[:2] == str(buyer_state)
    if intra_state and D(inv.igst) != 0:
        return ["tax_type_mismatch"]
    if not intra_state and (D(inv.cgst) != 0 or D(inv.sgst) != 0):
        return ["tax_type_mismatch"]
    return []


def check_totals(inv: Invoice) -> list[str]:
    if inv.total is None:
        return []
    computed = (sum((D(i.amount) for i in inv.line_items), Decimal("0"))
                + D(inv.cgst) + D(inv.sgst) + D(inv.igst) + D(inv.round_off))
    return ["totals_mismatch"] if abs(computed - D(inv.total)) > TOTALS_TOLERANCE else []


def check_duplicate(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian") -> list[str]:
    if inv.document_type != "invoice":
        return []
    key = supplier_key(inv.supplier_gstin, inv.supplier_name, is_domestic(inv))
    number = normalize_invoice_number(inv.invoice_number)
    fy = financial_year(inv.invoice_date)
    if not key or not number:
        return []

    def same(gstin, name, other_number, other_date) -> bool:
        keys = {(gstin or "").strip().upper(), name_key(name)} - {""}
        return key in keys and normalize_invoice_number(other_number) == number \
            and financial_year(other_date) == fy

    for paid in ref.paid_invoices:
        if same(paid.get("supplier_gstin"), paid.get("supplier_name"), paid.get("invoice_number"),
                _parse_iso(paid.get("invoice_date"))):
            return ["duplicate"]
    rows = conn.execute(
        "SELECT supplier_gstin, supplier_name, invoice_number, invoice_date FROM invoices "
        "WHERE org_id = ? AND document_type = 'invoice'", (org_id,)).fetchall()
    for r in rows:
        if same(r["supplier_gstin"], r["supplier_name"], r["invoice_number"], _parse_iso(r["invoice_date"])):
            return ["duplicate"]
    return []


def check_bank_details(inv: Invoice, vendor: dict | None, raw_text: str = "") -> list[str]:
    """Any account number or IFSC printed in the document that differs from the vendor's record.

    Bank details come from the original document (privacy.bank_details), not from the model, so a
    second "pay here instead" account further down the page is caught too.
    """
    if not vendor:
        return []
    accounts, ifscs = bank_details(raw_text)
    accounts = accounts or ([_digits(inv.bank_account)] if inv.bank_account else [])
    ifscs = ifscs or ([inv.ifsc.strip().upper()] if inv.ifsc else [])
    v_acct, v_ifsc = _digits(vendor.get("bank_account")), (vendor.get("ifsc") or "").strip().upper()
    if v_acct and any(a and a != v_acct for a in accounts):
        return ["bank_details_changed"]
    if v_ifsc and any(i and i != v_ifsc for i in ifscs):
        return ["bank_details_changed"]
    return []


def check_foreign_currency(inv: Invoice) -> list[str]:
    return [] if is_domestic(inv) else ["foreign_currency"]


def check_suspicious(*texts: str | None) -> list[str]:
    blob = "\n".join(t for t in texts if t)
    return ["suspicious_content"] if any(p.search(blob) for p in SUSPICIOUS_PATTERNS) else []


def check_processable(inv: Invoice) -> list[str]:
    """Fields we cannot route without. A document we cannot read reliably always goes to review."""
    if inv.invoice_date is None or not (inv.invoice_number or "").strip() or inv.total is None:
        return ["processing_error"]
    return []


# ---------------------------------------------------------------- the decision

def compute_reasons(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, raw_text: str = "",
                    org_id: str = "meridian") -> list[str]:
    vendor = find_vendor(ref, inv)
    reasons: list[str] = []
    if inv.document_type == "credit_note":
        reasons.append("credit_note")
    reasons += check_duplicate(conn, ref, inv, org_id)
    reasons += check_gstin(inv)
    reasons += check_vendor(vendor)
    reasons += check_new_vendor(inv, vendor)
    reasons += check_bank_details(inv, vendor, raw_text)
    reasons += check_tax_type(inv, str(ref.buyer.get("state_code", "27")))
    reasons += check_totals(inv)
    reasons += check_foreign_currency(inv)
    reasons += check_suspicious(raw_text, inv.notes)
    reasons += check_processable(inv)
    return reasons


def required_approvals(inv: Invoice) -> int:
    """AP_POLICY section 4.1."""
    if inv.document_type == "credit_note":
        return 0
    if not is_domestic(inv):
        return 2
    if inv.total is not None and D(inv.total) >= HIGH_VALUE_THRESHOLD:
        return 2
    return 1


def run_checks(conn, ref, inv, raw_text: str = "") -> list[str]:  # kept for older callers
    return compute_reasons(conn, ref, inv, raw_text)