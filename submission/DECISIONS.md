# Decisions

## Part 4 — My choice

I chose option B only partly. I measured two models using real calls: Haiku cost about ₹0.45 per document across nine documents; the final model cost about ₹0.022 per document, with a p95 latency of 6.2 seconds.

I added retries with back-off, configurable model and token limits, and fixed the check pass so it no longer loses a document.

Still missing: escalation to a stronger model after validation failure, provider fallback, and a proper measurement of whether the second pass is worth its cost. The server-side approval safety from Part 1 covers the server half of option A. The evidence UI is not built.

## Stakeholder replies

### Anita — CFO

I would not enable straight-through approval for invoices under ₹10,000 yet. Policy 4.3 requires approval, and I have not measured the miss rate for this group. I suggest checking the 200-document October sample first. Reviewing only flagged documents is estimated to cost about ₹85, around one seventh of reviewing everything. I would not auto-fix GSTINs either; that is a guess about supplier identity. I would show a suggested match for a reviewer to confirm.

### Farhan — AP

Showing the source of each extracted number is not built yet. I would start by storing page and text offsets for each field, then show those references in the reviewer screen. Bank-detail changes already go to review, so I would keep that block. The callback process needs a verified phone number, which we do not currently maintain. I would add the field only after defining who verifies and updates it. The final model is already well below budget; validation is a better next investment than simply choosing a more expensive model.

### Deepak — CTO

The ₹15 cost figure was wrong by about 1,000 times. I used a price listed per 1,000 units as if it were per million. The measured final-model cost is about ₹0.022 per document, with a p95 latency of 6.2 seconds. Haiku was about ₹0.45 per document across nine calls. I would not fine-tune now: we lack labelled data and budget for new infrastructure. The failures I found were mainly in rules and application plumbing.

### Priya — DPO

The current request sends document text with account numbers masked to the last four digits, plus supplier name, GSTIN and line items. It does not send the vendor master, policy text or bank accounts. Names and GSTINs still leave our system, so this is not anonymous data. The masking also depends on recognising an account number from its label; unusual formats may get missed. I would document this clearly and test the guard against different layouts.

### Sunil — Finance Controller

I would not send every invoice to review. The development set has about 54% problem documents, while production is expected to be around 13%. Using the development rate would create too much review work. I would also wait before adding a vendor-phone field until the callback process is defined. The line-arithmetic and future-date checks are implemented behind flags, but both remain off until Finance approves them.

### Ravi — Contractor

I agree that Finance changes policy often and should not need a developer for every threshold change. But putting all rules in prompts is risky: document text can influence the model, as seen in `dev_012`, and prompt behaviour is harder to test and can vary between runs. I suggest keeping rule logic in code while moving thresholds and flags into a configuration file that Finance can edit through an agreed process. This gives Finance flexibility without making approval decisions dependent on the invoice text.
