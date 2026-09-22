# Evaluation evidence

The report is reproducible; independent banker-quality calibration is unfinished.
Read statuses with their measurements: a completed measurement is not always a
passed product target, and an offline replay is not a new live generation.

## Current observations

| Boundary | Measured result | Meaning |
| --- | --- | --- |
| Ranking holdout | 54/142 buyers in the top ten (38.03%) | Below global popularity (40.85%) and sector popularity (43.66%) |
| Recall lift vs global | −2.82 percentage points; 95% CI −14.79 to +8.45 | No demonstrated improvement |
| Recall lift vs sector | −5.63 points; 95% CI −14.08 to +2.82 | No demonstrated improvement |
| Ranking identity | 100% across five deterministic runs | Same data/config gives the same ranks |
| Conviction | Ten Medium; 100% repeated agreement | Honest fixed thresholds, no forced diversity |
| Verifier fixtures | Three valid accepted; all six planted-invalid rejected | Known numeric/reference faults are caught |
| Latest live first pass | 7/10 pages; 76/79 parsed numeric claims | Three pages needed repair |
| Latest live final | 10/10 pages; 79/79 claims | Each failed first draft passed a repair |
| Latest live operations | 72.645 seconds; $1.022239 returned usage | 60-second and under-$1 goals remain unmet |
| Replay | 27 responses; 10/10 pages; $0 new spend | Reproduces saved responses through current validation |
| Human/judge agreement | Unmeasured | No kappa, identification, or quality improvement is claimed |

The live observation is
[recorded here](../evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/fresh_verification.json).
The [shipping replay scorecard](../evals/results/p7-274fd86d73929cfd9da62a1f392e91d75d894a21/summary.md)
contains the ranking intervals and mode-prefixed metrics.
Request p95 in the latest live run was 29.864 seconds; provider p95 was 29.769.
Neither is end-to-end p95 across repeated fresh portfolios.

One qualitative error is visible in the bundled Francisco Partners thesis: it
describes the target margin as below the sector median. The target is 16.53%;
the eligible-sector median is 15.7% (Closed-only median: 15.3%). Numeric claim
validation did not catch this number-free comparison. The archived output is
preserved unchanged, and this is an unresolved quality defect, not a verified
economic conclusion. A new prompt or validator needs a measured follow-up.

## Seven layers and what a pass proves

| Layer | Check | Proof boundary |
| --- | --- | --- |
| 0 | Isolated unit/property tests and measured coverage | The selected offline test subset passed; full-suite evidence is separate |
| 1 | Temporal ranking backtest, baselines, ablations, bootstrap intervals | Measurement completed; positive lift is not required to preserve an honest result |
| 2 | Planted fixtures and supplied saved-run claims | Numeric/reference consistency; not the truth of an investment thesis |
| 3 | Pairwise lexical similarity; identification when a judge archive exists | Lexical variety alone does not establish buyer specificity |
| 4 | Two independent rubric judges against blind human votes | Unmeasured until the required corpus and judgments exist |
| 5 | Ranking/conviction identity and repeated page validity | Replaying one response stream is not fresh-model stochastic stability |
| 6 | Cost, latency, tool usage, and controlled ablation outcomes | Routing evidence is distinct from the inherited live speed goal |

The legacy status `not_implemented` also represents a missing observation for
an implemented grader. It is not zero quality, and it must not be reported as a pass.
Phase 4's operational status reflects its recovery/ablation gate; the separate
`live_phase3_latency_gate_met` metric retains the failed speed target.

## Ranking protocol

Train on 358 source transactions through 2021; evaluate all 142 from 2022–2024.
Exclude rumored rows before fitting priors, sector adjacency, tags, and candidate
identities. There are 93 eligible training buyers; 17 test labels are absent from
that universe and remain misses for every method.

A query uses target sector, EV, margin, geography, and prior ownership, never the
held-out acquirer, outcome, deal type, or post-deal rationale tags. Actual transaction
EV still makes this retrospective. Synthetic assignment limits external validity.

Recall@10, full-list MRR, and nDCG@10 use one relevant buyer per query. All methods
share the same candidates and denominator. Paired bootstrap intervals resample
transactions with a fixed seed; they are not clustered by buyer. Feature-group
ablations renormalize the remaining weights. Initial ranking weights and conviction
thresholds were not tuned against these results.

## Controlled agent evidence

The [matched three-way comparison](../evals/results/p4-2b2d4904ec157d707e4eef0aa04dbbc84ba9b3b8/ablation_summary.json)
uses the same original source and prompt cohort:

| Variant | Final pages | Final claims | Seconds | Returned USD |
| --- | --- | --- | --- | --- |
| Tools and reviewer | 10/10 | 66/66 | 177.84 | 1.0890 |
| Tools, reviewer disabled | 10/10 | 64/64 | 133.59 | 0.9860 |
| Tools disabled | 0/10 | No successful output | 300.03 | 1.2713 |

Every tools-disabled draft and repair was rejected for missing retrieved comps.
Its terminal outcomes also include four budget denials and two deadlines; these
resource failures remain visible rather than being relabeled as evidence errors.
The original terminal-comp metric is 0.4; across-attempt evidence rejection is 1.0.

The reviewer changed no pages in its paired observation. Its own cost was $0.045584
and latency 3.37 seconds, so it is opt-in. Separate generated portfolios also differ
stochastically; their timing difference is not a causal reviewer-overhead estimate.
The newer 72.645-second run is a separate observation, not a matched optimization study.

## Reproduce measurements without provider calls

~~~sh
make test
make lint
make run
# Use the new run.json path printed above.
make eval RESULTS=/tmp/acquirer-final-eval EVAL_FLAGS="--analyst-run runs/RUN_ID/run.json"
make eval EVAL_FLAGS=--ci RESULTS=/tmp/acquirer-ci-eval
make eval-diff A=path/to/before/scorecard.json B=path/to/after/scorecard.json
~~~

Results are written to `RESULTS/p7-SOURCE_SHA/`. Existing bundles are never
overwritten. The scorecard records source SHA, dirty state, run ID, UTC timestamp,
configuration digest, and seed. A separate artifact commit retains clean-source
measurements. Historical source IDs remain unchanged; [revision aliases](REVISIONS.md)
identify equivalent reachable code trees where needed.

CI selects layers 0–2, runs the full tests separately, and also exercises keyless
report replay. It makes no provider calls. An intentional change in the top-ten
identity requires a `ranking:` marker in the intervening history.

## Calibration still to complete

The [blind packet](../evals/labels/README.md) has twenty pages: two runs of ten
buyers. These are evaluation examples, not twenty buyers in the product report.
A person must rate all five dimensions before seeing judge output. The CLI rejects
blank, duplicate, or foreign rows. It never fills missing votes.

[Judge execution](../JUDGING.md) isolates five rubric questions and name-masked
identification for two provider families. The current free plan has 360 outcomes
and 240 unique requests. Its conservative maximum-token estimate is $20.14;
the configured $10 admission cap may stop it before completion.

Kappa is computed per judge against the human, with buyer-cluster bootstrap
intervals. Judge-versus-judge agreement is separate. Unknown and failed requests
are not fabricated binary votes; undefined kappa stays null.
Twenty pages from one non-banker rater are a sanity check, not a validated benchmark.

No completed live judge baseline or measured judge-prompt iteration is present.
Generation prompts did change from v1 through v4 and their failures are preserved,
but that is not a substitute for the pending calibration experiment.

## Iteration trail

| Milestone | Artifact | What changed |
| --- | --- | --- |
| Harness first | [p0](../evals/results/p0-0a5d7e445c86fad65ac98742c7801a46bffe1c7b/summary.md) | Honest unmeasured layers before product behavior |
| Ranking | [p1](../evals/results/p1-675f60ac7c8dc2f6a41d8d83233cf0cb2ca7ade3/summary.md) | Temporal holdout, baselines, uncertainty |
| Verification | [p2](../evals/results/p2-036c180fd1f7575eb1739994a2e63f3b039be266/summary.md) | Positive and planted-negative fixtures |
| First live failure | [p3](../evals/results/p3-19f341aed6cdbf7125ab7bea09711ed19b9b555e/summary.md) | Ten draft timeouts were retained |
| Concise generation | [v4](../evals/results/p3-50493691575df8de6a7f75de41c891ae5c0f4340/summary.md) | Seven first-pass verified pages |
| Recovery and controls | [p4](../evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/summary.md) | Complete output, repair, ablations, separate speed failure |
| Calibration preparation | [p5](../evals/results/p5-35f1652a84f5bbccaa4e81a5b029b184b3b9d36f/summary.md) | Frozen cases and blind labels; quality unmeasured |
| Portable report | [p6](../evals/results/p6-2a4312258da10eddc14b4f30e1f9ff3997055080/summary.md) | Complete keyless replay from a clean clone |
| Shipping verification | [p7](../evals/results/p7-274fd86d73929cfd9da62a1f392e91d75d894a21/summary.md) | 310 tests and keyless replay; independent calibration still unmeasured |

Earlier unsuccessful runs remain under [evals/results](../evals/results/).
