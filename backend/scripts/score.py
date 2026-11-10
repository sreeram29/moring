"""Score a predictions file against labels.  python scripts/score.py PRED.jsonl ../data/ground_truth/dev.jsonl"""
import json, statistics, sys
from decimal import Decimal

MONEY = ["subtotal", "cgst", "sgst", "igst", "round_off", "total"]
TEXT = ["document_type", "supplier_gstin", "invoice_number", "invoice_date", "currency", "bank_account", "ifsc", "po_number"]


def load(path):
    return {r["document_id"]: r for r in (json.loads(l) for l in open(path, encoding="utf-8") if l.strip())}


def same_money(a, b):
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:
        return False


def norm(s):
    return " ".join(str(s or "").split()).casefold()


def lines_ok(p, e):
    pl, el = p.get("line_items") or [], e.get("line_items") or []
    if len(pl) != len(el):
        return False
    return all(same_money(a.get("amount"), b.get("amount")) and same_money(a.get("quantity"), b.get("quantity"))
               for a, b in zip(pl, el))


def main(pred_path, gt_path):
    pred = load(pred_path)
    gt = {k: v["expected"] for k, v in load(gt_path).items()}
    field_hits = {f: 0 for f in MONEY + TEXT + ["supplier_name", "line_items"]}
    n = len(gt)
    missed, false_alarm, wrong_reasons, wrong_appr, errors = [], [], [], [], []
    all_fields_ok = 0
    for doc, e in sorted(gt.items()):
        p = pred.get(doc)
        if p is None:
            missed.append((doc, "no prediction")); continue
        ok = True
        for f in MONEY:
            hit = same_money(p.get(f), e.get(f)); field_hits[f] += hit; ok &= hit
        for f in TEXT:
            hit = (p.get(f) or None) == (e.get(f) or None); field_hits[f] += hit; ok &= hit
        hit = norm(p.get("supplier_name")) == norm(e.get("supplier_name")); field_hits["supplier_name"] += hit; ok &= hit
        hit = lines_ok(p, e); field_hits["line_items"] += hit; ok &= hit
        all_fields_ok += ok
        if "processing_error" in (p.get("review_reasons") or []):
            errors.append(doc)
        if e["needs_review"] and not p["needs_review"]:
            missed.append((doc, sorted(e["review_reasons"])))
        if not e["needs_review"] and p["needs_review"]:
            false_alarm.append((doc, sorted(p["review_reasons"])))
        if set(p.get("review_reasons") or []) != set(e["review_reasons"]):
            wrong_reasons.append((doc, sorted(e["review_reasons"]), sorted(p.get("review_reasons") or [])))
        if p.get("required_approvals") != e["required_approvals"]:
            wrong_appr.append((doc, e["required_approvals"], p.get("required_approvals")))
        if not ok:
            print("field diff:", doc)
    need = sum(1 for e in gt.values() if e["needs_review"])
    print(f"\ndocuments {n}  needing review {need}  processing errors {len(errors)}")
    print(f"missed reviews {len(missed)}/{need}: {missed}")
    print(f"unnecessary reviews {len(false_alarm)}: {false_alarm}")
    print(f"reason sets differing {len(wrong_reasons)}: {wrong_reasons}")
    print(f"approvals differing {len(wrong_appr)}: {wrong_appr}")
    print(f"documents with every field right {all_fields_ok}/{n}")
    for f, h in field_hits.items():
        print(f"  {f:16s} {h}/{n}")
    u = [p["usage"] for p in pred.values()]
    lat = sorted(x["latency_ms"] / 1000 for x in u)
    cost = [x["cost_inr"] for x in u]
    def pct(v, q): return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]
    print(f"cost/doc INR mean {statistics.mean(cost):.4f} total {sum(cost):.3f}; calls/doc {statistics.mean(x['llm_calls'] for x in u):.1f}")
    print(f"latency s p50 {pct(lat, .5):.1f} p95 {pct(lat, .95):.1f}")


main(sys.argv[1], sys.argv[2])
