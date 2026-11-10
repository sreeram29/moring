"""Approve / reject rules (AP_POLICY section 4), enforced on the server.

Every decision runs inside one write transaction (BEGIN IMMEDIATE), so two clicks, a retry, or two
workers cannot interleave: the second one waits, then sees the first one's result. The database also
backs this up with unique indexes (one approval per person per invoice, one payment per invoice).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager


class DecisionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@contextmanager
def _write_tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _load(conn: sqlite3.Connection, invoice_id: int, org_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, org_id, status, needs_review, required_approvals, review_reasons_json, total, "
        "document_type FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None or row["org_id"] != org_id:
        raise DecisionError(404, "Invoice not found")
    return row


def _user(user_id: str | None) -> str:
    user = (user_id or "").strip().lower()
    if not user:
        raise DecisionError(422, "user_id is required")
    return user


def _result(conn, row, status: str, already: bool) -> dict:
    count = conn.execute("SELECT COUNT(DISTINCT user_id) FROM approvals WHERE invoice_id = ?",
                         (row["id"],)).fetchone()[0]
    return {"id": row["id"], "approvals": count, "required_approvals": row["required_approvals"],
            "status": status, "already_recorded": already}


def approve(conn: sqlite3.Connection, invoice_id: int, user_id: str, note: str = "",
            org_id: str = "meridian") -> dict:
    user = _user(user_id)
    with _write_tx(conn):
        row = _load(conn, invoice_id, org_id)
        reasons = json.loads(row["review_reasons_json"] or "[]")
        if row["document_type"] == "credit_note" or "credit_note" in reasons or row["required_approvals"] < 1:
            raise DecisionError(409, "Credit notes cannot be approved for payment")
        if "duplicate" in reasons:
            raise DecisionError(409, "Duplicate invoices cannot be approved; reject them instead")
        if row["status"] == "rejected":
            raise DecisionError(409, "This invoice was rejected")
        mine = conn.execute("SELECT 1 FROM approvals WHERE invoice_id = ? AND user_id = ?",
                            (invoice_id, user)).fetchone()
        if mine:  # a retry or a double click: same answer, nothing new recorded
            return _result(conn, row, row["status"], already=True)
        if row["status"] == "approved":
            raise DecisionError(409, "This invoice is already fully approved")
        if row["needs_review"] and not (note or "").strip():
            raise DecisionError(422, "A note is required to approve a document that needed review")

        conn.execute("INSERT INTO approvals (invoice_id, user_id, note) VALUES (?, ?, ?)",
                     (invoice_id, user, (note or "").strip()))
        conn.execute("INSERT INTO audit_log (invoice_id, user_id, action, note) VALUES (?, ?, 'approve', ?)",
                     (invoice_id, user, (note or "").strip()))
        status = row["status"]
        count = conn.execute("SELECT COUNT(DISTINCT user_id) FROM approvals WHERE invoice_id = ?",
                             (invoice_id,)).fetchone()[0]
        if count >= row["required_approvals"]:
            status = "approved"
            conn.execute("UPDATE invoices SET status = 'approved' WHERE id = ?", (invoice_id,))
            conn.execute("INSERT INTO payments (invoice_id, amount) VALUES (?, ?)", (invoice_id, row["total"]))
        return _result(conn, row, status, already=False)


def reject(conn: sqlite3.Connection, invoice_id: int, user_id: str, note: str = "",
           org_id: str = "meridian") -> dict:
    user = _user(user_id)
    with _write_tx(conn):
        row = _load(conn, invoice_id, org_id)
        if row["status"] == "rejected":
            return _result(conn, row, "rejected", already=True)
        if row["status"] == "approved":
            raise DecisionError(409, "This invoice is already approved and queued for payment")
        conn.execute("UPDATE invoices SET status = 'rejected' WHERE id = ?", (invoice_id,))
        conn.execute("INSERT INTO audit_log (invoice_id, user_id, action, note) VALUES (?, ?, 'reject', ?)",
                     (invoice_id, user, (note or "").strip()))
        return _result(conn, row, "rejected", already=False)