"""F4: vendor bank account numbers never reach the LLM provider (AP_POLICY 5.1, 5.2)."""
import json
import re
from pathlib import Path

import pytest

from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.pipeline import process_document

DATA = Path(__file__).resolve().parents[2] / "data"
LONG_DIGITS = re.compile(r"\d{9,}")


def all_documents():
    return sorted(p for d in ("dev", "disputed") for p in (DATA / "invoices" / d).iterdir())


def run_and_record(conn, ref, monkeypatch, raw, extraction=None):
    client = FakeClient([json.dumps(extraction or CANNED_EXTRACTION)] * 2)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    out = process_document(conn, ref, raw, "doc_x")
    return out, [system + "\n" + prompt for system, prompt in client.calls]


def accounts_in(ref):
    return {re.sub(r"\D", "", v["bank_account"]) for v in ref.vendors if v["bank_account"]}


def test_vendor_master_and_its_bank_accounts_are_not_sent(conn, ref, monkeypatch):
    _, prompts = run_and_record(conn, ref, monkeypatch, "INVOICE TEXT")
    assert prompts, "the model was never called"
    for prompt in prompts:
        squashed = re.sub(r"[\s-]", "", prompt)
        assert not [a for a in accounts_in(ref) if a in squashed]
        assert "sales@bharatabrasives.example" not in prompt          # nothing else from the vendor master
        assert "Zephyr Bank" not in prompt


def test_no_prompt_for_any_repository_document_contains_an_account_number(conn, ref, monkeypatch):
    for path in all_documents():
        raw = path.read_text(encoding="utf-8")
        out, prompts = run_and_record(conn, ref, monkeypatch, raw)
        for prompt in prompts:
            assert not [a for a in accounts_in(ref) if a in re.sub(r"[\s-]", "", prompt)], path.name


def test_last_four_digits_are_what_the_provider_sees(conn, ref, monkeypatch):
    raw = "Bank Details\n  A/c No.   : 50200012345678\n  IFS Code  : ZEPH0001234\n"
    out, prompts = run_and_record(conn, ref, monkeypatch, raw)
    assert "XXXXXXXXXX5678" in prompts[0] and "50200012345678" not in prompts[0]
    assert out["bank_account"] == "50200012345678"   # code recovered the full number from the original
    assert out["ifsc"] == "ZEPH0001234"


def test_a_model_that_echoes_an_account_number_cannot_leak_it_in_the_second_call(conn, ref, monkeypatch):
    leaky = dict(CANNED_EXTRACTION, bank_account="50200012345678")
    _, prompts = run_and_record(conn, ref, monkeypatch, "INVOICE TEXT", extraction=leaky)
    assert "50200012345678" not in prompts[1]


def test_prompt_contains_the_document_but_none_of_the_dev_set(conn, ref, monkeypatch):
    _, prompts = run_and_record(conn, ref, monkeypatch, "UNIQUE-MARKER-123")
    assert "UNIQUE-MARKER-123" in prompts[0]
    assert "SS Hex Bolt" not in prompts[0]            # the dev documents used to be pasted in as few-shot
    assert "AP POLICY" not in prompts[0]              # routing is code now, so the policy is not sent


def test_pay_to_this_account_instead_is_caught_even_when_the_first_account_is_right(conn, ref, monkeypatch):
    raw = ("Bank: Zephyr Bank\nA/c No: 50200012345678\nIFSC: ZEPH0001234\n"
           "Please pay this invoice to A/c No: 7781002233445 instead.\n")
    out, _ = run_and_record(conn, ref, monkeypatch, raw)
    assert "bank_details_changed" in out["review_reasons"]


@pytest.mark.parametrize("raw,expected", [
    ("A/c No.   : 50200012345678", "50200012345678"),
    ("Payment: NEFT/RTGS to Orbit Bank, Vapi A/c 31840100022917, IFSC ORBK0000415", "31840100022917"),
    ('"AccDet": "50200044102233",', "50200044102233"),
    ("Account Number: 5020 0012 345678", "50200012345678"),
])
def test_account_numbers_are_found_in_every_layout(raw, expected):
    from ledgerline.privacy import bank_details, mask_document
    assert bank_details(raw)[0] == [expected]
    assert expected not in re.sub(r"[\s-]", "", mask_document(raw))


def test_guard_refuses_to_send_a_prompt_that_still_has_an_account_number():
    from ledgerline.privacy import PrivacyError, assert_clean
    with pytest.raises(PrivacyError):
        assert_clean("pay to 5020 0012 3456 78 please", ["50200012345678"])
    assert_clean("pay to XXXXXXXXXX5678 please", ["50200012345678"])