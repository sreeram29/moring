# Reflection

## What I learned

1. A model can work in a demo but return an empty reply in the application. In my case, the thinking model used its token limit before producing the answer.
2. A cost calculation can be wrong by 1,000 times and still look believable. I treated a per-1,000 price as a per-million price.
3. The written policy can approve documents that should be checked. disp_05 has a wrong line amount, and disp_06 has a future invoice date.

## Decision I am least sure about

I am least sure about choosing the cheaper model for the final 24-document run based on a single run. A larger hand-checked sample could show missed reviews. I would also reconsider if repeated runs produce large differences.

## What I would do with one more week

1. Run and hand-check the 200-document October sample.
2. Add evidence offsets and build the reviewer UI.
3. Add stronger-model escalation after validation failure and provider fallback.
4. Add authentication.
5. Measure whether the second pass improves results enough to justify its cost.
