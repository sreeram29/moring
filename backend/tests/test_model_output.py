"""Models do not always answer with bare JSON; a readable answer must not become a processing_error."""
import json

import pytest

from ledgerline.extraction import ModelOutputError, parse_model_json
from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.pipeline import process_document

OBJ = {"supplier_name": "A {braced} name", "total": "1,180.00", "line_items": [{"amount": "1,000.00"}]}


@pytest.mark.parametrize("reply", [
    json.dumps(OBJ),
    "```json\n" + json.dumps(OBJ, indent=2) + "\n```",
    "```\n" + json.dumps(OBJ) + "\n```",
    "Here is the extraction:\n" + json.dumps(OBJ) + "\nLet me know if you need anything else.",
    "{not valid} then " + json.dumps(OBJ),
])
def test_json_is_found_in_whatever_wrapper_the_model_uses(reply):
    assert parse_model_json(reply) == OBJ


@pytest.mark.parametrize("reply", ["", "I cannot read this document.", "[1, 2, 3]", "{broken json"])
def test_no_object_means_a_clear_error_with_the_start_of_the_reply(reply):
    with pytest.raises(ModelOutputError) as e:
        parse_model_json(reply)
    assert "began" in str(e.value)


def test_a_fenced_reply_is_processed_normally_not_sent_to_review_as_an_error(conn, ref, monkeypatch):
    fenced = "```json\n" + json.dumps(CANNED_EXTRACTION, indent=2) + "\n```"
    client = FakeClient([fenced, fenced])
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    out = process_document(conn, ref, "INVOICE TEXT", "doc_fenced")
    assert "processing_error" not in out["review_reasons"]
    assert out["supplier_name"] == CANNED_EXTRACTION["supplier_name"]


def test_currency_is_inferred_only_when_the_text_is_unambiguous():
    from ledgerline.pipeline import infer_currency
    assert infer_currency('{"Gstin": "27AAACK9034R1ZX", "TotInvVal": 72275.0}') == "INR"
    assert infer_currency("Total due (USD) $1,298.00") == "USD"
    assert infer_currency("Total $100 and Rs 200") == ""
    assert infer_currency("") == ""


def test_normalize_uses_the_text_when_the_model_gave_no_currency():
    from ledgerline.pipeline import normalize
    inv = normalize({"supplier_name": "Konkan  Tooling Pvt. Ltd."}, None, "GSTIN 27AAACK9034R1ZX Rs 10")
    assert inv.currency == "INR" and inv.supplier_name == "Konkan Tooling Pvt. Ltd."
