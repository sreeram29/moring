# Evaluation report

## Setup

- Provider: OpenRouter. Model for every number below: `deepseek/deepseek-v4.1-flash-1017`. Run on 10 Nov 2026 over the 24 labelled dev documents, two model calls per document (extract, then check).
- Reproduce: `python -m ledgerline.cli predict --input ../data/invoices/dev --reference ../data/reference --output ../submission/predictions_dev.jsonl`, then `python scripts/score.py ../submission/predictions_dev.jsonl ../data/ground_truth/dev.jsonl`.
- Earlier, on `anthropic/claude-haiku-4.5`, the first nine dev documents matched the labels on every field and every routing decision (about ₹0.45 per document, p50 5.7 s). That run stopped when the account's credit ran out, so I do not use it for headline numbers.
- Starter: the template's first commit, run on the same model. As shipped it produced **0 of 24** predictions: it parses the reply with a bare `json.loads`, and this model's replies were empty or cut off at the starter's 2,000-token limit, so every document was skipped. For a fair comparison I changed only that: tolerant JSON parsing, an 8,000-token limit and reasoning off. The prompt, leaked examples and checks are untouched. All starter numbers below are from that patched run (`scripts/score.py`, `scripts/starter_metric.py`).

## What the "94%" actually measured

The handover's `eval/run_eval.py` checks 12 text and amount fields. It does not check `round_off`, bank details, line items, `needs_review`, `review_reasons` or `required_approvals`, so it says nothing about the thing Meridian cares about: whether a document that needed review was routed as ready. It compares numbers as floats and rounds to 2 places. It `continue`s past any document that raises an exception, so a failed document is simply left out of the denominator instead of counting as wrong. And the starter's prompt contained examples copied from the dev set, so the model was partly being tested on answers it had been shown. Results on this model: applying the handover's metric to the patched starter's predictions gives **99.7% (287/288 fields)**, higher than the 94.2% in the note, and my pipeline scores the same 99.7% on it. So the number is the wrong thing to look at: on the same predictions the starter **cleared two duplicate invoices as ready** (dev_015, dev_019), raised two false alarms, got 8 of 24 review-reason sets wrong and 3 of 24 approval counts wrong. A metric that cannot tell those two systems apart says nothing about routing.
I could not reproduce the note's 94.2%: the handover does not say which model or run produced it, and on my model the same metric gives 99.7%, so I can only say what the metric leaves out, not why the numbers differ. Removing the leaked examples from the starter’s prompt and rerunning: before my API credit ran out, 4 of the first 14 documents it handled failed outright, because without the examples the model returned quantities and prices such as “500 kg” and “$50.00” that the starter’s parser cannot read. The run could not be completed, so I do not report a no-leak accuracy figure.

## What I chose to measure, and why

1. **Missed reviews** (needed review, routed as ready). This is the number that can pay a fraudster. Target is zero.
2. **Unnecessary reviews.** Each costs about ₹85 of AP time and risks late payment to MSMEs, so I report it next to missed reviews rather than hiding behind it.
3. **Exact review-reason set and required approvals per document**, not only the yes/no, because a reviewer acts on the reasons.
4. **Field exactness as Decimals**, including `round_off`, bank details and line items. Strings are compared after collapsing whitespace.
5. **Cost per document in ₹ and p50/p95 latency**, taken from the `usage` block of real calls.
6. Failures count as failures: a `processing_error` is never a pass.

## Starter versus mine, on the same model

| Metric (24 dev documents, same model) | Starter (patched to run) | Mine |
|---|---|---|
| Missed reviews (needed review, predicted ready) | **2 / 13** (dev_015, dev_019: duplicates) | **0 / 13** |
| Unnecessary reviews | 2 / 11 (dev_003, dev_021: false `tax_type_mismatch`) | **0 / 11** |
| Review-reason sets exactly right | 16 / 24 | **24 / 24** |
| Required approvals right | 21 / 24 (credit note 1 not 0; USD 1 not 2; ₹5,00,000 1 not 2) | **24 / 24** |
| Documents with every field right | 22 / 24 | **23 / 24** |
| Handover-style field accuracy (12 fields) | 99.7% | 99.7% |
| Cost per document, as the system reports it | **₹0.0000** (unknown model priced at zero) | ₹0.022 |
| Cost per document, recomputed from tokens at the same prices | ₹0.039 | ₹0.022 |
| Input tokens per document | about 10,300 | about 1,560 |
| Latency p50 / p95 (s) | 6.7 / 8.3 | **4.3 / 6.2** |
| Model calls per document | 2 | 2 |

The starter's extra ~8,700 input tokens per document are the whole AP policy, the whole vendor master (with every vendor's bank account) and three labelled examples, sent on both calls. The starter's field misses were `dev_015` (it returned the normalized number `SIS26270018`) and `dev_023` (it returned the bank account as `XXXXXXX4411`).

My one field miss was `dev_015`: the model returned the invoice number as printed (`SIS / 26-27 / 0018`) and the label has `SIS/26-27/0018`. The contract says "as printed", the label drops the spaces. I now remove spaces around `/` and `-`, which matches the label and does not affect duplicate detection (the policy already strips them).

## Labels I disagree with

None that change a number. The labels follow the policy literally, including for documents where that is uncomfortable: a wrong line amount whose subtotal still adds up passes `totals_mismatch`. That is a gap in the policy, not in the labels, and it is what my two flags (RULINGS.md) address. I have not seen dev labels that look wrong.

## Failure analysis

- **First real runs failed for four reasons, none of them the model's accuracy:** the provider ran out of credit (402), the free tier rate-limited every call (429), reasoning models used all 2,000 output tokens before answering (empty reply), and e-invoice JSON has no currency field so my code refused it. Fixes: retries with back-off, a larger token limit with an explicit error, currency inferred from the text only when unambiguous, and a check pass that falls back to the first extraction.
- **Remaining errors on this run:** one (invoice-number spacing, normalization, fixed).
- **The risk that remains is not in the dev set.** Routing is decided by code from extracted fields, so a missed review now needs a wrong extraction (a misread digit in a total, a bank account not recognised) or a gap in the policy. Hidden-error documents like `disp_05` pass the literal policy; they are caught only with a flag.

## How much to trust these numbers

Weakly. 24 documents, one run, one model, no repeat to measure variation. Zero misses out of 13 documents that needed review only shows, at 95% confidence, that the true miss rate is below about 23% (rule of three: 3/13). Dev documents are deliberately hostile and the dev set is 54% problem documents against about 13% in production, so a clean dev run does not transfer. It also does not cover scanned-OCR noise at volume, other vendors' layouts, or documents in the 70% OCR-text class beyond what appears here.

## My recommendation

**Yes, with conditions**, not "every invoice, no humans".

1. Keep one human approval on every invoice, as the policy requires. I would not ship the CFO's request for straight-through processing under ₹10,000 yet: nothing here shows the miss rate is low enough, and ₹3.8 lakh was lost last quarter to one fake bank-change email.
2. Hold any bank-detail change for a call-back before the invoice can be approved.
3. Before the board date, run 200 hand-checked October documents (the 13% problem sample the AP team already has) through this pipeline. I would go ahead on zero missed reviews in those 200 and would stop on one.
4. Cost and latency are not the obstacle: about ₹65 a month for 3,000 documents on this model (budget ₹1.50 each), p95 6.2 s (budget 10 s). Spend the headroom on a stronger model for documents that fail validation, not on a bigger default.

What would change my mind: a missed review in the 200-document sample, a model or provider change without a rerun, or the policy being changed to allow automatic approval.

On the AP team's cost to review: at the production mix (13% of about 3,000 documents, so about 390 problem documents a month), reviewing every document would cost about ₹2.5 lakh a month of AP time (3,000 x ₹85); routing only flagged ones (about 390 plus false alarms) costs about ₹33,000 plus ₹85 for each false alarm. That is the trade I am making.
