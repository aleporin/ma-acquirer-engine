# Routing, repair, and replay

The [exit scorecard](evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/summary.md)
passes the Phase 4 routing gate on the original matched ablation cohort. A
[separate fresh verification](evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/fresh_verification.json)
checks the new admission configuration: 10/10 pages, 79/79 final claims, 72.645s, $1.022239.
Its 27 responses and all outcomes replay exactly. The 60s target remains unmet. The
[original comparison](evals/results/p4-2b2d4904ec157d707e4eef0aa04dbbc84ba9b3b8/ablation_summary.json)
records all variants at identical source, data, and prompt-file versions:

| Variant | Verified pages | Final matched claims | Seconds | Recorded USD |
| --- | --- | --- | --- | --- |
| Full pipeline | 10/10 | 66/66 | 177.84 | 1.0890 |
| Reviewer disabled | 10/10 | 64/64 | 133.59 | 0.9860 |
| Tools disabled | 0/10 | Not a successful output | 300.03 | 1.2713 |

The full run needed three repairs; reviewer-disabled needed two. The reviewer
changed no pages, so its paired lexical-overlap effect was zero. It cost $0.045584
and took 3.37 seconds. Separate-run timing differences also reflect generation
variation; they are not a causal estimate of review overhead or quality.
**Decision: cut review from the default path.** Set `reviewer_enabled: true` in
`config/analyst.yaml` to opt in. Its tested implementation remains for later quality
calibration; one observation does not establish that review never helps.

With tools disabled, all ten drafts and all ten repairs were rejected for missing
retrieved comps. Final errors were four comp rejections, four budget denials, and
two run deadlines. The historical terminal-comp metric remains 0.4. The corrected
gate separately measures evidence rejection across attempts: all ten were
rejected for missing retrieved comps and none succeeded. Budget/deadline
termination rates remain visible; a denial without evidence rejection cannot pass. The tools-off
run has an additional $1.64445 uncertain reservation bound, not recorded billing.

Reviewer-disabled replay reproduced all 27 responses and identical page outcomes
for $0. Corrected tools-disabled replay recovers all 24 responses, all page and
attempt outcomes, and the reviewer failure exactly. It uses explicit archived
failure evidence and creates no missing model answers. The 60-second target
remains unmet. Both paid ablations are complete.

A page follows `analyst -> repair -> escalation -> unverified banner` when each
validation attempt fails. Success ends recovery immediately. Schema and evidence
errors are fed back with the rejected draft and its existing evidence history.
Timeouts, exhausted rate-limit retries, missing replay responses, and resource
limits terminate the page. They do not trigger validation repairs.

The sparse prompt is selected from the ranker's full relevant-deal count, not
from the number of rows that fit into the core pack. Its threshold is configured.
The analyst still has to retrieve valuation comps; thin evidence does not relax
validation. Turning tools off is an explicit negative control.

When enabled, one portfolio review reads all page outcomes, including failures. Every buyer
must receive exactly one approve/revise verdict. Revisions need specific feedback.
Each flagged page gets one revision, using its original evidence and conversation,
followed by the same validation. A failed revision retains a banner. Original
pages remain in `before_review`; the reviewer cannot change ranks or conviction.
Reviewer errors remain in `review.errors` and make the command exit nonzero.

All provider models share one client, recording boundary, ledger, cache, and
spending guard. Each live request counts input tokens through the injected
model, adds the configured safety allowance, then reserves the full output-token
cap at maximum configured prices for all possible SDK attempts. Counting is
[free](https://platform.claude.com/docs/en/build-with-claude/token-counting), but
approximate; unsupported or failed counting falls back to serialized text bytes. Concurrent requests wait
for outstanding reservations to settle instead of spending the same budget twice.
The USD cap can stop a request even when its eventual actual cost might fit.
Returned usage replaces the reservation; missing usage retains an explicitly
uncertain cost bound. This is admission control, not an invoice guarantee.

The overall deadline includes reservation waits and provider execution. Tool
rounds are counted across initial drafting, recovery, and reviewer revision.
The ledger records model, stage, buyer, request number, real token usage, and
cost. New calls separate token-counting time, budget admission wait, and provider
time. Older total request durations are never relabeled as provider time.
First-pass, post-repair, and post-review claim rates remain separate.

Run these only when provider spending is intended:

```sh
make run RUN_FLAGS=--fresh
make run RUN_FLAGS='--fresh --no-reviewer'  # also bypasses an enabled reviewer
make run RUN_FLAGS='--fresh --no-tools'
```

To repeat the original three-way comparison, first enable review in configuration.
Each snapshot freezes all prompt text and ablation settings. Historical replay
never consults current prompts or starts a provider client. It runs current
validation against the original responses. A missing response is an explicit
archive failure unless explicit typed or legacy validation/reviewer evidence
records its failure. Replay restores that error without inventing a response.

Supply the three saved `run.json` paths as repeated `--analyst-run` arguments to
`acquirers eval`. The scorecard keeps intentional ablation failures outside the
full pipeline cohort and records reviewer flag rate, escalation rate, and paired
lexical overlap before/after review. Rubric quality and human calibration remain
unmeasured until their later evaluation phase; lexical overlap alone is not a
banker's quality judgment. Do not treat an offline fixture pass as a live gate pass.

The 4,000-token output cap completed all new responses, peaking at 2,529 tokens.
All 27 input estimates used provider token counts. Request p95 was 29.864s,
provider p95 29.769s, counting p95 0.206s, and budget-wait p95 0.014ms.
No request failed or incurred uncertain usage. Seven first-pass pages became
ten after three repairs; explicit claims improved from 76/79 to 79/79.
This is one fresh observation, not a causal timing study or reliability estimate.
The $3 cap, SDK retry allowance, and validation rules remain.
