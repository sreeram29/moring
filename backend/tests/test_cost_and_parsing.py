"""F5 (cost accounting) and F6 (parsing) regression tests."""
import json
from datetime import date
from pathlib import Path

import pytest

from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.llm.pricing import UnknownModelPrice, cost_usd
from ledgerline.parsing import parse_amount, parse_date, parse_quantity
from ledgerline.pipeline import process_document

DATA = Path(__file__).resolve().parents[2] / "data"


def run(conn, ref, monkeypatch, extraction, doc_id="doc_x", model="fake"):
    client = FakeClient([json.dumps(extraction)] * 2, model=model)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return process_document(conn, ref, "INVOICE TEXT", doc_id)


# ------------------------------------------------------------------ F5: cost accounting

def test_prices_are_per_million_tokens():
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
    assert cost_usd("claude-opus-5-5", 0, 1_000_000) == pytest.approx(20.0)
    assert cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_an_unpriced_model_is_an_error_not_a_free_call():
    with pytest.raises(UnknownModelPrice):
        cost_usd("some-new-model", 1000, 1000)


def test_get_client_refuses_an_unpriced_model(monkeypatch):
    from ledgerline.llm import get_client
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_MODEL", "some-new-model")
    with pytest.raises(UnknownModelPrice):
        get_client()


def test_price_can_be_set_by_environment_for_local_models(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_IN_USD_PER_MTOK", "0")
    monkeypatch.setenv("LLM_PRICE_OUT_USD_PER_MTOK", "0")
    assert cost_usd("llama3", 5000, 5000) == 0


def test_a_call_that_was_made_is_billed_even_if_the_document_then_fails(conn, ref, monkeypatch):
    client = FakeClient([json.dumps(CANNED_EXTRACTION), "this is not json"], model="claude-sonnet-5-5")
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    out = process_document(conn, ref, "x" * 4000, "doc_fail")
    assert out["review_reasons"] == ["processing_error"]
    assert out["usage"]["llm_calls"] == 2          # both responses were paid for
    assert out["usage"]["cost_inr"] > 0


def test_typical_document_cost_is_in_the_right_order_of_magnitude():
    # ~5,000 input + ~600 output tokens on the starter's default model should cost a few rupees, not paise.
    inr = cost_usd("claude-opus-5-5", 5000, 600) * 88
    assert 0.5 < inr < 5


# ------------------------------------------------------------------ F6: amounts

@pytest.mark.parametrize("printed,expected", [
    ("1,23,456.78", 123456.78),
    ("₹1,41,600.00", 141600.0),
    ("Rs. 25,370/-", 25370.0),
    ("Rs 1,00,819/-", 100819.0),
    ("INR 21,500.00", 21500.0),
    ("USD 1,298.00", 1298.0),
    ("$1,250.50", 1250.5),
    ("₹1.2 lakh", 120000.0),
    ("5 lakh", 500000.0),
    ("2.5 crore", 25000000.0),
    ("-0.40", -0.4),
    ("−0.40", -0.4),
    ("(1,234.50)", -1234.5),
    (2480, 2480.0),
    ("", None),
    (None, None),
])
def test_amounts_as_printed(printed, expected):
    assert parse_amount(printed) == expected


def test_an_unreadable_amount_raises_instead_of_guessing():
    for bad in ("twelve", "1,2x3", "N/A"):
        with pytest.raises(ValueError):
            parse_amount(bad)


def test_quantities_may_carry_a_unit():
    assert parse_quantity("10 box") == 10.0
    assert parse_quantity("2,000 kg") == 2000.0
    assert parse_quantity(None) is None


# ------------------------------------------------------------------ F6: dates

@pytest.mark.parametrize("printed,expected", [
    ("03/04/2026", date(2026, 4, 3)),      # Indian vendors: day first
    ("03-04-2026", date(2026, 4, 3)),
    ("03.04.2026", date(2026, 4, 3)),
    ("25/04/2026", date(2026, 4, 25)),
    ("2026-04-05", date(2026, 4, 5)),      # ISO stays year-month-day
    ("2026-04-05T10:00:00", date(2026, 4, 5)),
    ("25 Apr 2026", date(2026, 4, 25)),
    ("April 25, 2026", date(2026, 4, 25)),
])
def test_dates_are_day_first_by_default(printed, expected):
    assert parse_date(printed) == expected


def test_us_vendors_print_month_first():
    assert parse_date("04/03/2026", month_first=True) == date(2026, 4, 3)
    assert parse_date("2026-04-03", month_first=True) == date(2026, 4, 3)


def test_an_impossible_date_raises():
    for bad in ("31/02/2026", "13/13/2026", "not a date"):
        with pytest.raises(ValueError):
            parse_date(bad)


def test_pipeline_reads_an_indian_vendors_ambiguous_date_day_first(conn, ref, monkeypatch):
    out = run(conn, ref, monkeypatch, dict(CANNED_EXTRACTION, invoice_date="03/04/2026"))
    assert out["invoice_date"] == "2026-04-03"


def test_pipeline_reads_a_us_vendors_date_month_first(conn, ref, monkeypatch):
    usd = dict(CANNED_EXTRACTION, supplier_name="CloudNimbus Inc.", supplier_gstin=None, currency="USD",
               invoice_date="04/03/2026", invoice_number="CN-2026-0999")
    out = run(conn, ref, monkeypatch, usd)
    assert out["invoice_date"] == "2026-04-03"


def test_missing_currency_is_not_assumed_to_be_inr(conn, ref, monkeypatch):
    out = run(conn, ref, monkeypatch, dict(CANNED_EXTRACTION, currency=""))
    assert out["review_reasons"] == ["processing_error"]


def test_dev_005_printed_with_lakh_amounts_is_processed_not_crashed(conn, ref, monkeypatch):
    rows = {json.loads(x)["document_id"]: json.loads(x) for x in
            (DATA / "ground_truth" / "dev.jsonl").read_text(encoding="utf-8").splitlines()}
    e = {k: v for k, v in rows["dev_005"]["expected"].items() if k not in ("needs_review", "review_reasons")}
    e["subtotal"] = "₹1.2 lakh"
    e["line_items"] = [dict(i, amount="₹1.2 lakh") for i in e["line_items"]]
    e["total"] = "Rs. 1,41,600/-"
    raw = (DATA / "invoices" / "dev" / "dev_005.eml").read_text(encoding="utf-8")
    client = FakeClient([json.dumps(e)] * 2)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    out = process_document(conn, ref, raw, "dev_005")
    assert out["review_reasons"] == ["bank_details_changed"]