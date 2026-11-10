"""F2 over HTTP: status codes and idempotency as the UI sees them."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ledgerline.api import app


@pytest.fixture
def env(tmp_path, monkeypatch, fake_llm):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("LEDGERLINE_DB", path)
    return TestClient(app), path


def upload(client, name="a.txt"):
    return client.post("/api/invoices", files={"file": (name, b"text", "text/plain")}).json()


def payments(path):
    with sqlite3.connect(path) as c:
        return c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]


def test_double_click_returns_ok_twice_and_pays_once(env):
    client, path = env
    inv = upload(client)
    body = {"user_id": "kavya", "note": ""}
    r1 = client.post(f"/api/invoices/{inv['id']}/approve", json=body)
    r2 = client.post(f"/api/invoices/{inv['id']}/approve", json=body)
    assert r1.status_code == r2.status_code == 200
    assert r2.json()["already_recorded"] is True
    assert payments(path) == 1


def test_duplicate_is_409_on_approve_and_200_on_reject(env):
    client, path = env
    upload(client, "a.txt")
    dup = upload(client, "b.txt")  # same invoice number again
    assert "duplicate" in dup["review_reasons"]
    assert client.post(f"/api/invoices/{dup['id']}/approve", json={"user_id": "k", "note": "x"}).status_code == 409
    assert client.post(f"/api/invoices/{dup['id']}/reject", json={"user_id": "k", "note": "dup"}).status_code == 200
    assert payments(path) == 0


def test_unknown_invoice_is_404(env):
    client, _ = env
    assert client.post("/api/invoices/999/approve", json={"user_id": "k", "note": ""}).status_code == 404