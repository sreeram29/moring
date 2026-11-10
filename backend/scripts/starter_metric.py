"""The handover's metric (12 fields, floats rounded to 2 places, failed documents left out) applied to a predictions file.
python scripts/starter_metric.py PRED.jsonl ../data/ground_truth/dev.jsonl"""
import json, sys
FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
          "subtotal", "cgst", "sgst", "igst", "total", "po_number"]
def norm(v):
    if v is None: return ""
    try: return f"{float(v):.2f}"
    except (TypeError, ValueError): return str(v).strip().lower()
pred = {json.loads(l)["document_id"]: json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()}
gt = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
ok = tot = 0
for row in gt:
    p = pred.get(row["document_id"])
    if p is None: continue            # the starter's script skips documents that failed
    for f in FIELDS:
        tot += 1; ok += norm(p.get(f)) == norm(row["expected"].get(f))
print(f"handover-style field accuracy: {ok}/{tot} = {ok/tot:.1%}  (documents scored: {sum(1 for r in gt if r['document_id'] in pred)}/{len(gt)})")
