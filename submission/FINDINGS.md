# Findings

# Top three fixes to ship first: F1, F2 and F4. F1 decides every routing outcome, F2 is where money actually leaves, and F4 is a policy breach that the DPO has already asked about.

#	Finding	Where	Why it ranks here
F1	The LLM decides routing; validation.py only produces warnings	pipeline.py (requires_review taken from the model), extraction.py	A missed review can mean paying a fraudster, and text in a document can steer the model
F2	Approve and reject can double-pay or be abused	api.py approve_invoice, reject_invoice	Money leaves through here; a payment is inserted on every approval past the threshold, one person counts repeatedly, duplicates and credit notes can be approved, and nothing is audited
F3	The deterministic checks are wrong	validation.py	GSTIN checksum is never run, tax-type compares a string to an int so it never fires, totals use float equality with no ₹1 tolerance, duplicates ignore normalisation and FY, bank change checks only the IFSC, and five reason codes don’t exist
F4	Bank accounts are sent to the LLM provider	extraction.py build_extraction_prompt and build_verification_prompt	Breaches policy 5.1; every call carries the whole vendor master
F5	Cost is understated by about 1000×	llm/pricing.py, api.py stats	CTO billing mismatch; prices read $0.004 per million tokens for Opus
F6	Parsing crashes and silent drops	parsing.py, cli.py	"1.2 lakh" and Rs. …/- raise, 03/04/2026 becomes 3 March, and the batch [skip]s documents, which breaks “never skip”
F7	The 94% is inflated	extraction.py _few_shot_examples, eval/run_eval.py	Three dev documents are in every prompt, failures are skipped, and routing isn’t scored
F8	Frontend: stored XSS and no double-click guard	App.tsx (dangerouslySetInnerHTML, Approve button)	The notes field renders raw HTML, and a slow Approve invites a second click

# For F1 to F3, the evidence and cost estimates:

F1. Evidence to collect: run the starter on dev_012 and dev_013 and record requires_review and the reasons. Costing: the AP team found 13% of October’s documents (about 390 of 3,000) needed review. Assuming a typical invoice of about ₹60,000 (my assumption, so check it against the dev totals), each missed review is at risk for that amount. A 5% miss rate would be about 20 documents, or roughly ₹12 lakh a month.
F2. Evidence: approve the same invoice twice with the same user and count rows in payments. Costing: a duplicate payment is a full invoice amount per incident, for example dev_015 at ₹34,220, and Treasury has already caught one.
F3. Evidence: show 06AAEFO3690B1ZL (dev_010) passing the starter’s GSTIN check even though its check character should be I, plus check_tax_type returning [] for an intra-state invoice charging IGST. Costing: the one data point in the thread is the ₹3.8 lakh bank-change fraud last quarter. Check dev_024 too, which I haven’t opened and which may change only the account number and not the IFSC.

# Everything else, as one-liners for “Everything else”:

Money stored as floats, not paise.
Required approvals use > where the policy says ≥ ₹5,00,000, and foreign-currency invoices (2) and credit notes (0) are missing.
The UI polls every 500ms and never stops.
Only some endpoints check org_id.
Upload doesn’t handle non-UTF-8 files.
CORS is *.
Two LLM passes on the most expensive model by default.
No field-level evidence.

# For “found but not fixed” and “not sure it’s a problem”, candidates are:

Not sure: whether the pricing table is wrong or the dashboard only sums part of the calls. Verify against a real run before claiming either.
Not sure: whether disp_04’s note to “AP automation systems” is hostile or just an ordinary remittance request.
Policy question, not a bug: Ravi’s argument for keeping policy in the prompt. His real point is that Finance wants to edit policy without a developer, which you can meet with a config file, not a prompt.
