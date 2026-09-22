# Judges and calibration

Phase 5 evaluates saved rationale pages. It does not generate another portfolio.
The offline implementation and blind packet are available; live judge quality,
human agreement, and prompt improvement remain unmeasured.

## Execution flow

Follow one path through the code:

1. `prepare-judges` enters `evals/judges/command.py` and calls `prepare.py`, which
   checks original generation archives, resolves evidence from frozen inputs,
   and requires a matched cohort. `cases.py` seals and masks the corpus.
2. `labels.py` exports a shuffled packet and validates complete human votes.
   Source run, reviewer setting, generation prompt, and judge outputs are hidden.
3. `eval-judges` calls `command.py`. `plan.py` freezes exact prompts, source
   lineage, candidate order, model prices, output schemas, and human labels.
   Labels and expected identification answers never enter provider requests.
4. `command.py` creates each provider once. `runtime.py` schedules isolated
   judgments through `recording.py`, sharing a budget, cache, trace, and ledger
   through `JudgeDeps`. Failed requests do not become valid Unknown votes.
5. `reporting.py` computes rates and reviewer comparisons; `calibration.py`
   computes kappa and buyer-cluster bootstrap intervals. `evals/judges/grading.py`
   adds those saved observations to offline scorecards.

Typed cases, verdicts, and execution outcomes live in `schema.py`; frozen job
plans live in `plan.py`. Runtime policy lives in `config/judges.yaml`. These modules
belong to evaluation, not generation. The product stages have their own entry
map in [EXECUTION.md](EXECUTION.md).

## Blind labeling

Start with [the reading packet](../evals/labels/README.md) and its labeling guide.
Fill [human_labels.csv](../evals/labels/human_labels.csv) with Pass, Fail, or Unknown
for all five dimensions on all twenty pages. Do this before seeing judge output.
The runner refuses incomplete, duplicate, or foreign rows.

The cohort uses two complete ten-buyer runs from the same generation revision:
one with portfolio review and one without it. Ten paired pre-review pages are
also preserved for measurement, but do not require additional human labels.
These historical pages are distinct from the newer default-generation latency
measurement in ROUTING.md. They are not evidence of current generation speed.

To prepare a new corpus in a checkout without an existing packet:

```sh
uv run acquirers prepare-judges --analyst-run runs/FULL_ID \
  --analyst-run runs/REVIEWER_DISABLED_ID
```

Preparation never overwrites human work. The corpus digest binds page text,
evidence, candidate summaries, source identity, and the shuffle seed.

## Plan, execute, replay

```sh
make eval-judges
make eval-judges JUDGE_FLAGS=--fresh
make eval-judges JUDGE_FLAGS="--replay-from runs/JUDGE_ID"
make eval EVAL_FLAGS="--judge-run runs/JUDGE_ID"
```

The default command prints a free cost plan and never constructs clients.
`--fresh` spends credit, requires completed labels, clean source, and environment
variables `OPENAI_API_KEY` and `GEMINI_API_KEY`. It does not read dotenv files.
Replay needs neither keys nor current prompts. Supply saved analyst observations
as additional `--analyst-run runs/ID/run.json` flags to retain other measured layers.

Each page has five separate rubric calls plus name-masked identification, for
each of two independent model families. Candidate order is shuffled with a
recorded seed; transaction IDs and name-bearing statistic IDs are removed from
identification prose. Rubric calls receive only their own criterion, page,
target, and evidence. Dataset content is delimited as untrusted data.

Content-identical before/after inputs share a cached response within the run,
including the same candidate order. This prevents judge randomness from creating
an apparent reviewer effect on unchanged pages. The current corpus has 360 job
outcomes and 240 distinct requests. Versioned prompts and settings enter cache
identity; a fresh run creates a new cache instead of reusing old judge decisions.

The offline byte-based admission estimate is deliberately conservative; it is
not a billing prediction. The configured judge-run cap is $10, independent of
the generation cap. Every request reserves its maximum estimated charge before
admission, then settles returned usage. Missing usage retains an uncertain
reservation. A cap can stop work; it cannot guarantee all jobs finish.

## Reading results

`runs/JUDGE_ID/` holds `plan.json`, `run.json`, `summary.json`, `trace.jsonl`,
`log.jsonl`, and `responses/`. Raw responses are stored before verdict validation;
invalid schemas, truncation, provider errors, and out-of-range choices are
failures. There is one model request per job and no validation retry. Replays
preserve explicit no-response failures and revalidate available responses.
All replay usage has zero new cost; original token counts remain available.

The summary reports each rubric dimension by reviewer cohort, identification
accuracy, page lengths, failed-request counts, and paired reviewer changes.
Accuracy uses every requested identification as its denominator, including
abstentions and failed requests. Rubric pass rates exclude Unknown and failures,
with their counts shown separately. Paired reviewer changes count only answered
binary pairs. Comparisons of separate generated portfolios are descriptive,
not randomized causal estimates.

Kappa against the human labels is reported per judge and per dimension, with
pooled agreement across dimensions also shown. Judge-versus-judge agreement is
separate. Unknown pairs are excluded from kappa, and comparison coverage is
reported. Confidence intervals resample whole buyers with a fixed seed, keeping
the same buyer's pages and dimensions together. Undefined kappa and intervals
remain null; the valid bootstrap sample count is reported.

Twenty pages from one non-banker rater are a sanity check, not a validated
banking-quality benchmark. A later production evaluation would start with
multiple domain raters and measure their agreement. Prompt changes on this same
small corpus are exploratory, not held-out validation.

Layer 3 checks the default cohort against the configured identification target.
Layer 4 checks the configured overall kappa target for both judges, complete
observations, and available confidence intervals. A poor result remains a poor
result. The legacy `not_implemented` scorecard status denotes an absent judge
observation when no judge archive is supplied. CI remains offline layers 0–2.

The phase exit still requires completed blind labels, a measured judge baseline,
and a versioned prompt iteration with a scorecard diff or documented null result.
No paid measurement or prompt improvement is claimed by the offline tests.
