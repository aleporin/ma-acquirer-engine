# Evaluation results

## Measured behavior

| Measurement | Result |
| --- | --- |
| Ranking recall@10 | 54/142 (38.03%); global popularity 40.85%, sector popularity 43.66% |
| Lift versus global | −2.82 percentage points; 95% CI −14.79 to +8.45 |
| Lift versus sector | −5.63 points; 95% CI −14.08 to +2.82 |
| Ranking and conviction stability | Identical across five deterministic runs; ten Medium convictions |
| Verifier fixtures | Three valid accepted; six planted-invalid rejected |
| Selected live first pass | 9/10 pages; all parsed numeric claims matched |
| Selected live final | 10/10 pages, 54/54 claims, one successful repair |
| Live time and returned usage | 48.176 seconds, $1.863930; under-$1 goal unmet |
| Replay | 21 recorded responses, 10/10 pages, $0 new spend |
| Independent human/judge calibration | Unmeasured |

The [selected live run](../evals/results/p7-8d5ffa583cd6dd8a84685b443dd19200ba714b25/iteration.md)
was selected after multiple prompt iterations and checked against source evidence.
It is not an unbiased reliability estimate or independent banker validation.
Its [scorecard](../evals/results/p7-8d5ffa583cd6dd8a84685b443dd19200ba714b25/summary.md)
records the intervals; the [sample manifest](../sample_output/manifest.json) binds
output to its archive. GTCR's first draft had an unclaimed prose number; repair
replaced its claim list, so all-attempt and final-page denominators differ.

An earlier sample inverted the target-versus-sector margin comparison. The target
was 16.53%, above the eligible-sector median of 15.7% (Closed-only: 15.3%). The
shipped sample uses corrected fresh output. Tests now catch recognized margin
inversions and exclusive claims based on partial history; these narrow checks
cannot certify arbitrary economic reasoning. Original failures remain archived.

## What the harness checks

| Layer | Check | Limit of a pass |
| --- | --- | --- |
| 0 | Offline unit/property tests and coverage | Full-suite verification is separate from the grader's selected subset |
| 1 | Temporal ranking, baselines, ablations, bootstrap intervals | Measures performance; does not require positive lift |
| 2 | Planted faults and saved-run claims | Numeric/reference consistency, not economic truth |
| 3 | Lexical overlap and, when supplied, identification judgments | Lexical variety alone does not establish buyer specificity |
| 4 | Two rubric judges against blind human votes | Requires actual labels and judgments |
| 5 | Repeated ranks, convictions, and page validity | Replay stability is not fresh-model stability |
| 6 | Usage, latency, recovery, and controlled ablations | Requires controls from the relevant model/prompt cohort |

The [shipping replay scorecard](../evals/results/p7-e9e45db11ab88f824f2ea06a5e5ca4e22663fff4/summary.md)
passes layers 0/1/2/3/5/6; 4 is unmeasured. The selected live scorecard passes
0/1/2/3/5, leaves 4 unmeasured, and fails 6 because current matched controls are
missing, although that run meets the latency goal. Historical controls cannot
supply them. The legacy `not_implemented` status also denotes missing observations
for an implemented grader. It never means a passing result.

## Ranking protocol

Train on 358 transactions through 2021; test on all 142 from 2022–2024. Excluding
Rumored rows leaves 93 training buyers. Seventeen test buyers are absent from that
universe and count as misses for every method. Held-out buyer identities, outcomes,
deal types, and rationale tags do not enter query features.

All methods share candidates and denominators. Report recall@10, full-list MRR,
and nDCG@10 with one relevant buyer per query. Paired bootstrap intervals resample
transactions with a fixed seed, not buyer clusters. Feature ablations renormalize
remaining weights; initial weights and conviction thresholds were not tuned on
these results.

This is retrospective: query EV is the actual transaction EV, final outcomes lack
historical change dates, and synthetic assignments limit external validity.
Completion rates are therefore not a fully point-in-time reconstruction.

## Retrieval and reviewer controls

The [historical matched comparison](../evals/results/p4-2b2d4904ec157d707e4eef0aa04dbbc84ba9b3b8/ablation_summary.json)
uses the same source and prompt cohort across variants:

| Variant | Final pages | Final claims | Seconds | Returned USD |
| --- | --- | --- | --- | --- |
| Tools and reviewer | 10/10 | 66/66 | 177.84 | 1.0890 |
| Tools, no reviewer | 10/10 | 64/64 | 133.59 | 0.9860 |
| No tools | 0/10 | No successful output | 300.03 | 1.2713 |

All tools-disabled drafts and repairs lacked retrieved comps. Terminal outcomes
also include four budget denials and two deadlines; the historical terminal-comp
metric is 0.4, while evidence rejection across attempts is 1.0. An additional
$1.64445 reservation bound is uncertain usage, not recorded billing.

The reviewer changed no pages; its own call cost $0.045584 and took 3.37 seconds.
It is now opt-in. Separate portfolios also vary stochastically, so their elapsed
time difference is not a causal estimate of review overhead. These older controls
do not measure the current writer's quality or reliability.

## Run evaluations

```sh
make test
make lint
make run
# Replace RUN_ID with the path printed above.
make eval RESULTS=/tmp/acquirer-eval EVAL_FLAGS="--analyst-run runs/RUN_ID/run.json"
make eval EVAL_FLAGS=--ci RESULTS=/tmp/acquirer-ci-eval
make eval-diff A=path/to/before/scorecard.json B=path/to/after/scorecard.json
```

These commands make no provider calls. CI runs the full tests, lint, keyless
report replay, and eval layers 0–2. Scorecards record source, dirty state, run ID,
time, configuration digest, and seed under `RESULTS/p7-SOURCE_SHA/`; existing
bundles are not overwritten. An intentional top-ten change requires a `ranking:`
marker in the intervening history. Supply repeated `--analyst-run` paths for
matched ablations, or `--judge-run runs/JUDGE_ID` for saved judgments.

### Independent judging

The [blind packet](../evals/labels/README.md) contains twenty pages from two matched
historical ten-buyer runs. Complete all five dimensions before seeing judge output;
the CLI rejects incomplete, duplicate, and foreign votes. Five isolated rubric
calls and name-masked identification use two model families. The free plan has
360 outcomes and 240 unique requests; its conservative $20.14 maximum-token
estimate exceeds the $10 admission cap, which can stop the run.

```sh
make eval-judges                                       # Free plan
make eval-judges JUDGE_FLAGS=--fresh                    # Paid; completed labels required
make eval-judges JUDGE_FLAGS="--replay-from runs/JUDGE_ID" # Free replay
```

Fresh judging requires `OPENAI_API_KEY` and `GEMINI_API_KEY` in the environment
and clean source. It saves the plan, responses, usage, trace, and summary.
Kappa is per judge against the human, with buyer-cluster bootstrap intervals;
judge-versus-judge agreement is separate. Unknown/failure coverage is reported and
undefined kappa remains null. Twenty pages from one non-banker rater are only a
sanity check. No completed live judge baseline or measured judge-prompt iteration
is present; generation prompt revisions do not substitute for calibration.

### Optional weight experiment

The [frozen protocol](../config/ranking_experiment.yaml) asks for at most three
weight hypotheses from anonymous aggregates through 2018. Compare unchanged
weights with type-only and shrunk buyer-adjusted variants, select chronologically
on 2019/2020/2021, then freeze the winner before measuring 2022–2024. That benchmark
has already been inspected, so results are exploratory. No alternative-weight
performance is measured yet, and this experiment never changes product scoring.

```sh
uv run acquirers propose-weights --fresh                         # Paid; at most $0.50 reserved
uv run acquirers propose-weights --source runs/weight-proposals/ID # Free proposal replay
uv run acquirers experiment-weights runs/weight-proposals/ID       # Free selection and measurement
```

Fresh proposals need the analyst credential, allow zero retries, and record the
aggregate input, hypotheses, usage, and trace. Experiments save all trials,
per-query results, intervals, and provenance; mismatched inputs are rejected.
The implementation is in [`evals/ranking/`](../evals/ranking/).

## Evidence trail

| Milestone | Artifact |
| --- | --- |
| Harness before product behavior | [p0](../evals/results/p0-0a5d7e445c86fad65ac98742c7801a46bffe1c7b/summary.md) |
| Ranking and baselines | [p1](../evals/results/p1-675f60ac7c8dc2f6a41d8d83233cf0cb2ca7ade3/summary.md) |
| Planted verification faults | [p2](../evals/results/p2-036c180fd1f7575eb1739994a2e63f3b039be266/summary.md) |
| Initial live draft timeouts | [p3](../evals/results/p3-19f341aed6cdbf7125ab7bea09711ed19b9b555e/summary.md) |
| Repair and controlled ablations | [p4](../evals/results/p4-7213c62852810996a2b9a759e16418f65cebdb2c/summary.md) |
| Calibration preparation | [p5](../evals/results/p5-35f1652a84f5bbccaa4e81a5b029b184b3b9d36f/summary.md) |
| Portable keyless report | [p6](../evals/results/p6-2a4312258da10eddc14b4f30e1f9ff3997055080/summary.md) |
| Corrected live sample | [result](../evals/results/p7-8d5ffa583cd6dd8a84685b443dd19200ba714b25/iteration.md) |
| Latest runtime verification | [369 tests and checks](../evals/results/p7-2e72b99681eae5b83c590fad7d11893495cd6830/weight-experiment-checks.json), [replay parity](../evals/results/p7-2e72b99681eae5b83c590fad7d11893495cd6830/replay-parity.json) |

Full observations remain under [evals/results/](../evals/results/). The optional
[replay recording](demo/replay.webm) and [manifest](demo/manifest.json) show the
saved report; the video measures replay speed, not live generation.

<details>
<summary>Historical revision aliases</summary>

Saved artifacts retain their original source identities. The following aliases
point to reachable commits with identical code trees, author identities, dates,
and ordering. The measurements and archive contents were not changed.

| Recorded revision | Equivalent revision |
| --- | --- |
| `a1220e95bc4ea6f7057962def962e4db336af13e` | `b288157afedd27cf66da62477a729db9bb75ff21` |
| `c26fee0676e02661eaefcdea587d732a97e25d1e` | `655a4d4fbd605b0ba6c0e34c3f9777c7cd858514` |
| `d9dec9fb67602f81d078bbf3dc341b8eac6916ed` | `9ee0a59ef50df9bf5ac3353d6171c75b6f104887` |
| `737c5ee704e45dac7fc0522821b32943c09f0fd6` | `e25737fa3f0cecd98862a268b95ea6cac28c20c1` |
| `50e42daa4e66473bdb00137a1a8320b9eb26e792` | `a74442dda2ea6e399a1adc09e88b8610e2d8acd4` |
| `25495b85d8bf46e4bcf67023a0518c8c7f9ef31a` | `7c3e0978de787d13f98e70ba53b0ac59e57c9a70` |
| `7ff5a4faf59354d163d0ef767aed0921c943c2f9` | `0a12ad0a390f51bdad331b238c0b3f7ddbb4a8bd` |
| `2d06b0c37e7b66337251a9dd898e805bf7429fe8` | `efefa99b57dee3902d508a8f3b9d7b95033502a2` |
| `8e28510a530e2d73385710cd7c4b7166c6cb4771` | `8191ab43993819b3a4b53163f68d09e3adb1b224` |
| `ce092491c0aef5d0b7a74065242efabf7cecd8c8` | `0ef86ab919c50666f967c52dcfdc8e042ad1f51e` |
| `0e6733aa3b1b0e7f2249c4fbc0a3ad1ba36565ed` | `5a64a0a26d7125be002307b873d45a486b893bc5` |
| `3b14b14443b23beff32d9c6f9e61a6294a14ef98` | `8f8ed2f593ca254aeaf9d09885af5b1e417e1bef` |
| `abf86a14b9a47e40601a109a8d8f5110d37ccaf3` | `02e01d47f56f30986794a6388ff530b64ac24e0c` |
| `a32c126c5c11ce24232f75e18fd3309f80098e88` | `832c20277260c8daf097bd3736ac5a4e99ec4a82` |
| `374548daee390b7596da2fed9a667e717fff0bf2` | `6f80d578b945d95613ae149f160d8343d21cfdcb` |
| `1914a4edfa644b6e67a403bd838d2c0607202098` | `2a4a05e30a170d2df7257206da97294186cb4fd5` |
| `8e2816c6cf02824ecbb545ee2e8d8c1031b25862` | `42b66ffded7a51f97b371ff8685036b91d2350e7` |
| `64585e3024dc4e9c05afa7b2bd4a56d5821c52c1` | `178815d9fef366d2f593515a5a07a5825ab0c722` |
| `81a8a9d1f82bd6e6e0e3e7d7b527cf3d68932827` | `935f7c99b818e8d1bbd3de7dd407121fdb4902e4` |
| `2aa31341fc052d26879060279395cc80988f4a62` | `500879dda420ab0a021288268135829f13fcd173` |
| `3303b53205cc277247f0fc75fd04a6ffce962c0c` | `9bd02fe46c9a388d49c964a7e57a2ccf9dd249dc` |
| `35f1652a84f5bbccaa4e81a5b029b184b3b9d36f` | `880ac20ba81850ace8e0df5e73dc566968a3d161` |
| `0de3da91bd9b7efa30ae33196e92601ea3d87e78` | `726511e7422002f4a0e45f587f39121a47c6814a` |
| `cdffd5d5f5428c91c9fb59041dafbac9710e774e` | `19df2b03d4cd9715fdf18d5bda813a2c8fa14bca` |
| `f757d631defc965360742708345afdcbe807ccea` | `17f9c478532929c48ab26334cab1dff6532f5e60` |
| `4da0ba3d8d1a1b3109bf2f9a623846a7fd3c07cf` | `c7013e9a011c2afdd083e7b81f3b2daa70aee33e` |
| `654221908e27c971d0f462854169346d5d4cd41a` | `f941ead93f0a03c8e0335db02a0536294e91ed9e` |
| `e55bdabd62cbef1c0b9f6dd156fe9ae2c64e84a3` | `36032972420d4b9c9446beaef8770fe360c3b3ee` |
| `b690016c5da6be865f3aa70a58b8e7ae7f433e06` | `0c74fe55ec25ec6890d6e2905c37b0d3e451a880` |
| `820f16fe6b15fc0d6c28e31770c3085bcd3e4aad` | `bfa7527bf4d7a2424ce50227a1eab2de99bf55bc` |
| `e04224a08b1a60cf4bf63061c6bd249d5086d3d0` | `3bdce6118065f20ec4a11b9df8f05e0693d7c9a4` |
| `20c8f4811f4258fd8e01d7ccb4045014d48448e0` | `e2b9239bc77ae55d67f7cccc65582e8e0eabd72e` |
| `1df1f9c79ad8c5ef7cd3f88fae13baeae91320dd` | `07c6ec8a5fd08fbea3f72548fc4742a1f77b0e96` |
| `d6e497afcb5d6e6ce25a05ef4c698631041c650c` | `1437aa0f00f99bc585d0dddd7ebdc2c3ffb92a4c` |
| `538de75678658857e95246b0651d845cac9c3e25` | `4fbc795058fe272f0d5c89f6c50dae7815462265` |
| `3417cdb7cb8d73f3633e62cac3b602805a23ac39` | `2d0651aa7fadc17fdb587d2531fbf379adc85eb1` |
| `1fe4216e5aa4b136d93ff9b54aa42cf17f55ab03` | `ec0757921eb4e13667925be40b6c8f389a556797` |
| `10423ed34a23ce11bebdcd685f02cdce1807ecbb` | `5fbd6389f7db1b9b137e0d2d0967da405af5f543` |
| `ae93e0a06c634a0e4c5809d3689ff5e4ad290be3` | `1409ffb6c6315a01d6f8eeab95fc935f77857be0` |
| `0e034a2b0f1cdb1a0b192c15fbfe59735a8498d6` | `574fd1bdb930699a86c5d66f4317255c4c521237` |
| `6c08395b3bfcbb10fe94f7456cf82582c9cca5db` | `1d132d0afeba03863c0775696c52781608bb17cb` |
| `b26cae145d78a7072d32be5495e2c4632446f884` | `9668dc2fdaa8f7a87a17ae4be571aae2dd3dd5c1` |
| `2a4312258da10eddc14b4f30e1f9ff3997055080` | `882f2871cbc293fa282aee735a8d14b36f7239e2` |
| `13f89a3dc0985dd239238aea96b7d407a7b8a0d9` | `9965b31da170618ba1e7ea7735f051bc761abd5e` |
| `a2f7ef8718fa7b22e05b423fbd216fa4789b4c87` | `64bc04b2dac3f8ef30564fd9b608845a3598ffb2` |
| `a0b8c4b5f192894cccb84d3c1310012e4e67ad00` | `9127b41c6e71b4bd4720504dc36ba614db9efeed` |
| `0511c5a87f7fad22c12932a8a99b31d250327e0a` | `44f1d4beda68aaa6978373a8aec2cb5486aa6edf` |
| `46c8a6f622f2848ed58d75f12153a8156218c316` | `2c4bf6d5b1a0167c80b1c912b8c2be39bedfb4a1` |

</details>
