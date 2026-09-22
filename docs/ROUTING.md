# Routing, repair, and replay

## Current generation policy

The execution loop is in [`stages/draft.py`](../src/acquirer_engine/stages/draft.py):
`draft_pages` schedules buyers; `draft_one`, `generate`, `next_route`, and
`repair_history` drive each page. Optional portfolio review is in
[`stages/review.py`](../src/acquirer_engine/stages/review.py).
[`factory.py`](../src/acquirer_engine/factory.py) constructs shared services once;
the pipeline binds them into required `RuntimeDeps` before these stages run.

The analyst now uses the stronger Opus 5 model previously reserved for escalation,
as configured in `config/models.yaml`. Escalation is disabled because there is no
stronger configured tier. The current route is
`analyst -> same-tier repair -> unverified banner`, with success ending recovery
immediately. Although `max_repairs` is two, the existing router permits only the
first repair when escalation is disabled; the second recovery step belongs to the
optional escalation route. Reviewer execution remains opt-in.

Schema and evidence errors return to the analyst with the rejected draft and its
existing evidence history. Timeouts, exhausted rate-limit retries, missing replay
responses, and resource limits terminate the page without validation repair.
The quality-correction runs use an approved $10 admission cap. This permits
concurrent worst-case reservations; it is neither expected billing nor a revision
to the under-$1 measured-cost goal. The end-to-end speed target remains 60 seconds. The output-token ceiling is now
6,000, leaving headroom after a stronger-model draft reached the earlier limit.

Two earlier stronger-model observations illustrate the quality/cost tradeoff:

| Prompt | Seconds | Returned USD | Factual read-through |
| --- | --- | --- | --- |
| [v6](../evals/results/p7-f12ac9adc5c49079dd40c1b402aabad0b6a55c40/iteration.md) | 44.823 | 1.914185 | Rejected unsupported qualitative claims |
| [v7](../evals/results/p7-0a63cfe438c161aef46b0502ca13c941ec1779e2/iteration.md) | 50.613 | 1.940530 | Rejected remaining factual phrases |

Both completed ten pages through numeric/schema validation and met the speed
target in that observation, but neither qualified as a shipping sample. They
exceeded the cost goal.

The [selected v13 observation](../evals/results/p7-8d5ffa583cd6dd8a84685b443dd19200ba714b25/iteration.md)
produced 10/10 final pages and 54/54 matched numeric claims in 48.176 seconds for
$1.863930, across 21 responses. Nine pages passed first try; GTCR passed one
numeric repair. A source-based read-through found no concrete factual
contradiction in the ten public pages or their internal summaries. That is
development QA, not independent banker calibration or proof of future quality.
Selection followed multiple iterations, so this is not an unbiased estimate of
first-run reliability. The run met the speed goal; the under-$1 goal remains unmet.

The current validation includes narrow guards for recognized target-versus-Closed-
sector median margin inversions and target-theme exclusivity asserted from partial
buyer history. The latter checks recognized “only through/in/on” phrasing and asks
for positive examples instead. Complete coverage removes that scope restriction;
it does not prove an exclusive claim true. These guards do not provide general
semantic verification.

The selected run is `fd394967475d4b19905d473fe26b903f`, measured at clean source
`8d5ffa583cd6dd8a84685b443dd19200ba714b25`. Its live layer 6 remains failed because
the new model/prompt cohort lacks matched tools/reviewer controls, even though its
latency metric passes. Historical controls do not supply those missing variants;
independent quality calibration remains unmeasured.

## Historical routing evidence

The [Phase 4 exit scorecard](../evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/summary.md)
passes the routing gate on the original matched ablation cohort. A
[separate historical verification](../evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/fresh_verification.json)
recorded 10/10 pages, 79/79 final claims, 72.645s, and $1.022239 under the
then-current admission configuration. Its 27 responses and outcomes replayed
exactly. It missed the 60-second goal. The
[original comparison](../evals/results/p4-2b2d4904ec157d707e4eef0aa04dbbc84ba9b3b8/ablation_summary.json)
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
termination rates remain visible; a denial without evidence rejection cannot pass.
The tools-off run has an additional $1.64445 uncertain reservation bound, not
recorded billing.

Reviewer-disabled replay reproduced all 27 responses and identical page outcomes
for $0. Corrected tools-disabled replay recovers all 24 responses, all page and
attempt outcomes, and the reviewer failure exactly. It uses explicit archived
failure evidence and creates no missing model answers. These completed historical
ablations do not constitute current-cohort controls.

## Shared execution and replay boundaries

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

For a new three-way comparison, explicitly run reviewer-enabled, reviewer-disabled,
and tools-disabled variants under one frozen configuration. Current defaults do
not reproduce the original model/prompt cohort.
Each snapshot freezes all prompt text and ablation settings. Historical replay
never consults current prompts or starts a provider client. It runs current
validation against the original responses. A missing response is an explicit
archive failure unless explicit typed or legacy validation/reviewer evidence
records its failure. Replay restores that error without inventing a response.

Supply the three saved `run.json` paths as repeated `--analyst-run` arguments to
`acquirers eval`. The scorecard keeps intentional ablation failures outside the
full pipeline cohort and records reviewer flag rate, escalation rate, and paired
lexical overlap before/after review. Rubric quality and human calibration remain
unmeasured without the required independent judgments; lexical overlap alone is
not a banker's quality judgment. Do not treat an offline fixture pass as a live gate pass.

In the separate historical 72.645-second run, the 4,000-token output cap completed
all responses, peaking at 2,529 tokens.
All 27 input estimates used provider token counts. Request p95 was 29.864s,
provider p95 29.769s, counting p95 0.206s, and budget-wait p95 0.014ms.
No request failed or incurred uncertain usage. Seven first-pass pages became
ten after three repairs; explicit claims improved from 76/79 to 79/79.
These figures describe that historical observation, not a causal timing study or
a reliability estimate for the current writer. That run used the then-approved
$3 admission cap; the current cap is $10, with the same distinction between
reservation limits and measured returned usage.
