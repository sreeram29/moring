"""HTTP API used by the reviewer UI.  Run: uvicorn ledgerline.api:app --reload"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import approvals, db
from .approvals import DecisionError
from .config import USD_TO_INR, get_settings
from .pipeline import process_document
from .reference import load_reference

app = FastAPI(title="Ledgerline API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_conn():
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_org(x_org_id: str = Header(default="meridian")) -> str:
    return x_org_id


class DecisionRequest(BaseModel):
    user_id: str
    note: str = ""


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/invoices")
async def upload_invoice(file: UploadFile, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    raw_text = (await file.read()).decode("utf-8")
    document_id = (file.filename or "upload").rsplit(".", 1)[0]
    return process_document(conn, load_reference(), raw_text, document_id, org_id=org_id, filename=file.filename)


@app.get("/api/invoices")
def list_invoices(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT id, document_id, supplier_name, invoice_number, invoice_date, currency, total, status, "
        "needs_review FROM invoices WHERE org_id = ? ORDER BY id DESC",
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    invoice = db.get_invoice(conn, invoice_id)
    if invoice is None or invoice["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _decide(action, invoice_id: int, body: "DecisionRequest", org_id: str, conn):
    try:
        return action(conn, invoice_id, body.user_id, body.note, org_id=org_id)
    except DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org),
                    conn=Depends(get_conn)):
    return _decide(approvals.approve, invoice_id, body, org_id, conn)


@app.post("/api/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org),
                   conn=Depends(get_conn)):
    return _decide(approvals.reject, invoice_id, body, org_id, conn)


@app.get("/api/stats")
def stats(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    """Feeds the cost dashboard."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT c.invoice_id) AS invoices, COALESCE(SUM(c.cost_usd), 0) AS cost_usd "
        "FROM llm_calls c JOIN invoices i ON i.id = c.invoice_id WHERE i.org_id = ?",
        (org_id,),
    ).fetchone()
    total_inr = row["cost_usd"] * USD_TO_INR
    return {
        "invoices_processed": row["invoices"],
        "llm_cost_inr": round(total_inr, 2),
        "avg_llm_cost_per_invoice_inr": round(total_inr / row["invoices"], 4) if row["invoices"] else 0.0,
    }