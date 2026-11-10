"""Process one document end to end: extract -> normalise -> check -> route -> persist."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from . import db
from .extraction import extract
from .llm.pricing import cost_usd
from .models import Invoice, LineItem
from .privacy import bank_details
from .parsing import parse_amount, parse_date
from .reference import ReferenceData
from .validation import compute_reasons, required_approvals


def normalize(data: dict) -> Invoice:
    items = [
        LineItem(
            description=str(item.get("description", "")),
            quantity=parse_amount(item.get("quantity")),
            unit_price=parse_amount(item.get("unit_price")),
            amount=parse_amount(item.get("amount")) or 0.0,
        )
        for item in data.get("line_items") or []
    ]
    return Invoice(
        document_type=data.get("document_type") or "invoice",
        supplier_name=data.get("supplier_name"),
        supplier_gstin=data.get("supplier_gstin"),
        invoice_number=data.get("invoice_number"),
        invoice_date=parse_date(data.get("invoice_date")),
        currency=data.get("currency") or "INR",
        subtotal=parse_amount(data.get("subtotal")),
        cgst=parse_amount(data.get("cgst")) or 0.0,
        sgst=parse_amount(data.get("sgst")) or 0.0,
        igst=parse_amount(data.get("igst")) or 0.0,
        round_off=parse_amount(data.get("round_off")) or 0.0,
        total=parse_amount(data.get("total")),
        bank_account=data.get("bank_account"),
        ifsc=data.get("ifsc"),
        po_number=data.get("po_number"),
        notes=data.get("notes"),
        line_items=items,
    )


def blank_invoice() -> Invoice:
    """Placeholder for a document we could not read; it is stored and routed as processing_error."""
    return Invoice("invoice", None, None, None, None, "INR", None, 0.0, 0.0, 0.0, 0.0, None, None, None,
                   None, None, [])


def process_document(
    conn: sqlite3.Connection,
    ref: ReferenceData,
    raw_text: str,
    document_id: str,
    org_id: str = "meridian",
    filename: str | None = None,
) -> dict:
    data: dict = {}
    responses: list = []
    warnings: list[str] = []
    try:
        data, responses = extract(raw_text, ref)
        inv = normalize(data)
        accounts, ifscs = bank_details(raw_text)  # read by code; the provider never saw the full number
        inv.bank_account = accounts[0] if accounts else None
        inv.ifsc = ifscs[0] if ifscs else None
        # Routing is decided by code (validation.py). Whatever the model claims is only a warning.
        review_reasons = list(dict.fromkeys(compute_reasons(conn, ref, inv, raw_text, org_id)))
        model_reasons = sorted({str(r) for r in (data.get("review_reasons") or [])})
        if model_reasons != sorted(review_reasons):
            warnings.append(f"model proposed {model_reasons}; policy engine decided {sorted(review_reasons)}")
    except Exception as exc:  # never drop a document: store it and send it to a human
        inv = blank_invoice()
        review_reasons = ["processing_error"]
        warnings.append(f"processing_error: {type(exc).__name__}: {exc}")
    needs_review = bool(review_reasons)
    approvals_needed = required_approvals(inv)
    status = "needs_review" if needs_review else "ready_for_approval"

    cur = conn.execute(
        """INSERT INTO invoices (org_id, document_id, filename, raw_text, document_type, supplier_name,
               supplier_gstin, invoice_number, invoice_date, currency, subtotal, cgst, sgst, igst, round_off,
               total, bank_account, ifsc, po_number, notes, line_items_json, warnings_json, needs_review,
               review_reasons_json, required_approvals, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            org_id, document_id, filename, raw_text, inv.document_type, inv.supplier_name, inv.supplier_gstin,
            inv.invoice_number, inv.invoice_date.isoformat() if inv.invoice_date else None, inv.currency,
            inv.subtotal, inv.cgst, inv.sgst, inv.igst, inv.round_off, inv.total, inv.bank_account, inv.ifsc,
            inv.po_number, inv.notes, json.dumps([asdict(i) for i in inv.line_items]), json.dumps(warnings),
            int(needs_review), json.dumps(review_reasons), approvals_needed, status,
        ),
    )
    invoice_id = cur.lastrowid
    for r in responses:
        conn.execute(
            "INSERT INTO llm_calls (invoice_id, document_id, model, input_tokens, output_tokens, cost_usd, "
            "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (invoice_id, document_id, r.model, r.input_tokens, r.output_tokens,
             cost_usd(r.model, r.input_tokens, r.output_tokens), r.latency_ms),
        )
    conn.commit()
    return db.get_invoice(conn, invoice_id)