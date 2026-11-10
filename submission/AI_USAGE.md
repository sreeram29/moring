# How I worked with AI

## Tools and models

- Claude (Sonnet 5.5) in the Claude app, with a sandbox copy of the repo for writing and testing code. I applied its files locally, ran the commands and pasted the output back.
- Pipeline models used through OpenRouter: `anthropic/claude-haiku-4.5` (first runs, stopped when credit ran out), a free Gemma model (rate-limited, unusable), and `deepseek/deepseek-v4.1-flash-1017` for the final dev and disputed runs.

## How I set up context

I gave Claude the template repository link first and asked it to explain what was given and the end goal. After that I worked from my own repository, pasting terminal output and attaching generated files (predictions, input documents) for it to read. No `CLAUDE.md` or rules file.

## My workflow

Claude proposed a change and wrote the code and tests; I applied the files, ran pytest, committed in small steps, and pasted failures back. I wrote the first-hour plan, the rulings, the stakeholder replies and the reflection myself, using Claude's notes to check my thinking. I checked output by running the test suite, by running the real pipeline on the dev set, and by comparing the predictions with `data/ground_truth/dev.jsonl`.

## Where the AI was wrong

Real moments from this session (add the transcript location of each, and say honestly which one you went along with at first):

1. **Assumed the model answers with bare JSON.** The first real run turned all 24 documents into `processing_error` because replies came back with extra text. Fix: a tolerant parser, with a test.
2. **Sent retry code before seeing a test-collection error.** The sandbox did not have `httpx`, so the tests had not really run; Claude said so afterwards and verified with a stand-in. I found it when pytest failed on my machine.
3. **A test it wrote was off by exactly the tolerance.** A ₹1.00 difference is inside the policy tolerance; the test expected a failure. Fixed by changing the case to ₹1.50.
4. **Output limit too small and currency check too strict.** The 2,000-token limit starved reasoning models, and refusing a missing currency broke e-invoice JSON. I only saw it in the second real run.
5. **Inherited a test that asserted the bug.** `test_parse_date_with_slashes` expected 3 March for `03/04/2026`; Claude rewrote it day-first.

## What I deliberately didn't delegate, and why

The rulings on the disputed documents, the replies to stakeholders, deciding what to cut, and judging whether a recommendation is safe to give a CFO.

## Time

~6 hrs.
