# My first hour

## What I think is going on
Ledgerline's last change let the LLM decide routing, so what the system calls "needs review" is just what the model says. The real checks in validation.py only produce warnings, and some of them look broken. Nothing in the repo measures routing, so the 94% tells us little about whether it's safe to trust.

## Risks I suspect, most serious first
1. Approve can create two payments, and one person can approve twice. Treasury has already seen it.
2. Bank-change and duplicate checks are weak (IFSC only, raw names and numbers). That is the kind of gap fraud uses.
3. Vendor bank accounts go to the LLM provider in the vendor master. That breaks policy 5.1.
4. Cost tracking is off by roughly 1000x (the CTO's $165 vs ₹15).
5. The 94% includes three dev documents pasted into every prompt.

## Plan
Fix routing and the validators first, in code, with tests. Then the approval path and the privacy leak. Part 4: option A, because reviewers can't trace numbers and the approval bugs live in the same code. I expect to cut fine-tuning, model-cascade work and polish on the UI.

## Questions for Meridian
- Which date wins when an email and an invoice disagree?
- Who can approve, and can the same person do both approvals on a high-value invoice?
- Can we hold vendor phone numbers somewhere for call-backs?
- When a vendor sends a revised invoice with the same number, is it a duplicate?
