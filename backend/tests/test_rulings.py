"""Rulings on the disputed documents (RULINGS.md): both rules are off unless their flag is set."""
import json
from datetime import date
from pathlib import Path

from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.pipeline import process_document
from ledgerline.validation import check_future_date, check_line_arithmetic
from tests.test_routing import make_invoice
from ledgerline.models import LineItem

DISPUTED = Path(__file__).resolve().parents[2] / "data" / "invoices" / "disputed"


def run(conn, ref, monkeypatch, extraction, raw):
    client = FakeClient([json.dumps(extraction)] * 2)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return process_document(conn, ref, raw, "doc_rule")


# disp_05: 4 x 3,850.00 is 15,400.00 but the line prints 15,950.00, and the subtotal adds up to the wrong line
DISP05 = dict(CANNED_EXTRACTION, supplier_name="Precision Gauges & Instruments", supplier_gstin="27AABFP2915E1ZK",
              invoice_number="PGI/26-27/018", invoice_date="06/05/2026", subtotal="24,950.00", cgst="2,245.50",
              sgst="2,245.50", igst="0.00", round_off="0.00", total="29,441.00", po_number="PO-2026-0157",
              line_items=[{"description": "Plug Gauge 20H7", "quantity": "4", "unit_price": "3,850.00", "amount": "15,950.00"},
                          {"description": "Calibration", "quantity": "6", "unit_price": "1,500.00", "amount": "9,000.00"}])


def test_line_arithmetic_flag_is_off_by_default(conn, ref, monkeypatch):
    monkeypatch.delenv("LEDGERLINE_FLAG_LINE_ARITHMETIC", raising=False)
    out = run(conn, ref, monkeypatch, DISP05, "x")
    assert "line_amount_mismatch" not in out["review_reasons"]


def test_line_arithmetic_flag_catches_a_wrong_line_that_adds_up(conn, ref, monkeypatch):
    monkeypatch.setenv("LEDGERLINE_FLAG_LINE_ARITHMETIC", "1")
    out = run(conn, ref, monkeypatch, DISP05, "x")
    assert "line_amount_mismatch" in out["review_reasons"] and out["needs_review"]


def test_correct_lines_are_not_flagged():
    inv = make_invoice(line_items=[LineItem("Bolt", 1200.0, 71.2, 85440.0), LineItem("Gauge", 750.0, 98.45, 73837.5)])
    assert check_line_arithmetic(inv) == []
    assert check_line_arithmetic(make_invoice(line_items=[LineItem("Bolt", 4.0, 3850.0, 15950.0)])) == ["line_amount_mismatch"]


def test_future_date_uses_the_email_send_date(monkeypatch):
    raw = "From: a@b.example\nDate: Tue, 28 Apr 2026 12:05:00 +0530\nSubject: x\n\nbody"
    assert check_future_date(make_invoice(invoice_date=date(2026, 6, 25)), raw) == ["invoice_date_in_future"]
    assert check_future_date(make_invoice(invoice_date=date(2026, 4, 28)), raw) == []


def test_future_date_without_a_header_uses_the_as_of_day(monkeypatch):
    monkeypatch.setenv("LEDGERLINE_AS_OF", "2026-05-15")
    assert check_future_date(make_invoice(invoice_date=date(2026, 6, 25)), "plain text") == ["invoice_date_in_future"]
    assert check_future_date(make_invoice(invoice_date=date(2026, 5, 12)), "plain text") == []


def test_future_date_flag_routes_disp_06_to_review(conn, ref, monkeypatch):
    raw = (DISPUTED / "disp_06.eml").read_text(encoding="utf-8")
    ext = dict(CANNED_EXTRACTION, supplier_name="Shakti Castings Pvt. Ltd.", supplier_gstin="27AAPCS5512H1Z4",
               invoice_number="SCPL/26-27/011", invoice_date="25/06/2026", subtotal="70,500.00", cgst="6,345.00",
               sgst="6,345.00", igst="0.00", round_off="0.00", total="83,190.00", bank_account=None,
               line_items=[{"description": "Casting", "quantity": "30", "unit_price": "2,350.00", "amount": "70,500.00"}])
    monkeypatch.delenv("LEDGERLINE_FLAG_FUTURE_DATE", raising=False)
    assert "invoice_date_in_future" not in run(conn, ref, monkeypatch, ext, raw)["review_reasons"]
    monkeypatch.setenv("LEDGERLINE_FLAG_FUTURE_DATE", "1")
    out = run(conn, ref, monkeypatch, ext, raw)
    assert "invoice_date_in_future" in out["review_reasons"] and out["needs_review"]


def test_spaces_around_slashes_in_an_invoice_number_are_not_part_of_the_number():
    from ledgerline.pipeline import normalize
    assert normalize({"invoice_number": "SIS / 26-27 / 0018", "currency": "INR"}).invoice_number == "SIS/26-27/0018"
