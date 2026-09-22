# Follow one run

Start with the four files in [`stages/`](src/acquirer_engine/stages). Their names
match the product workflow: **select → draft → review → render**. Review is
optional. [`pipeline.py`](src/acquirer_engine/pipeline.py) connects the stages;
[`cli.py`](src/acquirer_engine/cli.py) accepts the request and displays the result.

```text
cli.py:run_product
  → pipeline.py:execute_run
      → stages/select.py:select_buyers
      → factory.py:model_resources
      → pipeline.py:execute_prepared
          → factory.py:build_services
          → stages/draft.py:draft_pages
          → stages/review.py:review_portfolio
          → save run.json
  → stages/render.py:render_report
  → print paths and exit status
```

This outlines the live path; `execute_prepared` calls `build_services` before
launching the model stages. Replay supplies archived responses without creating
a provider client. The CLI renders only after the pipeline returns its result.

## The four stages

| Stage | Inputs and decision | Output |
| --- | --- | --- |
| [`select.py`](src/acquirer_engine/stages/select.py): `select_buyers` | Resolve target YAML/flags, load transactions and saved feedback, fit features, score buyers, build bounded evidence | Ranked buyers and their evidence packs |
| [`draft.py`](src/acquirer_engine/stages/draft.py): `draft_pages`, `draft_one` | Warm one response, fan out buyer tasks, let each analyst retrieve evidence and draft, validate and route failures | A verified page or an explicit failed-page result for every buyer |
| [`review.py`](src/acquirer_engine/stages/review.py): `review_portfolio` | When enabled, request portfolio verdicts and at most one revalidated revision per flagged page | Final pages plus separate reviewer outcomes; disabled review passes pages through |
| [`render.py`](src/acquirer_engine/stages/render.py): `render_report` | Resolve visible citations and canonical deal facts, then project public fields into templates | HTML and buyer Markdown; internal working notes remain in structured JSON |

`factory.py` owns provider lifetime and constructs agents, evidence tools,
recording, ledger, cache, and trace once. A buyer task receives those resources;
it does not create a new client. The pipeline freezes input snapshots and saves
outcomes independently of presentation.

## One buyer's draft and recovery

The full loop is in [`stages/draft.py`](src/acquirer_engine/stages/draft.py):

1. `draft_pages` primes the shared prompt prefix, then uses a semaphore to bound
   concurrent tasks while retaining ranked output order.
2. `draft_one` creates buyer-local evidence state, selects the normal or sparse
   agent, and keeps the attempt history until the page passes or recovery stops.
3. `generate` runs the injected agent and captures its messages, validation
   outcome, and explicit claim counts.
4. `next_route` selects pass, repair, escalation, or a failed-page banner from
   the outcome and configured limits.
5. `repair_history` attaches precise errors to the rejected output call while
   preserving the draft and retrieved evidence for the next attempt.

The current configuration permits one same-tier repair, with escalation disabled.
The optional reviewer is also disabled by default. [ROUTING.md](ROUTING.md)
separates these settings from historical recovery and ablation measurements.
Provider failures and resource limits stop the affected page without entering
validation repair. Other buyers continue. The CLI exits nonzero if any page or
portfolio review fails.

The agent's output validator is registered in `llm/agents.py` and calls
`validation/claims.py`. A model chooses tools and writes a draft; deterministic
checks decide whether to accept it or return errors. This boundary checks schema,
references, numbers, and limited prose patterns, not general economic truth.

## Dependencies before and after resource construction

[`deps.py`](src/acquirer_engine/deps.py) makes the lifecycle explicit:

- `Deps` contains only settings and logger, available during preparation.
- `deps.with_runtime(services)` creates `RuntimeDeps`, whose `runtime` is required.
- Drafting, review, and optional comparison summaries accept `RuntimeDeps`.
  Their signatures no longer suggest that model resources may be absent.
- `PageDeps` combines those shared runtime resources with one buyer's `ToolState`.
  `PageSession` retains the conversation for a possible reviewer revision.

Buyer-local state lives beside evidence queries in `llm/tools.py`. The verifier
receives only that buyer's initial pack and the evidence actually returned by its
tools. One buyer's mutable evidence is not shared with another buyer.

## Domain modules behind the stages

| Question | Where to look |
| --- | --- |
| How is the CSV validated and its quality measured? | [`data.py`](src/acquirer_engine/data.py): typed transactions, loading, identity checks, and quality report |
| How is eligible history fitted? | [`ranking/features.py`](src/acquirer_engine/ranking/features.py): buyer histories, sector similarity, and tag weights |
| Why this score and conviction? | [`ranking/scorer.py`](src/acquirer_engine/ranking/scorer.py): signals, shrinkage, weights, ordering, and conviction |
| What evidence is initially available or later resolved? | [`evidence/pack.py`](src/acquirer_engine/evidence/pack.py): stable IDs, statistics, core packs, and evidence lookup |
| Why did a number or citation fail? | `validation/claims.py`, `validation/numbers.py` |
| Which qualitative wording is checked? | `validation/prose.py`: recognized margin inversions, partial-history theme exclusivity, and configured boilerplate |
| Where do visible financial facts come from? | `stages/render.py` resolves source rows/statistics before rendering [`templates/`](src/acquirer_engine/templates) |
| How are frozen inputs and portable replay selected? | [`replay.py`](src/acquirer_engine/replay.py): snapshots, run history, integrity manifests, and strict policy matching |

The core pack prioritizes exact target-sector deals before recency within the row
and byte caps. Closed, Pending, and resolved counts retain full-history scope even
when displayed rows are truncated. Tools remain necessary for Closed valuation
comps and population sector benchmarks.

## Ten model-support modules

Workflow stages are outside `llm/`; this package supplies their reusable boundaries.

| Module | Responsibility |
| --- | --- |
| [`agents.py`](src/acquirer_engine/llm/agents.py) | Agent declarations, five typed tool bindings, output validation, and reviewer coverage checks |
| [`tools.py`](src/acquirer_engine/llm/tools.py) | Evidence queries, query schemas, buyer-local provenance, and continuation state |
| [`recording.py`](src/acquirer_engine/llm/recording.py) | Shared request boundary: deadlines, request identity, live/replay choice, usage, and failures |
| [`provider.py`](src/acquirer_engine/llm/provider.py) | Client creation, retry eligibility, output-schema compatibility, truncation, and safe error messages |
| [`cost.py`](src/acquirer_engine/llm/cost.py) | Returned-usage accounting, admission reservations, token estimates, and uncertain charges |
| [`results.py`](src/acquirer_engine/llm/results.py) | Typed attempts, pages, reviewer verdicts, and run artifacts |
| [`trace.py`](src/acquirer_engine/llm/trace.py) | Append-only events and exact historical response/failure matching |
| [`cache.py`](src/acquirer_engine/llm/cache.py) | Content-addressed request identity and atomic response reuse |
| [`config.py`](src/acquirer_engine/llm/config.py) | Typed execution policy, separate from constructing resources |
| [`framing.py`](src/acquirer_engine/llm/framing.py) | Escaped JSON data boundaries shared by drafting, comparison, and judging |

## Live and replay

- `acquirers run --fresh`: prepare current inputs and make provider requests.
- `acquirers run --replay`: first check an installed portable bundle for exact
  input, feedback, prompt, policy, and file-integrity agreement. If no bundle is
  installed, use matching response-cache entries. A mismatch has no paid fallback.
- `acquirers replay RUN_ID`: load that run's frozen `snapshot.json` and recorded
  `trace.jsonl`, then execute with no provider client.

`replay.py` owns saved inputs and bundle selection; `llm/trace.py` matches original
responses to conversations; `llm/cache.py` owns reusable responses by request key.
Those remain different contracts. Historical replay writes a new run with lineage,
never overwrites the original, and does not run old code. Explicit failures replay
as failures. Missing responses never become invented answers or usage.

## Evaluation takes another path

`acquirers eval` enters [`evals/command.py`](evals/command.py): `run_evaluation`.
The command assembles `PreparedEvaluation`, calls `evaluate` in
[`evals/harness.py`](evals/harness.py), and writes the scorecard through
`evals/scorecard.py`. Preparation modules describe what they measure:

| Preparation | Module and function |
| --- | --- |
| Ranking holdout, baselines, ablations | `evals/ranking/prepare.py`: `prepare_ranking` |
| Evidence fixtures and groundedness | `evals/groundedness.py`: `prepare_groundedness` |
| Saved analyst outcomes and cohort checks | `evals/analyst.py`: `prepare_analyst`, `load_runs` |
| Recovery and ablation observations | `evals/routing.py`: `prepare_routing` |
| Independent judge observations | `evals/judges/grading.py`: `prepare_judges` |

Judge corpus and evidence preparation live in `evals/judges/prepare.py`; typed
cases, verdicts, and outcomes live in `schema.py`; `command.py` owns provider
construction and execution entry. [JUDGING.md](JUDGING.md) describes the separate
blind-label, paid-judge, and replay paths.

Evaluation consumes saved runs and does not draft buyer pages. The product path
does not run graders. Missing independent calibration stays unmeasured. Structural
cleanup makes no new ranking, generation-quality, or speed claim; see
[docs/EVALS.md](docs/EVALS.md) for measured limits and retained provenance.

## Preferences and comparison

`stages/select.py` is the shared input path for product runs and comparisons.
`feedback/state.py` saves exclusions; `feedback/ranking.py` applies a disclosed
similarity penalty after the base scorer.

`comparison/command.py` selects two target portfolios, computes their differences
through `comparison/ranking.py`, and saves a table. Optional `comparison/summary.py`
uses the existing recorded model boundary, with one request and no output retry.
`comparison/results.py` retains summary failures separately from valid ranking
facts. Default comparison never constructs a provider client.
