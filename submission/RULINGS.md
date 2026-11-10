# Rulings

## Flags

Both checks are off by default. I enabled them for the `predictions_disputed.jsonl` replay.

- `LEDGERLINE_FLAG_LINE_ARITHMETIC=1`: adds `line_amount_mismatch` when quantity × rate differs from the printed line amount by more than ₹0.05.
- `LEDGERLINE_FLAG_FUTURE_DATE=1`: adds `invoice_date_in_future` when the invoice date is later than the email date or the replay's current date.
- `LEDGERLINE_AS_OF=2026-05-15`: fixes the date used for replay. This is not a policy flag.

## disp_01 — Sitara

**Ruling: Review; one approval.**

The GSTIN `27AAKCS4B21M1ZW` fails its checksum and does not match the vendor master. The reasons are `gstin_invalid` and `vendor_unknown`.

The name, address, bank account and PO match Sitara, so this may just be a typo. But those details are not enough to prove the GSTIN is valid. Automatically correcting it could let a false identity through. I would show the closest GSTIN from the vendor master as a suggestion, without changing the invoice.

## disp_02 — Sitara revised invoice

**Ruling: Duplicate; reject only.**

The supplier, normalised invoice number and financial year match an earlier invoice (`dev_015`). The policy does not allow this document to be approved.

The rate has changed from ₹1,450 to ₹1,520, so it may be a genuine correction. However, the policy does not explain how revisions should work. I would propose a `supersedes invoice` process: cancel the earlier invoice, link the replacement and require two approvals. This is not implemented.

## disp_03 — Narmada

**Ruling: Foreign currency; two approvals.**

The invoice is in USD. Under the policy, currency determines the domestic or foreign route, regardless of the Indian GSTIN.

The pipeline may also report `vendor_unknown` or a tax-related reason because the foreign-document supplier match uses the name. The main policy gap is how to validate GST when an Indian registered supplier issues a USD invoice with tax shown in INR. Finance should define the exchange-rate source and validation method. Until then, I would keep the foreign-currency route.

## disp_04 — Vardhan

**Ruling: Review under `suspicious_content`.**

The bank details match the master and the totals add up. The email asks the system to quote the invoice number for automated matching.

That request looks harmless, and flagging every message addressed to software could create noise. I would narrow the rule to content that tries to influence the decision, bypass checks or force approval. Under the current wording, though, the review flag remains.

## disp_05 — Precision Gauges

**Ruling: Review.**

The line is 4 × ₹3,850 = ₹15,400, but the invoice prints ₹15,950. The subtotal, tax and total are based on the higher amount.

The existing policy checks the line against the stated total, so the invoice passes that check. I still think it should be reviewed because the line calculation is wrong by ₹550.

I added `line_amount_mismatch` behind `LEDGERLINE_FLAG_LINE_ARITHMETIC`, with a five-paise tolerance. It is tested in `tests/test_rulings.py` and remains off by default.

## disp_06 — Shakti

**Ruling: Review.**

The invoice date is 25 June 2026, but the email was received on 28 April 2026. The vendor was onboarded on 20 March, so accepting the future invoice date could hide the new-vendor window.

Post-dated invoices can be normal in some industries, but the date difference should be checked. I added `invoice_date_in_future` behind `LEDGERLINE_FLAG_FUTURE_DATE` and tested it. The flag is off by default.

## Highest-risk cases

I consider disp_05 and disp_06 the riskiest. The written policy could allow both through without review. One has an incorrect line amount; the other has a future invoice date that affects the vendor-onboarding check.
