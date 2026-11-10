"""Batch processing.  This is the interface Meridian's nightly batch job uses:

    python -m ledgerline.cli predict --input ../data/invoices/dev --reference ../data/reference \
        --output ../submission/predictions_dev.jsonl

See docs/OUTPUT_CONTRACT.md for the output format.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import db
from .pipeline import process_document
from .reference import load_reference

SUPPORTED_SUFFIXES = {".txt", ".eml", ".json"}
MONEY_FIELDS = ["subtotal", "cgst", "sgst", "igst", "round_off", "total"]
TEXT_FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
               "bank_account", "ifsc", "po_number"]


def to_contract(invoice: dict) -> dict:
    out = {"document_id": invoice["document_id"]}
    out.update({f: invoice[f] for f in TEXT_FIELDS})
    out.update({f: None if invoice[f] is None else f"{invoice[f]:.2f}" for f in MONEY_FIELDS})
    out["line_items"] = invoice["line_items"]
    out["needs_review"] = invoice["needs_review"]
    out["review_reasons"] = invoice["review_reasons"]
    out["required_approvals"] = invoice["required_approvals"]
    out["usage"] = invoice["usage"]
    return out


def failed_contract(document_id: str) -> dict:
    """The line for a document that could not be processed at all (OUTPUT_CONTRACT: never skip)."""
    zero = "0.00"
    return {
        "document_id": document_id, "document_type": "invoice", "supplier_name": "", "supplier_gstin": None,
        "invoice_number": "", "invoice_date": "", "currency": "INR", "subtotal": zero, "cgst": zero,
        "sgst": zero, "igst": zero, "round_off": zero, "total": zero, "bank_account": None, "ifsc": None,
        "po_number": None, "line_items": [], "needs_review": True, "review_reasons": ["processing_error"],
        "required_approvals": 1,
        "usage": {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0, "latency_ms": 0},
    }


def predict(args: argparse.Namespace) -> None:
    ref = load_reference(args.reference)
    db_path = args.db or str(Path(tempfile.mkdtemp(prefix="ledgerline-")) / "predict.db")
    conn = db.connect(db_path)
    documents = sorted((p for p in Path(args.input).iterdir() if p.suffix in SUPPORTED_SUFFIXES),
                       key=lambda p: p.stem)
    written = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for path in documents:
            try:
                invoice = process_document(conn, ref, path.read_text(encoding="utf-8", errors="replace"), path.stem,
                                           filename=path.name)
            except Exception as exc:  # never skip a document: write it as a processing_error
                print(f"[processing_error] {path.name}: {exc}", file=sys.stderr)
                out.write(json.dumps(failed_contract(path.stem), ensure_ascii=False) + "\n")
                written += 1
                continue
            if invoice["review_reasons"] == ["processing_error"]:
                print(f"[processing_error] {path.name}: {'; '.join(invoice['warnings'])}", file=sys.stderr)
            out.write(json.dumps(to_contract(invoice), ensure_ascii=False) + "\n")
            written += 1
    print(f"wrote {written}/{len(documents)} predictions to {args.output}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ledgerline")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("predict", help="process a folder of documents and write predictions.jsonl")
    p.add_argument("--input", required=True, help="folder containing .txt / .eml / .json documents")
    p.add_argument("--reference", default=None, help="folder with vendors.csv, paid_invoices.csv, buyer.json")
    p.add_argument("--output", required=True, help="where to write predictions (JSON Lines)")
    p.add_argument("--db", default=None, help="SQLite file to use (default: a fresh temporary database)")
    args = parser.parse_args(argv)
    if args.command == "predict":
        predict(args)


if __name__ == "__main__":
    main()