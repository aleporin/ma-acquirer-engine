# Routing, repair, and replay

Phase 4 adds bounded recovery and portfolio review. Its live exit is unmeasured
until a fresh full run and both ablations are recorded. The latest historical
live baseline remains seven verified pages out of ten; it predates these routes.

A page follows `analyst -> repair -> escalation -> unverified banner` when each
validation attempt fails. Success ends recovery immediately. Schema and evidence
errors are fed back with the rejected draft and its existing evidence history.
Timeouts, exhausted rate-limit retries, missing replay responses, and resource
limits terminate the page. They do not trigger validation repairs.

The sparse prompt is selected from the ranker's full relevant-deal count, not
from the number of rows that fit into the core pack. Its threshold is configured.
The analyst still has to retrieve valuation comps; thin evidence does not relax
validation. Turning tools off is an explicit negative control.

One portfolio review reads all page outcomes, including failures. Every buyer
must receive exactly one approve/revise verdict. Revisions need specific feedback.
Each flagged page gets one revision, using its original evidence and conversation,
followed by the same validation. A failed revision retains a banner. Original
pages remain in `before_review`; the reviewer cannot change ranks or conviction.
Reviewer errors remain in `review.errors` and make the command exit nonzero.

All provider models share one client, recording boundary, ledger, cache, and
spending guard. Each request reserves a conservative cost estimate using serialized
text bytes, the configured protocol allowance, its actual output-token cap,
maximum configured prices, and possible SDK retries. Concurrent requests wait
for outstanding reservations to settle instead of spending the same budget twice.
The USD cap can stop a request even when its eventual actual cost might fit.
Returned usage replaces the reservation; missing usage retains an explicitly
uncertain cost bound. This is admission control, not an invoice guarantee.

The overall deadline includes reservation waits and provider execution. Tool
rounds are counted across initial drafting, recovery, and reviewer revision.
The ledger records model, stage, buyer, request number, real token usage, and
cost. First-pass, post-repair, and post-review claim rates remain separate.

Run these only when provider spending is intended:

```sh
make run RUN_FLAGS=--fresh
make run RUN_FLAGS='--fresh --no-reviewer'
make run RUN_FLAGS='--fresh --no-tools'
```

Each snapshot freezes all prompt text and ablation settings. Historical replay
never consults current prompts or starts a provider client. It runs current
validation against the original responses. A missing response is an explicit
archive failure; replay does not invent the result of a timed-out request.

Supply the three saved `run.json` paths as repeated `--analyst-run` arguments to
`acquirers eval`. The scorecard keeps intentional ablation failures outside the
full pipeline cohort and records reviewer flag rate, escalation rate, and paired
lexical overlap before/after review. Rubric quality and human calibration remain
unmeasured until their later evaluation phase; lexical overlap alone is not a
banker's quality judgment. Do not treat an offline fixture pass as a live gate pass.
