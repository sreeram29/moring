"""F2: approvals are enforced on the server and are safe under double-clicks, retries and races."""
import json
import threading

import pytest

from ledgerline import approvals, db
from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.pipeline import process_document


def make_doc(conn, ref, monkeypatch, doc_id="doc_001", **overrides):
    client = FakeClient([json.dumps(dict(CANNED_EXTRACTION, **overrides))] * 2)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return process_document(conn, ref, "INVOICE TEXT", doc_id)


def payments(conn, invoice_id):
    return conn.execute("SELECT COUNT(*) FROM payments WHERE invoice_id = ?", (invoice_id,)).fetchone()[0]


def test_repeated_approval_by_same_person_creates_one_payment(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch)
    first = approvals.approve(conn, inv["id"], "kavya", "")
    again = approvals.approve(conn, inv["id"], "kavya", "")   # double click / retry
    assert first["status"] == again["status"] == "approved"
    assert again["already_recorded"] is True
    assert payments(conn, inv["id"]) == 1


def test_one_person_cannot_provide_both_approvals(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch, total="600000.00", subtotal="600000.00", cgst="0", sgst="0",
                   line_items=[{"description": "x", "quantity": "1", "unit_price": "600000", "amount": "600000"}],
                   round_off="0")
    assert inv["required_approvals"] == 2
    approvals.approve(conn, inv["id"], "kavya", "")
    again = approvals.approve(conn, inv["id"], "Kavya ", "")  # same person, different spelling
    assert again["approvals"] == 1 and again["status"] != "approved"
    assert payments(conn, inv["id"]) == 0
    done = approvals.approve(conn, inv["id"], "farhan", "")
    assert done["status"] == "approved" and payments(conn, inv["id"]) == 1


def test_extra_approver_after_completion_is_refused_and_pays_once(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch)
    approvals.approve(conn, inv["id"], "kavya", "")
    with pytest.raises(approvals.DecisionError) as e:
        approvals.approve(conn, inv["id"], "farhan", "")
    assert e.value.status_code == 409 and payments(conn, inv["id"]) == 1


def test_duplicates_can_be_rejected_but_never_approved(conn, ref, monkeypatch):
    make_doc(conn, ref, monkeypatch, doc_id="doc_001")
    dup = make_doc(conn, ref, monkeypatch, doc_id="doc_002")
    assert "duplicate" in dup["review_reasons"]
    with pytest.raises(approvals.DecisionError) as e:
        approvals.approve(conn, dup["id"], "kavya", "looks fine to me")
    assert e.value.status_code == 409 and payments(conn, dup["id"]) == 0
    assert approvals.reject(conn, dup["id"], "kavya", "duplicate")["status"] == "rejected"


def test_credit_notes_cannot_be_approved(conn, ref, monkeypatch):
    cn = make_doc(conn, ref, monkeypatch, document_type="credit_note")
    assert cn["required_approvals"] == 0
    with pytest.raises(approvals.DecisionError) as e:
        approvals.approve(conn, cn["id"], "kavya", "ok")
    assert e.value.status_code == 409 and payments(conn, cn["id"]) == 0


def test_approving_a_flagged_document_needs_a_note(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch, supplier_gstin="06AAEFO3690B1ZL")  # invalid GSTIN -> review
    assert inv["needs_review"]
    with pytest.raises(approvals.DecisionError) as e:
        approvals.approve(conn, inv["id"], "kavya", "   ")
    assert e.value.status_code == 422
    assert approvals.approve(conn, inv["id"], "kavya", "checked with vendor")["status"] == "approved"


def test_rejected_invoice_cannot_be_approved_and_approved_cannot_be_rejected(conn, ref, monkeypatch):
    a = make_doc(conn, ref, monkeypatch, doc_id="doc_001")
    approvals.reject(conn, a["id"], "kavya", "wrong PO")
    with pytest.raises(approvals.DecisionError):
        approvals.approve(conn, a["id"], "farhan", "")
    b = make_doc(conn, ref, monkeypatch, doc_id="doc_002", invoice_number="SIS/26-27/0099")
    approvals.approve(conn, b["id"], "kavya", "")
    with pytest.raises(approvals.DecisionError) as e:
        approvals.reject(conn, b["id"], "farhan", "too late")
    assert e.value.status_code == 409 and payments(conn, b["id"]) == 1


def test_every_decision_is_audited_once(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch)
    approvals.approve(conn, inv["id"], "kavya", "ok")
    approvals.approve(conn, inv["id"], "kavya", "ok")  # retry is not logged twice
    rows = conn.execute("SELECT user_id, action, note, created_at FROM audit_log").fetchall()
    assert [(r["user_id"], r["action"], r["note"]) for r in rows] == [("kavya", "approve", "ok")]
    assert rows[0]["created_at"]


def test_other_organisations_cannot_decide(conn, ref, monkeypatch):
    inv = make_doc(conn, ref, monkeypatch)
    with pytest.raises(approvals.DecisionError) as e:
        approvals.approve(conn, inv["id"], "mallory", "", org_id="someone_else")
    assert e.value.status_code == 404


def test_concurrent_clicks_create_exactly_one_payment(tmp_path, ref, monkeypatch):
    path = str(tmp_path / "race.db")
    setup = db.connect(path)
    inv = make_doc(setup, ref, monkeypatch)
    results, errors = [], []

    def click():
        c = db.connect(path)
        try:
            results.append(approvals.approve(c, inv["id"], "kavya", ""))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=click) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert payments(setup, inv["id"]) == 1
    assert sum(1 for r in results if not r["already_recorded"]) == 1